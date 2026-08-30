# Retro: Wayfinder calendar v1 — charted, decided, and built to done, with one wiped ticket body

**Date**: 2026-08-30
**Session**: 01a04f89-04d5-75c5-b03a-99bb32df167b
**Transcript**: /home/vfeenstr/.pi/agent/sessions/--home-vfeenstr-devel-lab-agenterio-nidaro--/2026-08-29T21-59-34-869Z_01a04f89-04d5-75c5-b03a-99bb32df167b.jsonl
**Duration / tokens / cost**: 66,916 s wall clock (~18.6 h, 5 user returns) · 17,783,638 tokens (input 1,244,488 / output 147,470 / cache-read 16,391,680 / reasoning 93,816) · $0.00 · zai/glm-5.3-flash · 150 tool calls, 15 user turns, 0 compactions
**Extraction**: /home/vfeenstr/devel/lab/agenterio/nidaro/docs/retros/skill-name-wayfinder-location-home.extract.json

## What happened

A loose idea — "a calendar implementation: special things, not meetings" — was charted with wayfinder into the `[cal]` map: destination = the implemented `/calendar` page (the map carries execution). Four decision tickets were grilled through over three returns — activity shape, recurrence storage (read-time expansion, weekday int-array, no RRULE), a three-variant prototype resolved as a hybrid (month wall grid + week/day agenda, per-device remembered view), and the backend surface — each closing with a recorded resolution, map update, and glossary term. The four graduated build tickets then ran as worktree subagents (cal-5+cal-6 in parallel, then cal-7, cal-8), merged with validation that caught real integration breakage and two latent pre-existing bugs, and the map completed with `/calendar` live, 104 tests green, and gates fully green after the user's own deptry fix. Along the way one mutation incident wiped `[cal-4]`'s ticket body (restored verbatim), and a broken deptry ratchet was discovered mid-flight rather than at baseline.

## What worked

- **Wayfinder discipline**: claim-before-work on every ticket, one ticket per invocation, decisions living in tickets with the map as index, fog graduated promptly, and the cal-2 session even caught and corrected its own charting mis-file (fog → out-of-scope, `71c88ae4` → `f439b0d9`).
- **Grilling quality**: repo facts gathered before every round (`431fe0ee`–`07848de3`, `3aa71bdf`), numbered options with recommendations, and the round-1 contradiction in the user's answers ("recurring events" vs "fine for Q4") caught and cleanly re-asked (`a395c959`). Zero redirects from the user across all 15 turns.
- **Orchestrator care before parallel builds**: asked the user before branching a dirty tree (`957e27e6`), wrote builder briefs with explicit per-file ownership, binding decisions, gates, and smoke instructions (`f0cc321c`, `2a568a7c`, `0210539e`), and refused to touch gate policy, escalating instead (`e42953b9`).
- **Merge validation that earned its keep**: post-merge runs surfaced two broken cal-5 tests, and a latent pre-existing seed crash (`NoReferencedTableError`) fixed properly with `db/registry.py` (`e7659faf`); cal-8's smoke caught a real household-wide-create 500 (`d1f6f3ef`).
- **Incident recovery**: damage assessed against the append-only Rohrpost log, `[cal-4]` restored verbatim from authored text, and nine post-fix verification checks adopted for every subsequent tracker write (`ecb59b1e`, `0f532f55`).

## Friction

- **`rp set` fired with an empty temp file and wiped [cal-4]'s body** (`fac56d3e` bash → `2229cd70` → `ecb59b1e` → `0f532f55`): a python prep heredoc died on an assert mid-script; the compound command continued anyway; `body="$(cat /tmp/cal-4-new.md)"` expanded to empty and replaced the whole body. The map was simultaneously set to `/tmp/cal-map-new.md` — a *stale file from the previous session with the same name* (accidentally a no-op). Root cause chain: prepare and mutate inlined in one shell call with no error gating → `cat` of a missing file yields `""` and `body=` accepts it → predictable `/tmp` names reused across sessions → no verification between prepare and mutate. Recovery only worked because the agent still held the authored text in context.
- **Broken deptry ratchet discovered via builder reports, not a baseline** (`de0e899c`, `fe0fe5e4`, `e42953b9`): `deptry` runs with no `known_first_party`, so in this src-layout repo every internal `nidaro.*` import counts as DEP001 and `aufsicht full` can never pass a branch that adds imports — the base itself was already failing. cal-6 correctly stopped and reported mid-flight per AGENTS.md; the orchestrator spent extra rounds diagnosing and escalating what a pre-spawn `aufsicht full` on the base commit would have shown immediately. (The user later fixed the config themselves in `096fcc7`.)
- **Both parallel builders were told to add identical model columns; the merge stacked them** (`f0cc321c` briefs, `fe0fe5e4` finding 2, `2540a85e`, `a6b7a63f`): the deliberate "duplicate so each branch is green, merge dedupes" strategy produced doubled columns in `calendar/models.py` that only a line-count check caught — no merge step was designed to look for exactly this.
- **Worktrees branched from a HEAD that didn't match the working tree** (`957e27e6`, `ebbc3e59`, `d902c794`, `c389e563`, `2a568a7c`): after the user chose "commit your own changes only", cal-5/cal-6 worktrees lacked the dirty `app.py`/meals edits and untracked `scripts/` + `test_ui.py` (hand-copied into worktrees as "an uncommitted helper"). Gates were green partly "because untracked files still exist on disk" — a baseline that no fresh checkout could reproduce. Resolved only when the user committed the rest before cal-7.
- **Builder smoke tests wrote into the shared dev database** (`2a568a7c` cal-7 brief allowed migrate+seed on the DEV DB; `0210539e` cal-8 brief directed real POSTs at it; `d1f6f3ef` cleanup): the orchestrator afterwards deleted the builder's smoke rows from the user's dev database. Root cause: no scratch-database affordance — worktrees inherit the dev `NIDARO_DATABASE_URL`, and nothing in the repo marks the dev DB off-limits to smoke traffic.
- **En-dash strings vs RUF001, amplified by edit atomicity** (`f8d035d5`, `5eca6df1`, `b96271de`, `09d38f33`): typographic en-dashes written into Python UI strings tripped RUF001; the three-part fix then rolled back atomically because `ruff format` had reflowed one edit anchor, costing a re-read and individual re-applies before gates went green. Root cause: gate rules not checked before authoring display strings, plus editing from pre-format text.
- **Minor, one-off**: a repo-wide grounding `rg` with an over-generic pattern returned 41 KB (`431fe0ee`); gate output parsed as JSON failed three times on non-JSON preamble through `rtk` (`024d8b1a`, `d9e67098`, `eb2152a3`); two failed smoke-server starts before settling on the background terminal (`871b346f`, `5785f5db`).

## Proposals

| # | Type | Change | Where | Evidence | Status |
|---|------|--------|-------|----------|--------|
| 1 | skill-update | Destructive-write guardrail for `body=` in the Rohrpost skill | `.agents/skills/rohrpost/SKILL.md` § "Updating fields" | `fac56d3e`, `2229cd70`, `ecb59b1e`, `0f532f55` | done — applied |
| 2 | skill-update | "Parallel builds in git worktrees" checklist in the subagents skill | `~/.pi/agent/skills/subagents/SKILL.md`, new section after "Spawn and Manage" | `957e27e6`, `de0e899c`, `fe0fe5e4`, `2540a85e`, `e7659faf`, `c389e563` | deferred — short pointer applied globally (workflows as orchestrator + core invariants); full playbook ticketed as NIDAR-fhhz1p |
| 3 | tool-create | `scripts/smoke-db.sh` — scratch-DB smoke server, plus a one-line pointer | `scripts/smoke-db.sh` (new); `AGENTS.md` § Project rules (protected path — needs user to apply) | `2a568a7c`, `0210539e`, `d1f6f3ef` | deferred — ticketed as NIDAR-m3cdt7 (script + protected AGENTS.md line together) |
| 4 | skill-update | Make prototype capture an explicit pre-deletion step with commands | `.agents/skills/prototype/SKILL.md` rule 6 | `eeb05554`, `2a568a7c` | done — applied |
| 5 | skill-update | One-line sharpening: destination-deferred work is out of scope, never fog | `.agents/skills/wayfinder/SKILL.md` § Fog of war | `71c88ae4`, `f439b0d9` | rejected |
| 6 | acknowledge | En-dash/RUF001 + post-format edit-anchor churn — harness/tool interaction, self-corrected; no repo artifact would reliably have prevented it | — | `f8d035d5`, `5eca6df1`, `b96271de` | done — acknowledged, no artifact |
| 7 | acknowledge | Gate output parsed as JSON failed 3× on `rtk`/preamble noise; one-off grounding `rg` returned 41 KB | — | `024d8b1a`, `d9e67098`, `eb2152a3`, `431fe0ee` | done — acknowledged, no artifact |

### Proposal details

**1. Rohrpost skill — `body=` guardrail** (`skill-update`). Systemic: every wayfinder session rewrites map/ticket bodies; this is the exact pattern that wiped `[cal-4]`. Append to the end of "## Updating fields", after the `body=` replaces-the-whole-body sentence:

```markdown
`body=` is destructive and accepts the empty string silently: a prep step that
dies before writing the temp file turns `body="$(cat /tmp/next.md)"` into a
wipe. Never prepare and set in one compound command — a failed prep does not
stop the shell from running the mutation. The safe sequence:

1. Write the new body to a fresh `mktemp` file, never a reusable name —
   `/tmp/<ticket>-new.md` from a previous session is still there and will be
   served up by `cat`.
2. Check the file before using it: non-empty, and it contains an anchor you
   know belongs in the new body (`grep -q`).
3. Run `rp set <id> body="$(cat <file>)" --json` as its own command, only after
   the prep exited zero (gate with `&&`, or split calls).
4. `rp show <id> --json` afterwards and verify length + anchor took.
```

**2. Subagents skill — parallel worktree builds** (`skill-update`). The session invented the whole orchestration protocol per brief; nothing anywhere carries it. The next "run these in parallel with subagents" re-rolls the dice. Insert a new section after "## Spawn and Manage" in `~/.pi/agent/skills/subagents/SKILL.md`:

```markdown
## Parallel builds in git worktrees

Before spawning builders that each work in their own worktree:

1. **Branch from a committed baseline.** Commit or stash everything first —
   uncommitted files do not exist in a worktree, and untracked helpers
   hand-copied into worktrees make gates green for the wrong reason. Verify a
   fresh worktree passes the unit suite before a builder starts.
2. **Run the full gate suite on the base commit before spawning.** Failures at
   base are pre-existing: escalate to the human and write the verdict into
   every builder brief ("only X is an acceptable failure"), so no builder
   stops mid-flight on a gate that was already broken.
3. **Partition files; never assign the same edit to two builders.** If two
   branches genuinely need identical lines in one shared file so each stays
   green, say so in both briefs and treat stacked duplicates as an expected
   merge artifact — diff the merge result for doubled lines before verifying.
4. **Fix the merge on main, in merge order.** After each merge: unit suite,
   then the full gate suite, then end-to-end smoke. Cross-branch breakage
   (a constructor change under a parallel branch's tests) surfaces here; fix
   forward on main, never inside an already-merged branch.
```

**3. Scratch-DB smoke server** (`tool-create`). The repo's ethos is deterministic tooling for mechanical workflows; a script enforces the convention where a doc line would have to be re-derived by every builder brief. `NIDARO_DATABASE_URL` is already the settings override and alembic/seed read it, so this is cheap and complete. New `scripts/smoke-db.sh`:

```bash
#!/usr/bin/env bash
# Boot a throwaway smoke server on a scratch database — never the dev DB.
# Usage: scripts/smoke-db.sh [PORT]  (default 8123). Ctrl-C stops it; the
# scratch database is dropped on exit.
set -euo pipefail

PORT="${1:-8123}"
SCRATCH="nidaro_smoke_$$"

podman exec nidaro-postgres-1 psql -U nidaro -d postgres \
  -c "DROP DATABASE IF EXISTS $SCRATCH" -c "CREATE DATABASE $SCRATCH" >/dev/null
cleanup() {
  podman exec nidaro-postgres-1 psql -U nidaro -d postgres \
    -c "DROP DATABASE IF EXISTS $SCRATCH" >/dev/null || true
}
trap cleanup EXIT

export NIDARO_DATABASE_URL="postgresql+psycopg://nidaro:nidaro@localhost:5432/$SCRATCH"
uv run alembic upgrade head
uv run nidaro-seed
echo "Smoke server: http://127.0.0.1:$PORT (scratch DB $SCRATCH)"
exec uv run uvicorn nidaro.app:create_app --factory --port "$PORT"
```

Plus one pointer line in `AGENTS.md` § "Project rules" (aufsicht-protected file — apply by user hand or explicit approval): `- Smoke-test servers run on a scratch database via scripts/smoke-db.sh, never the dev database.`

**4. Prototype capture as a hard step** (`skill-update`). The skill already says capture-to-throwaway-branch, but the session folded cal-7's deletion into a build brief with "the throwaway capture is git history" — unlabeled main history, no branch. The pointer didn't fail; it just wasn't actionable enough at the moment of deletion. In `.agents/skills/prototype/SKILL.md`, extend rule 6 with:

```markdown
   Run the capture **before anything deletes the prototype from main** — a
   build ticket folding the winner in counts as deletion: `git checkout -b
   throwaway/<name>` from a commit holding the full prototype, then switch
   back. Verify with `git branch --list 'throwaway/*'` and link the branch
   from the ticket; unlabeled main history is not a capture.
```

**5. Wayfinder — deferred-vs-fog** (`skill-update`). At charting, work the confirmed destination itself named as "later" (edit/delete, richer recurrence) was filed as fog; the cal-2 session re-filed it as out of scope. One sentence after the "Fog or ticket?" bullets in § Fog of war:

```markdown
Work the confirmed destination itself defers to "later" sits in **Out of
scope** from the moment the destination is confirmed, never in **Not yet
specified**: the destination text already places it past the end of the route.
```

## Questions for the user

- Upstream guard: `rp set body=` accepting an empty replacement silently is what made the wipe possible. File an issue upstream (refuse empty `body=`, and/or a `--body-file` flag that verifies non-empty)? This repo can't fix it locally — the installed `rp` lives outside it.
- Proposal 3 touches `AGENTS.md`, an aufsicht-protected path; and Proposal 2 edits the *global* subagents skill (affects every repo, not just nidaro). Confirm both scopes, or tell me to demote them to repo-local homes (`docs/agents/`).

## Resolutions

- Proposal 1 upstream guard: user chose the repo-local skill edit only; no upstream issue drafted.
- Proposal 2 scope: user directed workflows as the default orchestrator; short pointer applied to the global
  subagents skill, full playbook deferred to NIDAR-fhhz1p (possible future worktrunk-based skill).
- Proposal 3 scope: deferred wholesale (script + protected AGENTS.md line) to NIDAR-m3cdt7.
- Proposal 5: rejected by the user.
