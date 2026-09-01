# Retro: School portal — chart to deployed slice, derailed by a workflow-script bug hunt

**Date**: 2026-09-01
**Session**: 01a05441-0b43-79fe-96d9-9d44687b96e3
**Transcript**: /home/vfeenstr/.pi/agent/sessions/--home-vfeenstr-devel-lab-agenterio-nidaro--/2026-08-30T19-59-04-003Z_01a05441-0b43-79fe-96d9-9d44687b96e3.jsonl
**Duration / tokens / cost**: 123,545 s (~34 h wall, mostly user idle between turns) / input 1,806,062, output 233,442, cacheRead 80,298,112, reasoning 111,654, total 82,337,616 / $0.00 (zai/glm-5.3-flash); 409 tool calls, 10 bash errors
**Extraction**: /home/vfeenstr/devel/lab/agenterio/nidaro/docs/retros/wayfinder-the-school-should-show.extract.json

## What happened

One session carried the school effort end to end: `/wayfinder` charting of `[school]` (research-first pivot after the user's redirect, 40a5571e), three parallel research subagents, the `[school-4]` shortlist decision, dossier merge + ADR 0002, then the `[portal]` implementation map and six straight `/wayfinder portal` tickets — landing zone, account config, page prototype (user picked variant B), school domain, portal page, what-to-pack, finish — each red→green, gated, merged. The user then asked for a CI fix and a workflow orchestrating all agent-ready tickets. The CI fix was sound (the agent's own [portal-10] integration test violated the house probe-and-skip convention; fixed, both workflows green, 462cf9dc–56ac097c). The orchestration then failed three launches to the agent's own JavaScript (shadowed `parallel` global; thunks passed to `Promise.all`), was misdiagnosed as "this runtime cannot run workflow agents concurrently at all" (0184135f), and the fourth, sequential run was killed mid-flight by a disk-quota crash (a3a6298e) from accumulated worktree venvs. Recovery by hand merged all six build branches with gates and closed the `[portal]` map; the prod deploy then caught three shipped defects (conflict markers in `migrations/env.py`, two alembic heads, an unsupported Quadlet key), all fixed (204b778d, 5d8c0a9).

## What worked

- **Research-first pivot executed cleanly** (40a5571e → 8deaf829): the user's redirect from manual-entry to a passive, research-first portal changed the map's shape; the agent reset the grill, charted `[school]` with three research tickets, and fired three parallel research subagents that landed dossiers on branches without rework.
- **Grilling with confidence scores, once adopted** (f578ef85 onward): after the user asked for scores (505e8318), every recommendation carried a percentage plus a flip condition; rounds settled in one reply ("Agreed with all", 29afc3fb, b96191a5) and one reality-check from the user (two kids = two parent accounts, 20a17563) *simplified* the [portal-3] design. The agent wrote the rule into the wayfinder skill itself the same night (git `8402934`).
- **Prototype run-loop fired as repaired** (6eec5b81–9b5e2395): worktree, three variants, self-judged via chrome-agent screenshots before handover, one defect found and fixed, server torn down at resolution — the previous retro's UI.md step worked; the user decided in five words ("I like B best", fccf7bb6).
- **Finishing work caught a real bug** (5c4eb7d8): the idempotent-seed run exposed SQLAlchemy's INSERT-before-DELETE flush ordering in `replace_lessons`; fixed with delete-flush-insert plus an integration regression test on real PostgreSQL.
- **Deploy verification did its job** (204b778d): the deploy gate's `Requires=` chain refused to start half-broken, surfacing the env.py markers, the dual alembic heads, and the silently-skipped chromium unit before they could become outages.

## Friction

- **Three workflow launches failed on the agent's own script bugs, then got misdiagnosed as a runtime limitation** (22ba5da3, bb92ebf6, 3b5fc977, 10621de1, 6a91d978, 5f9347df, 6fabb563, 58aabfd3, 0184135f): run 1 declared `const parallel = [...]` (shadowing the sandbox-provided `parallel()` helper) and called the array as a function → `TypeError: parallel is not a function` after the 78-minute foundation phase had completed. Runs 2–3 passed *thunks* to `Promise.all`, which resolves immediately without invoking them — `agent()` was never called; transcripts.json holds exactly one transcript (the integrate agent) and all six builds report `ok:false` with empty errors. The agent theorized a 45-second spawn guard and provider saturation (5f9347df), then concluded "concurrency itself is the problem" (58aabfd3) and "this runtime cannot run workflow agents concurrently at all" (0184135f) — a false runtime fact narrated to the user — and rebuilt strictly sequential (~1.5–2.5 h projected). The documented API (`await parallel([() => agent(...)], { concurrency? })`) is in the workflow tool description the agent itself quoted at 3b5fc977; the pi docs dir it then searched has no workflows page. Root cause: never checked the script's actual semantics against the documented API; when results looked empty, theorized about the runtime instead of printing `typeof r` on the returned objects, which would have shown functions, not results.
- **No worktree/venv/disk discipline; the session died of EDQUOT mid-orchestration** (a3a6298e, 3f5588b3, 1b4522cf, 6aefeb61, 39096e12, 88d98d1e): every build agent ran `uv run` inside its `/tmp/wf-*` worktree, materializing a ~253 MB `.venv` each; ~1.4 GB of stale aufsicht worktrees sat in `~/.cache`; the iCloud agent left a 291 MB `.venv-wf-icloud` at the repo root and repointed the main `.venv` symlink at it (later self-referential → ELOOP). Nothing checked disk headroom before a multi-hour run. Side effect: `aufsicht full` hit pyright 900 s timeouts (747194c4) because `pyrightconfig.json` excludes only `.venv` (protected file) and the stray env was enumerable. Root cause: the worktree-build playbook this repo already knows it needs (ticket NIDAR-fhhz1p, still open) covers mechanics but nothing about venv cost, disk preflight, or post-merge cleanup.
- **Build briefs guaranteed a migration-head collision** (22ba5da3 vs ce72f609, 1bfc6a68): the foundation phase pre-assigned revisions 0006–0009 "so the chain can't collide", but every build brief then said "the current head is 0009_connector_household_config — set down_revision accordingly" — so WhatsApp (0010) and Google (0011) both chained off 0009 and alembic reported two heads, found only at deploy. Builders in isolated worktrees from the same base cannot see siblings' migrations; the working mitigation existed one phase earlier and was dropped. Root cause: orchestration design inconsistency, not concurrency.
- **`migrations/env.py` shipped with conflict markers; only prod caught it** (a1d6b066, 204b778d): recovery merges committed the file broken; "the unit suite never imports it, so every gate stayed green", and the agent's post-merge marker sweep scanned only `src/`. The `resolving-merge-conflicts` skill was never invoked in the whole recovery (its sole transcript mention is an `ls` during deploy, a85e3a97) — and even if invoked it has no whole-repo marker-sweep step, so this is missing guidance, not just a missed trigger. Root cause: no deterministic conflict-marker check anywhere in the gates, and the skill doesn't carry the sweep.
- **Four wrong-directory/wrong-path mistakes across worktree juggling** (114321c7, e6a0f4bc, 17be46c7, 3a411e8e): merges run from a removed worktree's cwd, files written into "the removed portal-8 worktree path", a resolved file written "into the real repo file and clean[ing] up the stray". Each cost detect-fix-redo cycles. Root cause: long-lived `/tmp` worktrees plus cwd assumptions; no cd-back-and-verify habit after worktree operations.
- **Bash string-surgery corrupted files four times; the edit tool existed for all four** (231bce37, 720b91bb, 088258ce, c39e6ac2): a regex script "clobbered the test file (bad conditional)", string surgery left tasks.py with broken syntax ("top of the file is shredded"), a replace script "corrupted the array". Each corruption cost a full rewrite. Root cause: no rule pins file modifications to the edit/write tools; inline python replace felt natural under merge pressure.
- **Own integration test broke CI** (462cf9dc, 357d7099, 3d3deff5): the [portal-10] test assumed a migrated, seeded PostgreSQL; CI's test job runs neither and the aufsicht job has no database. The house precedent — `tests/integration/test_database.py` self-skipping — existed but is only discoverable by reading that file; the tdd skill says nothing about integration tests that need real infrastructure. Fixed properly (probe-and-skip), but a day later and via red CI.
- **rp accepted blocking edges to a nonexistent ticket** (4e773611, 82fa9f69): a typo'd id in `--blocked-by` produced edges to `NIDAR-3d0c8e`, which doesn't exist; the tracker rendered fine and the error was found by hand, then fixed with two more commands. Root cause: upstream rp validates neither `--blocked-by` nor `--parent` ids at creation (the issue-tracker doc, docs/agents/issue-tracker.md, documents exit 1 for "no such ticket" but creation doesn't enforce it).
- **Confidence scoring needed a user correction** (505e8318 → f578ef85): the session's first three grills carried recommendations without confidence scores; the user asked for scores "and continue doing this in this session like that". Root cause: the wayfinder skill had no Confidence section at session start; the agent added it mid-session (git `8402934`), so this gap is already closed in the artifact — the remaining question is whether standalone grilling should score too.

## Proposals

| # | Type | Change | Where | Evidence | Status |
|---|------|--------|-------|----------|--------|
| 1 | rule-update | Workflow-script API + verify-before-diagnosing line in Project rules | AGENTS.md: "Project rules" | 22ba5da3–0184135f, 3b5fc977 | done |
| 2 | skill-create | Parallel-builds playbook skill (absorbs open ticket NIDAR-fhhz1p; adds venv/disk, migration-head, wiring-partition, workflow-API sections) | skill-manager Home: skills/engineering/process/parallel-builds, in dev-default, installed via skm | a3a6298e, 6aefeb61, 747194c4, 1bfc6a68, 33784980 | done |
| 3 | skill-update | Whole-repo conflict-marker sweep + union-check steps | .agents/skills/resolving-merge-conflicts/SKILL.md: steps 3–4 | a1d6b066, 9a3e258a, a85e3a97 | done |
| 4 | rule-update | Integration tests needing real PostgreSQL must probe-and-skip | AGENTS.md: "Project rules" | 462cf9dc, 357d7099 | done |
| 5 | rule-update | File edits go through edit/write tools, not bash string surgery | AGENTS.md: "Project rules" | 231bce37, 720b91bb, 088258ce, c39e6ac2 | done |
| 6 | doc-update | "Adding or changing a Quadlet unit" subsection (update.sh doesn't install units; verify generation) | docs/deployment.md: "Deploying a new build" | db764fcf, 4d9c0971 | done |
| 7 | tool-create | rp: validate `--blocked-by`/`--parent` ids exist at creation, exit 1 on unknown id (upstream github.com/code-factorio/rohrpost) | upstream rp CLI (code-factorio/rohrpost#14) | 4e773611, 82fa9f69 | done |
| 8 | acknowledge | Confidence rule already added to the wayfinder skill by the session itself (git `8402934`) | .agents/skills/wayfinder/SKILL.md: "Confidence" | 505e8318, f578ef85 | done |

### 1. AGENTS.md — "Project rules", append one bullet

```markdown
- Workflow scripts: `agent`, `parallel`, `phase`, and `args` are provided
  globals — never declare variables with those names, pass thunks to
  `parallel([...])` (never to `Promise.all`, which does not invoke them), and
  before redesigning around a suspected runtime limitation, verify it:
  inspect what the script actually returned (agents that never ran leave no
  transcript and empty results) and re-read the tool's own API description.
```

Justification: cheapest durable form (pointer line, recurrence order 1); the misdiagnosed "runtime cannot run concurrent agents" is now in the session narrative and will mislead the next orchestration unless written against.

### 2. `~/.pi/agent/skills/parallel-builds/SKILL.md` — new skill (supersedes ticket NIDAR-fhhz1p's scope, adding what this session proved)

Write the skill with the ticket's six points (workflow tool as default orchestrator; fresh-worktree unit-suite check; pre-spawn gate verdict with accepted-failure list; file partitioning; merge order with gates on main; worktrunk consideration) **plus** these session-derived sections:

```markdown
## Environments and disk

- Every worktree that runs `uv run` materializes a full `.venv` (~250 MB in
  this project). Before launching a multi-builder run: `df -h /tmp .` and
  `git worktree list`; clean stale worktrees and env dirs first. A full disk
  kills the host session mid-run (EDQUOT), not just the workflow.
- Builders must not create environments inside the main checkout; a stray
  `.venv-*` at the repo root is enumerated by pyright (only `.venv` is
  excluded in the protected pyrightconfig) and turns gates into 900 s
  timeouts.
- The integration agent removes each worktree (`git worktree remove`) and its
  env dir immediately after merging the branch.

## Migrations

- Pre-assign migration revision numbers in every builder brief that may add a
  migration; builders in isolated worktrees cannot see sibling branches, and
  "chain off the current head" guarantees multiple heads when two builders
  add one. Verify single head (`alembic heads`) at each merge, not at deploy.

## Shared wiring

- Files several builders will touch (container wiring, task registration,
  connector registry) get one of: a single owner builder, a pinned contract
  in every brief (names, registration shape), or sequential builds that
  rebase. Three builders each invented their own sweep design; uniting them
  by hand cost a day. After resolving, verify both sides' registrations and
  constructor calls survived (auto-merged hunks drop lines above the
  conflict).
```

Justification: form 3 (new skill); the ticket already tracks it and this session supplied the failure evidence the ticket lacks.

### 3. .agents/skills/resolving-merge-conflicts/SKILL.md — extend steps 3–4

Before (step 3 ends):

```markdown
3. **Resolve each hunk.** Preserve both intents where possible. Where incompatible, pick the one matching the merge's stated goal and note the trade-off. Do **not** invent new behaviour. Always resolve; never `--abort`.
```

After:

```markdown
3. **Resolve each hunk.** Preserve both intents where possible. Where incompatible, pick the one matching the merge's stated goal and note the trade-off. Do **not** invent new behaviour. Always resolve; never `--abort`. When uniting branches that touched the same wiring (container, registry, task registration), re-read the resolved file whole: auto-merged hunks silently drop lines above the conflict, and each side's registrations and constructor calls must all survive.
```

Insert a new step between 4 and 5:

```markdown
4b. **Sweep the whole repository for conflict markers**, not only the files you edited: `rg -n '^(<<<<<<<|=======|>>>>>>>)' -g '!.venv*'` from the repo root. No automated gate covers files no test imports (e.g. `migrations/env.py`), so a marker there reaches production with every gate green.
```

Justification: form 2 (edit existing skill); the session did marker sweeps that scanned only `src/` and shipped `migrations/env.py` broken to prod.

### 4. AGENTS.md — "Project rules", append one bullet

```markdown
- Integration tests that need real PostgreSQL must probe-and-skip, following
  `tests/integration/test_database.py`: CI's test job provides an empty
  database (no migrations, no seed) and the aufsicht job has none. Verify a
  new integration test against an unmigrated database before pushing.
```

Justification: form 1; the convention exists only inside one test file, and the next integration test will break CI again the same way.

### 5. AGENTS.md — "Project rules", append one bullet

```markdown
- Modify files with the edit and write tools, not with inline python/sed
  string-replacement in bash; a bad match silently corrupts the file, and
  every corruption costs a full rewrite.
```

Justification: form 1; four self-inflicted corruptions in one session, all in reach of the edit tool.

### 6. docs/deployment.md — new subsection after "Deploying a new build"

```markdown
### Adding or changing a Quadlet unit

`update.sh` rebuilds images and cycles the app units; it does **not** install
new unit files. After adding a `.container`/`.volume` file under
`deploy/quadlet/`, install it:

```bash
ln -sf ~/devel/lab/agenterio/nidaro/deploy/quadlet/nidaro-prod-<name>.container \
  ~/.config/containers/systemd/
systemctl --user daemon-reload
```

Then verify the unit actually generated: an unsupported key (e.g. `Init=` on
older Quadlets) makes the generator **silently skip the whole unit**.

```bash
systemctl --user list-unit-files 'nidaro-prod-*'   # the new unit must be listed
```
```

Justification: the session lost time rediscovering both facts at deploy time (db764fcf, 4d9c0971); the doc's own "Deploying a new build" section is where a deployer looks.

### 7. Upstream rp — id validation (file in the Rohrpost repo)

`rp new --blocked-by <id>` and `--parent <id>` should exit 1 (domain failure) when the referenced id does not exist, matching the documented exit-code contract; batch acceptance of unknown ids produced blocking edges to `NIDAR-3d0c8e` that only manual inspection caught. Not applicable in this repo — proposal is to file upstream and reference it from docs/agents/issue-tracker.md once fixed.

## Questions for the user

- Should confidence scores extend to standalone grilling sessions (one line in `grilling/SKILL.md`'s question format), or stay scoped to wayfinder map work where the rule now lives?
- The parallel-builds playbook ticket targets the global `~/.pi/agent/skills/` — approve writing it there, or keep a repo-local copy under `.agents/skills/` so it versions with the repo?
- Session narrative told you "this runtime cannot run workflow agents concurrently at all" (0184135f) — the evidence says that was a script bug, and the documented `parallel()` helper was never actually exercised. Want a cheap two-agent `parallel()` smoke run before the next orchestration trusts sequential-only?
- File the rp id-validation issue upstream (proposal 7), or track it as a Rohrpost ticket here?
