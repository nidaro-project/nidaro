/**
 * reflect: review the current session with a detached headless pi instance.
 *
 * /reflect              review the current session
 * /reflect <session>    review a specific session log (.jsonl path)
 *
 * The command extracts a compact view of the transcript, fills the reviewer
 * brief in code, and spawns a detached `pi -p` process that writes the retro
 * to docs/retros/. The detached process survives closing this session; while
 * the session stays open, a watcher injects the finished retro into the
 * conversation. Nothing runs unless the user types the command.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { spawn } from "node:child_process";
import { access, mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { openSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const EXTENSION_DIR = dirname(fileURLToPath(import.meta.url));
const BRIEF_PATH = join(EXTENSION_DIR, "review-prompt.md");
const EXTRACT_SCRIPT = join(EXTENSION_DIR, "scripts", "extract.py");
const POLL_MS = 5000;
const REVIEW_TIMEOUT_MS = 30 * 60 * 1000;

interface ActiveRun {
	retroPath: string;
	timer: NodeJS.Timeout;
}

let activeRun: ActiveRun | undefined;

function slugFromText(text: string): string {
	const words = text
		.toLowerCase()
		.replace(/[^a-z0-9\s-]/g, " ")
		.split(/\s+/)
		.filter(Boolean)
		.slice(0, 5);
	return words.length > 0 ? words.join("-") : "session";
}

async function fileExists(path: string): Promise<boolean> {
	try {
		await access(path);
		return true;
	} catch {
		return false;
	}
}

function sanitizedEnv(): NodeJS.ProcessEnv {
	// The host pi exports PI_* state (session file, mode, extension paths);
	// the reviewer must start like a plain CLI invocation.
	const env: NodeJS.ProcessEnv = { ...process.env };
	for (const key of Object.keys(env)) {
		if (key.startsWith("PI_")) delete env[key];
	}
	return env;
}

const APPLY_INSTRUCTIONS = [
	"Read the retro file, summarize the session in a few sentences, then show",
	"the full proposal table with its evidence. Walk the user through the",
	"proposals one by one: apply quick edits they approve (skill, rule, or doc",
	"lines) and show each diff; offer a Rohrpost ticket for bigger work; mark",
	"every row done, deferred, or rejected in the retro file.",
].join(" ");

export default function reflectExtension(pi: ExtensionAPI) {
	pi.registerCommand("reflect", {
		description:
			"Review this session with a detached pi instance; writes docs/retros/<slug>.md",
		handler: async (args, ctx) => {
			if (activeRun) {
				ctx.ui.notify("reflect: a review is already running", "error");
				return;
			}

			const requested = args.trim();
			const sessionFile = requested
				? resolve(ctx.cwd, requested)
				: (ctx.sessionManager.getSessionFile() ?? undefined);
			if (!sessionFile || !(await fileExists(sessionFile))) {
				ctx.ui.notify("reflect: no session log to review", "error");
				return;
			}

			const retroDir = join(ctx.cwd, "docs", "retros");
			await mkdir(retroDir, { recursive: true });
			const tmpExtract = join(retroDir, ".reflect-extract.tmp.json");

			const extracted = await pi.exec("python3", [EXTRACT_SCRIPT, sessionFile]);
			if (extracted.code !== 0) {
				ctx.ui.notify(
					`reflect: extractor failed: ${extracted.stderr.slice(0, 200)}`,
					"error",
				);
				return;
			}
			await writeFile(tmpExtract, extracted.stdout, "utf8");

			const extract = JSON.parse(await readFile(tmpExtract, "utf8")) as {
				arc?: Array<{ role?: string; text?: string }>;
			};
			const firstUserText =
				extract.arc?.find((row) => row.role === "user")?.text ?? "";
			const slug = slugFromText(firstUserText);
			const extractPath = join(retroDir, `${slug}.extract.json`);
			await rename(tmpExtract, extractPath);
			const retroPath = join(retroDir, `${slug}.md`);

			const brief = (await readFile(BRIEF_PATH, "utf8"))
				.replaceAll("{{REPO_ROOT}}", ctx.cwd)
				.replaceAll("{{SESSION_LOG}}", sessionFile)
				.replaceAll("{{EXTRACT_PATH}}", extractPath)
				.replaceAll("{{RETRO_PATH}}", retroPath);

			// setsid -f forks once more, so the reviewer reparents to init
			// immediately; a direct child gets killed when the host pi process
			// exits and reaps its children. Output lands in a log next to the
			// retro so a dead reviewer explains itself in one read.
			const logPath = `${retroPath}.log`;
			const logFd = openSync(logPath, "a");
			const child = spawn(
				"setsid",
				[
					"-f",
					"pi",
					"-p",
					brief,
					"--no-session",
					"--no-skills",
					"--no-context-files",
					"--no-extensions",
					"--thinking",
					"high",
				],
				{ cwd: ctx.cwd, detached: true, stdio: ["ignore", logFd, logFd], env: sanitizedEnv() },
			);
			child.unref();

			ctx.ui.notify(
				`reflect: review running in the background; retro at ${retroPath}, log at ${logPath}`,
				"info",
			);

			if (ctx.mode !== "tui") return;

			// The reviewer is a daemonized grandchild, so its real pid is not
			// observable here. Completion is detected by the retro file
			// appearing; the cap keeps a crashed review from polling forever.
			const startedAt = Date.now();
			const timer = setInterval(async () => {
				if (await fileExists(retroPath)) {
					clearInterval(timer);
					activeRun = undefined;
					const message = {
						customType: "reflect",
						content: `The reflect review finished. Retro file: ${retroPath}\n\n${APPLY_INSTRUCTIONS}`,
						display: true,
					};
					if (ctx.isIdle()) {
						pi.sendMessage(message, { triggerTurn: true });
					} else {
						pi.sendMessage(message, { deliverAs: "followUp" });
					}
					return;
				}
				if (Date.now() - startedAt > REVIEW_TIMEOUT_MS) {
					clearInterval(timer);
					activeRun = undefined;
					ctx.ui.notify(
						`reflect: review did not finish within 30 minutes; see ${logPath}`,
						"error",
					);
				}
			}, POLL_MS);
			timer.unref();
			activeRun = { retroPath, timer };
		},
	});

	pi.on("session_shutdown", () => {
		if (activeRun) {
			clearInterval(activeRun.timer);
			activeRun = undefined;
		}
	});
}
