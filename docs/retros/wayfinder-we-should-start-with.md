# Retro: Meal planner via wayfinder — chart, prototype, build, orchestrate

**Date**: 2026-08-30
**Session**: 01a04f8b-f41d-7c73-aa52-640a0b73d980
**Transcript**: /home/vfeenstr/.pi/agent/sessions/--home-vfeenstr-devel-lab-agenterio-nidaro--/2026-08-29T22-02-47-197Z_01a04f8b-f41d-7c73-aa52-640a0b73d980.jsonl
**Duration / tokens / cost**: 40,469 s (~11 h 14 m, of which ~7 h was user idle between turns) / input 868,369, output 114,716, cacheRead 26,118,144, reasoning 50,164, total 27,101,229 / $0.00 (zai/glm-5.3-flash)
**Extraction**: /home/vfeenstr/devel/lab/agenterio/nidaro/docs/retros/wayfinder-we-should-start-with.extract.json

## What happened

One session carried the whole meal-planner effort: `/wayfinder` charting (16 min, two grilling rounds, CONTEXT.md, epic + 6 tickets), then three `/wayfinder mealplan` executions — two prototype tickets (week view, dish config) resolved by user verdicts, the meals domain built TDD-style, and finally the two page builds orchestrated across parallel subagents in git worktrees, merged to main green. All six tickets closed and the map completed. The session produced the meals domain (Dish, PlannedMeal, copy-on-plan, migration, repository, protocol-typed seam), `/meals` week view, `/meals/dishes` config page, seed data, an e2e meals pass, and `known_first_party` deptry config fixing 155 pre-existing false positives. Two user corrections landed mid-flight: "commit your work more regularly" (ceded662) and "orchestrate the tickets in its own worktree, merge to main when done" (a422731b) — both were work-location/cadence rules the repo never stated.

## What worked

- **Grilling with recommended answers**: rounds of numbered questions each carrying a recommendation (bae64629, 7481e5ff, cce92f48) settled 12 decisions in ~12 minutes with near-zero back-and-forth; the frontier moved exactly as the grilling skill prescribes.
- **Decision propagation into build tickets**: every prototype verdict was written into the map's Decisions-so-far *and* the dependent build ticket's body before the build (c95740f3, 54ab05d6, 08773bd0). The parallel subagent briefs (418c9561) then carried the settled design as fact — neither builder re-litigated anything.
- **Worktree-per-ticket orchestration**: spawn in isolated worktrees, strict file ownership in the brief, sequential merges with conflict resolution, main verified green after each merge (a62ee179, acf87024, 380f33e4, 0d0fa723) — the pattern the user asked for (a422731b) executed cleanly per the calendar-map precedent.
- **Live verification catching real bugs**: the Postgres copy-on-plan proof caught missing primary-key defaults (db501f08); the pre-existing `ensure_household` DetachedInstanceError was bypassed without scope-creep and filed as its own ticket (efcbd19d, 45feb6af).

## Friction

- **Commit cadence needed a user correction** (ceded662, 32509a41): the agent built the entire meals domain — and left the freshly written CONTEXT.md — with zero commits, and only committed after the user intervened 21 minutes into the build turn. Root cause chain: no repo rule states commit cadence → agent defaulted to "commit at completion" → user preference surfaced as a mid-build correction → agent wrote it into the mealplan map's Notes (e302afdd), which die with the map, so the next effort inherits nothing.
- **The Meals glossary was silently destroyed** (809b8348, 3c2e7d12, a5f293f; git `aa09839`): the agent's CONTEXT.md with *Dish / Planned meal / Slot* sat uncommitted from 22:19; the user's concurrent `chore: Docs` commit (08:43) landed a calendar-only CONTEXT.md as a new file. The distilled ubiquitous language now exists nowhere on main. Root cause: shared-checkout concurrency + no commit cadence (previous bullet) + the agent concluding at 3c2e7d12 that "CONTEXT.md is gone from untracked" meant it was handled, and its commit a5f293f therefore omitted it.
- **Agent worked in the user's checkout while the user worked there** (ccfed36b, bec5ad6d, 3c2e7d12, 1734ee4f, f9d85a8a): mealplan-3 ran in the main checkout alongside the user's in-flight uncommitted UI work, forcing git-plumbing branch capture that avoids shared files, a "the branch moved under me" investigation, and a post-hoc check of whether a concurrent user commit swept the prototype files onto main. Root cause: neither the wayfinder skill nor the map said *where* execution happens; the user had to state the worktree rule explicitly afterwards (a422731b).
- **~15 calls and ~20 gate runs spent inventing typed-fake typing** (c557e45b, 8112b5f9, 6ebb5c4d, 73d681cb, 9f3101ca, 72b79361, 5004288d, 54f8093d, e7c631a6, 4aa246e6): the fake failed pyright (`reportArgumentType`), the agent asked "how do the house tests pass this?" (they subclass the real repository, tests/unit/test_services.py) but judged that "ugly", invented a Protocol seam, then hit three pitfalls serially — all-members rule, `dishes` dict attribute colliding with a `dishes()` protocol method, leftover old-name reference. Root cause: tdd/mocking.md has no typed-fake guidance; the house pattern is only discoverable by reading existing tests; the Protocol pattern is new and unrecorded. The gate was the only type-checker in the loop, so every micro-fix cost a full `aufsicht fast` (20 bash gate calls 06:30–06:59).
- **Dev-server lifecycle ad-hoc'd per prototype** (646132db, c0a00dac, 4d414ce0, b1f9df0b, 28740f10, 9f56476b, 14e2a65d, c2024af3, 78e11074, 4ce4a49e, d5a529cc, 19cd51e8, 46595028, b6ee99ab): curl `000` from `localhost` resolving to ::1 (exit 7), a server started without `--reload` serving stale code/state (three calls to diagnose), fixed-sleep startup races failing screenshots twice, and repeated kill/start/wait/re-shoot cycles in both prototype tickets — roughly 15–19 calls total on server lifecycle. Leftover server + headless Chrome were carried across two handovers (ba835339, ddc8015b) until final cleanup (dd9e6b17). Root cause: prototype/UI.md's "trivial to run" addresses the human, not the agent-driven smoke loop; the readiness/IPv4/reload recipe had to be derived twice.
- **Gate as inner loop, and pre-existing findings blocking changed files** (ec896226, 632a30e6, fcb6bc02): the agent's standalone `uvx pyright` produced venv-resolution noise, so `aufsicht fast` became the only trusted type-check and was re-run after every micro-edit; and because the ruff gate is diff-scoped, container.py's pre-existing F821 — acknowledged at fcb6bc02 as "baseline, not mine" — blocked anyway once the file was touched, and the agent fixed it. AGENTS.md's rule ("fix what you added; do not offset with an unrelated fix") does not cover a pre-existing finding inside a file the change legitimately touches. Root cause: no cheap changed-files precheck affordance; ambiguity in the gate policy for pre-existing findings in touched files.

## Proposals

| # | Type | Change | Where | Evidence | Status |
|---|------|--------|-------|----------|--------|
| 1 | skill-update | Add "Typed fakes must type-check" recipe to mocking guidance | .agents/skills/tdd/mocking.md (new section at end) | c557e45b–4aa246e6 | done |
| 2 | skill-update | Carve out seam confirmation when a ticket already fixes the seam | .agents/skills/tdd/SKILL.md: "Seams" section | c988e463, map Notes | done |
| 3 | skill-update | Execution hygiene: worktree isolation + commit-per-increment in "Work through the map"; charting records them in Notes | .agents/skills/wayfinder/SKILL.md: "Work through the map" step 3 | ceded662, a422731b, ccfed36b, 1734ee4f | done |
| 4 | skill-update | New step "Run it and judge it yourself": IPv4 bind, reload, readiness block, screenshot judging, teardown at handover | .agents/skills/prototype/UI.md: new step between 4 and 5 (renumber 5–6 → 6–7) | 646132db, c0a00dac, 28740f10, 9f56476b, 46595028, dd9e6b17 | done |
| 5 | doc-update | Restore the lost Meals glossary (*Dish / Planned meal / Slot*) to CONTEXT.md | CONTEXT.md: "## Language" | 809b8348, aa09839, a5f293f | done |
| 6 | tool-create | `scripts/quality-changed.sh`: pinned ruff + pyright on changed files as a cheap pre-gate loop | scripts/quality-changed.sh (new) | 20 gate calls 06:30–06:59, ec896226 | deferred — ticket NIDAR-ntewtw |
| 7 | investigate | Gate policy for pre-existing findings in files the change touches (fix vs. baseline vs. ignore) | AGENTS.md aufsicht block (protected) | 632a30e6, fcb6bc02 | rejected — user: "I asked them to fix it. Ignore this for now." (the container.py fix was user-directed; no policy gap to close) |

### 1. tdd/mocking.md — append section

```markdown
## Typed fakes must type-check

Where the gate type-checks changed test files, a fake must satisfy the
service's annotation. Two working shapes; pick by one rule — can the real
repository be constructed without a database?

- **Subclass the real repository** when constructing it needs no live session:
  `class FakeEventRepository(CalendarRepository)` (see
  tests/unit/test_services.py). The fake is a subtype, so a service annotated
  against the concrete class accepts it.
- **Protocol at the seam** when the real repository needs a session to build:
  the service annotates its dependency with a structural `Protocol`
  (`MealsRepositoryProtocol` in src/nidaro/meals/service.py); the real class
  satisfies it implicitly and the fake stays standalone.

Protocol pitfalls — each missed one costs a full gate cycle:

- The fake must define **every** protocol member, including methods the
  current tests never call; protocol matching is all-members.
- Never give a fake an attribute that shares a name with a protocol method: a
  dict named `dishes` collides with a `dishes()` method and reports as a
  member mismatch, not a naming accident.
- After renaming inside the fake, grep for leftover references to the old
  name before re-running the gate.
```

### 2. tdd/SKILL.md — "Seams" section, after "Ask: 'What's the public interface, and which seams should we test?'"

Before:

```markdown
When the shape of that interface is itself in question ...
```

Insert before that paragraph:

```markdown
When the seam is already fixed upstream — an approved ticket, spec, or map
decision states the interface — the seam counts as agreed: write it down,
build to it, and record it in the resolution instead of re-opening the
question with the user.
```

### 3. wayfinder/SKILL.md — "Work through the map", extend step 3

Before:

```markdown
3. Resolve it. **Zoom as needed**: fetch the full body of any related or closed ticket on demand; call the Skill tool for whichever skills the `## Notes` block names. If in doubt, call the Skill tool twice, for "grilling" and "domain-modeling".
```

After:

```markdown
3. Resolve it. **Zoom as needed**: fetch the full body of any related or closed ticket on demand; call the Skill tool for whichever skills the `## Notes` block names. If in doubt, call the Skill tool twice, for "grilling" and "domain-modeling". While resolving a ticket that builds something, **commit each increment as it turns green** — never hold a session's whole output for one end-of-ticket commit — and build in a **worktree or branch of your own**, never in a checkout the human is working in; merge to the main line once it is green. Charting sessions record these execution preferences in the map's **Notes** so every later session and subagent brief inherits them.
```

### 4. prototype/UI.md — insert new step before "### 5. Hand it over"; renumber the last two steps to 6 and 7

```markdown
### 5. Run it and judge it yourself

Before handing over, drive every variant end to end yourself — the user should confirm a working page, not debug one.

- Start the dev server on an explicit IPv4 host (`127.0.0.1`, not `localhost`: on dual-stack machines `localhost` can resolve to `::1` and curl reports `000` against a server that is up).
- If you will keep editing, start with auto-reload — or plan to kill and restart after each edit. A server started without reload serves stale code and stale in-memory state; debugging that costs more than the restart.
- Block on readiness inside one bash call (`until curl -fsS http://127.0.0.1:PORT/<route> >/dev/null; do sleep 1; done`) instead of a fixed sleep. A screenshot or POST fired before the server answers is a wasted round trip.
- Smoke the flows with curl (form POSTs, fragment swaps), and judge rendering from screenshots via the chrome-agent CLI rather than trusting status codes.
- Hand over with the server running only if the user should poke at it; otherwise stop the server and the headless browser before you finish.
```

### 5. CONTEXT.md — append to "## Language" (restore from session entry 809b8348; matches the file's flat bold-term style)

```markdown
**Dish**:
A reusable meal idea the household eats typically, configured once with a name, notes, and tags. A Dish is not tied to any date.
_Avoid_: recipe, meal idea, template

**Planned meal**:
A Dish (or a one-off name) placed on a specific date and slot. A planned meal keeps the dish's name at planning time and is unaffected by later edits to or deletion of the Dish.
_Avoid_: meal entry, calendar event

**Slot**:
One of the fixed eating times a day is planned in: breakfast, lunch, dinner, snacks. A slot may hold more than one planned meal.
_Avoid_: mealtime, category
```

### 6. scripts/quality-changed.sh (new; deterministic inner loop so `aufsicht fast` is a checkpoint, not a type-checker)

```bash
#!/usr/bin/env bash
# Pre-gate check: pinned analyzers on changed Python only.
# Cheap loop between micro-edits; `aufsicht fast`/`full` remain the gates of record.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
PIN_RUFF=$(awk -F'"' '/^ruff =/{print $2}' .quality/toolchain.lock)
PIN_PYRIGHT=$(awk -F'"' '/^pyright =/{print $2}' .quality/toolchain.lock)
mapfile -t FILES < <({ git diff --name-only HEAD -- '*.py'; git ls-files -o --exclude-standard -- '*.py'; } | sort -u)
[ ${#FILES[@]} -eq 0 ] && { echo "no changed python files"; exit 0; }
# shellcheck disable=SC2086
uvx "ruff@${PIN_RUFF}" format --check --config .quality/ruff.toml "${FILES[@]}"
uvx "ruff@${PIN_RUFF}" check --config .quality/ruff.toml "${FILES[@]}"
uvx "pyright@${PIN_PYRIGHT}" --pythonpath "$(pwd)/.venv/bin/python" "${FILES[@]}"
echo "precheck clean: ${FILES[*]}"
```

Validate on first run: the `--pythonpath` pointing at `.venv` must silence the import-resolution noise the session saw from bare `uvx pyright` (ec896226); if the repo's venv lives elsewhere, adjust the path once.

### 7. investigate — pre-existing findings in touched files

`AGENTS.md`'s ratchet rule says fix what you added and never offset with unrelated fixes, but says nothing about a pre-existing finding inside a file the change legitimately touches (the F821 in container.py at 632a30e6: acknowledged as "not mine" at fcb6bc02, then blocking, then fixed anyway). Options: allow trivial pre-existing fixes in touched files, add a baseline mechanism, or leave as-is. The config is protected, so this needs the user's call, not an agent edit.

## Questions for the user

- **Commit cadence in AGENTS.md**: the durable home for "commit your work more regularly" is a Project rules line in AGENTS.md, but AGENTS.md is aufsicht-protected — the applying session cannot edit it. Add the line yourself, or let the wayfinder skill edit (proposal 3) carry it alone?
- **ADR for "meals are their own domain, never calendar Events"**: the offer at c18dd1ac went unanswered when the next `/wayfinder mealplan` arrived, and `docs/adr/` does not exist. The decision currently lives only in the completed map's Decisions-so-far. Write the ADR now, or leave it?
- Proposal 7's policy choice above (fix / baseline / ignore pre-existing findings in touched files).
