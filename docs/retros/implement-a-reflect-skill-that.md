# Retro: Building reflect as a skill, then rebuilding it as a pi extension

**Date**: 2026-08-29
**Session**: 01a04a95-3ca9-76e8-9539-03e607414c78
**Transcript**: /home/vfeenstr/.pi/agent/sessions/--home-vfeenstr-devel-lab-agenterio-nidaro--/2026-08-28T22-54-49-513Z_01a04a95-3ca9-76e8-9539-03e607414c78.jsonl
**Duration / tokens / cost**: 25,809s; 6,864,606 total tokens (407,028 input, 67,242 output, 6,390,336 cacheRead, 43,326 reasoning); cost 0.0; 100 tool calls, 88 assistant messages; model zai/glm-5.3-flash
**Extraction**: /home/vfeenstr/devel/lab/agenterio/nidaro/docs/retros/implement-a-reflect-skill-that.extract.json

An earlier retro (`docs/retros/implement-reflect-skill.md`, written by the session's own first reflect run) covers the build of the skill up to its first dispatch. This retro covers the whole session, including the half that retro did not see. The transcript's tail is the dispatch of this very review (92bdbf02, 6bbeef5a); friction inherent to a review running is excluded.

## What happened

The user asked for a user-initiated reflect skill that hands the current session log to a separate harness instance running as a background process (4a732a12). The agent read the repo's writing skills, derived pi's session format, researched prior art (agent-retro, Claude Code /insights), and shipped `.agents/skills/reflect/` (extractor, reviewer brief, SKILL.md), then cleared both aufsicht gates after a long pinned-toolchain discovery loop (4844b655 through 541d9575). The user invoked the skill and its first run produced a retro end to end (d5d7b01c through 64b47381), but the user then redirected: reflect would do better as a pi extension (28cc07db). The agent weighed the trade-offs with doc evidence, asked, and on approval built `.pi/extensions/reflect/` and retired the skill. Verifying the detached reviewer then took roughly 20 calls of process forensics, ending in the `setsid -f` fix and a green final test (6bbeef5a); this retro is that pipeline's second real output.

## What worked

- **The skill ran first try in production** (d5d7b01c, cff92232, 198b32e2, f2783dd1, 64b47381): locate, extract, spawn, wait; the 9KB retro landed without a misstep. The one prior art idea that mattered most, proposals must carry actual text, is visible in both retros' tables.
- **The pivot was evidence-first, not reflexive** (745753bf, d211af44, 49b1c65b, 138/49b1c65b): before agreeing with the user's hunch, the agent read the extension docs, produced an honest "what the extension does not fix" section, and offered three options via `ask_user` (3573e7fa). The resulting design also improves on the skill mechanically: slug derivation, placeholder substitution, and spawn parameters moved from model judgment into code (`index.ts`), which is the repo's own "prefer deterministic code" rule applied to itself.
- **Gate honesty** (dc39edff, 4e9b155d, 82a26858, 014a01e6): real gate findings were fixed by refactoring and pin alignment, not worked around; the text-mode `seek` bug was self-caught before any gate flagged it.
- **Test hygiene under pressure** (b75db1d3): the agent killed its own reproduction process once it realized it would race the real test on the same retro path, and re-ran clean.

## Friction

- **"Background process" shipped as a session-scoped subagent** (4a732a12 vs 2d881eaa, 64b47381; admitted at 49b1c65b: "The background process is not actually background"). The spec's key noun was delivered by the one mechanism that cannot survive the session ending, and the gap surfaced only when the user pushed (28cc07db), triggering a full re-implementation. Root cause chain: the global `subagents` skill (read at 18493c53) documents spawn/check/wait/cancel mechanics but says nothing about subagent lifetime, so the agent equated "different instance" with `subagent_spawn`; no design step checked spec nouns against mechanism properties; the agent's own retro tool also reviewed the run without flagging it. The pivot itself was the user's call and is not friction; delivering on the spec the first time was the agent's job.
- **The detached reviewer was unobservable, so verification became forensics** (0c4a59a5, 7fd8d303 through b75db1d3, 6b5f4dd4 through 2f4a3332, 92bdbf02 through 6bbeef5a; roughly 12 of the last 25 calls). pgrep matched its own command line twice (5300fe5b, ad50c120); `ps` argv truncation sent the agent down a false lead (f8547c9d, b75db1d3); the real killer, pi reaping direct children at shutdown, was derived empirically (2f4a3332); after the `setsid -f` fix, the verification scan assumed the old argv shape and false-negatived once more (af2f29c3, 999cd708). Root cause: the extension spawns with `stdio: "ignore"` and records neither a pid nor a log, so every hypothesis ("did it start? did it crash? who killed it?") had to be tested against the process table, and pi's child-reaping behavior is documented nowhere the agent looked. One observable artifact (log file, pidfile) would have collapsed the loop to a single `cat`.
- **Pinned-toolchain discovery, still unremediated** (4844b655, 3c4ebfbc, 037f9fe6, e7bdbe0b, cc05c12a, ad593075, d73654b3, 5f475bb8, 541d9575): fully analyzed in the first retro. It remains open: `AGENTS.md` still names `.quality/toolchain.lock` only as provenance ("come from the pinned aufsicht runner recorded in..."), not as instructions, and the agent probed only `pyproject.toml` before concluding "defaults apply" (3c4ebfbc). Same session, same gap, and it will fire again on the next Python change.
- **Self-test asserted against the live, growing session log** (6a95b64a, c6aa4747, 20422cf1): the exact-count assert failed spuriously and was weakened to invariants. The first retro proposed the fixture and the checklist bullet; neither is applied, and the extractor now lives on at `.pi/extensions/reflect/scripts/extract.py`, so the gap moved with it.
- **unslop self-audit miss** (b24580c0): the agent's thinking claims "no em dashes, plain speech" for its own reply, while the visible summary contains three em dashes in bold-lead-in bullets ("**`SKILL.md`** — user-invoked only..."). The skill's description says "Must always apply" and its step 4 says self-audit, but the step never names the agent's outgoing reply as in-scope, and the audit was spent on repo files instead.
- **Edit oldText fumbling** (cbe908df, 8a26a312, cb375a0e): two failed edits on `index.ts` with mangled tab indentation ("items", "itemso" pasted into oldText) before reading the file. One-off tool friction, self-corrected in three calls; noted only because read-before-edit was skipped exactly where indentation was invisible.

## Skill pass

| Skill | Verdict |
|---|---|
| subagents (global, `~/.pi/agent/skills/subagents/SKILL.md`) | Missing guidance: no lifetime semantics, no detached-process alternative. The agent read the skill (18493c53), then spent the session's last ~20 calls deriving exactly that knowledge by experiment (2f4a3332). Strongest gap in the session. Fix drafted as proposal 2. |
| writing-agent-skills | Under-specification (carried over): section 4 lists `tests/` in the layout, but the section 5 ship checklist never requires scripts to pass against a fixture, so the extractor shipped verified only against live state (c6aa4747). Fix drafted as proposal 4. |
| unslop | Wrong-ish guidance: step 4's self-audit reads as scoped to documents; the agent's own reply escaped it (b24580c0, three em dashes while claiming compliance in thinking). Fix drafted as proposal 6. |
| writing-for-agents (+ SKILL-MECHANICS) | No gap: loaded before writing content (95b7b7a6, 8892352e); the brief and SKILL.md follow its completion-criterion and pointer rules, and the extension carries the same discipline into code. |
| rohrpost | No gap: consulted at design time (c73a9cf4, 61fed3d5) and integrated as the ticket path for heavy proposals (retro-1's step 5; `APPLY_INSTRUCTIONS` in `index.ts`). |

## Recurrence pass

- Pinned-toolchain mismatch: recurs on the next Python change; cheapest durable form is a pointer line where conventions already live (`AGENTS.md` workflow list). Protected path, so human approval needed. Justification: the pins and config already exist; only the pointer wording fails to instruct.
- Subagent lifetime: recurs whenever a user says "background"; cheapest form is an edit to the existing global subagents skill rather than a new one. Justification: the knowledge is three sentences at the point the agent already reads before spawning.
- Reviewer observability: recurs on every future edit to the extension and every silent review failure; cheapest form is the deterministic fix in the code itself (log + pidfile), per the repo rule that deterministic code carries workflows.
- Extractor fixture: recurs on every extractor edit; the fixture file plus the checklist bullet from proposal 4 cover it.
- Session-dir naming (37bd1726, c19c1152): now moot; the extension uses `ctx.sessionManager.getSessionFile()` and the brief carries the path. Acknowledged.
- pgrep self-match (5300fe5b, ad50c120): generic tool hygiene, not worth a rule; the pidfile removes this session's recurring instance. Acknowledged.

## Proposals

| # | Type | Change | Where | Evidence | Status |
|---|------|--------|-------|----------|--------|
| 1 | rule-update | Pinned-toolchain step in the aufsicht agent workflow (text below; same as retro-1 proposal 1, still unapplied) | `AGENTS.md`, "Quality guardrails (aufsicht)", Agent workflow list (protected path) | 3c4ebfbc, 037f9fe6, cc05c12a, 5f475bb8, 541d9575 | done |
| 2 | skill-update | Add "Lifetime and detached work" section to the global subagents skill (text below) | `~/.pi/agent/skills/subagents/SKILL.md`, new section before "## Spawn and Manage" | 4a732a12, 18493c53, 2d881eaa, 28cc07db, 49b1c65b, 2f4a3332 | done (lifetime paragraph added, tmux/herdr pointer included) |
| 3 | tool-create | Give the detached reviewer a log file and pidfile (diff below) | `.pi/extensions/reflect/index.ts`, spawn block and watcher | 5300fe5b, ad50c120, f8547c9d, 2f4a3332, af2f29c3, 999cd708 | done (log file; pidfile unnecessary, completion is detected by the retro file appearing) |
| 4 | skill-update | Require scripts to pass against a fixture in the ship checklist (retro-1 proposal 2, still unapplied) | `.agents/skills/writing-agent-skills/SKILL.md`, section 5 checklist, append bullet | c6aa4747, 20422cf1 | done |
| 5 | tool-create | Ship the extractor fixture with the extension (retro-1 proposal 3, retargeted from the retired skill) | `.pi/extensions/reflect/tests/session.jsonl` (new; content in retro-1) | c6aa4747, 20422cf1 | deferred |
| 6 | skill-update | Make the unslop self-audit cover the agent's own reply (text below) | `.agents/skills/unslop/SKILL.md`, Process step 4 | b24580c0 | proposed (not yet user-decided) |
| 7 | acknowledge | Session-dir naming: superseded by the extension's `getSessionFile()` path | — | 37bd1726, c19c1152 | acknowledged |
| 8 | acknowledge | pgrep self-match: one-off hygiene; proposal 3 removes the recurring instance | — | 5300fe5b, ad50c120 | acknowledged |

### Proposal 1 text (AGENTS.md is a protected path; apply only with explicit user approval)

Before:

```
4. Run quality-fast. Fix failures. Repeat until clean.
5. Run quality-full.
```

After:

```
4. Format and lint changed Python only with the pinned analyzers:
   versions live in `.quality/toolchain.lock`, ruff config in
   `.quality/ruff.toml` (line-length 100). Command shape:
   `uvx ruff@<pin from toolchain.lock> format --config .quality/ruff.toml <paths>`.
   Ambient installs disagree with the pin and the config.
5. Run quality-fast. Fix failures. Repeat until clean.
6. Run quality-full.
```

### Proposal 2 text

Insert into `~/.pi/agent/skills/subagents/SKILL.md`, before "## Spawn and Manage":

```markdown
## Lifetime and detached work

A subagent lives inside the invoking session: closing the session kills it,
and `subagent_wait` holds the parent open until the run finishes. When the
work must outlive the session (the user asks for a "background process"),
spawn a detached OS process instead and leave the result on disk:

    setsid -f pi -p "<self-contained brief>" --no-session --no-skills \
      --no-context-files --no-extensions --thinking high

`setsid -f` reparents the worker to init, so the host exiting does not reap
it. Poll for the output file rather than the pid: after `setsid -f` the
spawned pid is a short-lived fork stub, and `pgrep -f` matches its own
command line, so scan `/proc/*/cmdline` for a marker unique to the brief.
```

### Proposal 3 text (sketch; apply inside the existing spawn block of `index.ts`)

Before:

```ts
const child = spawn(
    "setsid",
    ["-f", "pi", "-p", brief, /* flags */],
    { cwd: ctx.cwd, detached: true, stdio: "ignore" },
);
```

After:

```ts
const logPath = `${retroPath}.reviewer.log`;
const pidPath = `${retroPath}.pid`;
const log = await open(logPath, "a"); // add `open` to the node:fs/promises import
const child = spawn(
    "setsid",
    ["-f", "sh", "-c",
      'echo $$ > "$PIDFILE"; exec pi -p "$BRIEF" --no-session --no-skills --no-context-files --no-extensions --thinking high',
      "sh"],
    { cwd: ctx.cwd, detached: true,
      env: { ...process.env, BRIEF: brief, PIDFILE: pidPath },
      stdio: ["ignore", log.fd, log.fd] },
);
```

On completion or timeout the watcher deletes `pidPath` (add `rm` to the import) and may read it to detect early reviewer death instead of polling the full 30 minutes. The log turns "the reviewer died silently" into a one-`cat` diagnosis; during this session its absence cost the forensic loop at 5300fe5b through 2f4a3332 and the false-negative rescan at af2f29c3 through 999cd708.

### Proposal 4 text

Append to the section 5 checklist in `.agents/skills/writing-agent-skills/SKILL.md`:

```
- Every script in `scripts/` runs clean against a fixture in `tests/`,
  not against live state that shifts between runs.
```

### Proposal 5 text

Create `.pi/extensions/reflect/tests/session.jsonl` with the four-line synthetic session given in retro-1 proposal 3 (one user turn, one `read` call, `totalTokens` 15); completion criterion unchanged: `python3 scripts/extract.py tests/session.jsonl` reports those counts. Proposal 4's checklist bullet is what makes a future editor reach for it.

### Proposal 6 text

In `.agents/skills/unslop/SKILL.md`, Process step 4:

Before:

```
4. Self-audit: "What makes this obviously AI generated?" Fix remaining tells.
```

After:

```
4. Self-audit: "What makes this obviously AI generated?" Fix remaining tells.
   This includes the reply you are about to send, not only files you edited.
```

## Questions for the user

- Proposal 1 edits `AGENTS.md`, a protected path under the aufsicht guardrails; it adds a workflow pointer and weakens no threshold. Approve?
- `RTK.md` (imported into `AGENTS.md`) says to prefix every shell command with `rtk`, and `rtk` 0.42.2 is installed, yet all 65 bash calls in this session ran bare. Is the rule meant for pi sessions too (then this is an agent-side failure worth a sharper pointer) or Codex-only (then `RTK.md` should say so in its first line)?
- Retro-1's proposal rows were never walked or marked because the extension pivot interrupted the apply loop. When applying this retro: mark retro-1 rows 1 and 2 as re-raised here, row 3 as retargeted (proposal 5), and rows 4-5 as acknowledged?
