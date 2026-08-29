# AGENTS.md

## Project rules

- Use Python 3.14 and `uv`.
- Use `podman compose` for local infrastructure. `docker compose` is also compatible.
- Keep PostgreSQL as the authoritative family state. Redis is only a task broker.
- Keep the boundary `route/tool/worker -> service -> repository -> database`.
- Do not add secrets to source control.
- Prefix shell commands with `rtk` (see `RTK.md`). It is a token-optimizing proxy; `rtk proxy <cmd>` runs the raw command when you need unfiltered output.
- When a request hinges on a runtime property ("runs in the background", "survives closing the session", "only the user can trigger it"), verify the chosen mechanism has that property before building. If two mechanisms plausibly fit, confirm the split with the user first.
- Use `aufsicht fast` during implementation and `aufsicht full` before a change is complete.

## Nidaro architecture

- PostgreSQL is the source of truth for family state.
- Agent memory is not family memory.
- Agent tools call application services.
- Application services call repositories.
- Domain services must not depend on FastAPI, Taskiq, or Pydantic Deep.
- Scheduled jobs call the same application services as HTTP and assistant code.
- Connectors produce external records and do not directly mutate unrelated domains.
- All I/O is async unless a dependency requires otherwise.
- Do not add microservices.
- Do not add infrastructure dependencies without a concrete requirement.
- Prefer deterministic code for parsing, scheduling, calculations, and state changes.
- Use LLMs for semantic interpretation and reasoning.

<!-- aufsicht:begin (do not edit outside these delimiters; appended by `aufsicht init`) -->

## Quality guardrails (aufsicht)

Deterministic gates defined by the Python AI Code Quality Guardrails
spec (v5.1). `quality-fast` and `quality-full` come from the pinned
`aufsicht` runner recorded in `.quality/toolchain.lock`.

### Agent workflow

1. Read repository conventions.
2. Understand the change. Inspect existing patterns before writing new ones.
3. Implement the smallest complete solution.
4. Format and lint changed Python only with the pinned analyzers: versions
   live in `.quality/toolchain.lock`, ruff config in `.quality/ruff.toml`
   (line-length 100). Command shape:
   `uvx ruff@<pin from toolchain.lock> format --config .quality/ruff.toml <paths>`.
   This includes scripts under `.pi/extensions/`. Ambient installs disagree
   with the pin and the config.
5. Run quality-fast. Fix failures. Repeat until clean.
6. Run quality-full.
7. If a ratchet failed, find and fix what you added. Do not offset it with an
   unrelated fix.
8. Stop. Report status. Do not self-approve.

Never, under any circumstances:

* disable, skip, or xfail a test to make a task complete
* add a suppression comment
* edit anything under the protected paths (`.quality/**`,
  `pyrightconfig.json`, `.pyscn.toml`, `.pre-commit-config.yaml`,
  `.github/workflows/**`, `AGENTS.md`)
* regenerate the baseline
* add or edit an allowlist entry
* weaken a threshold, coverage target, or lint rule
* leave the previous implementation in place after replacing it
* create a parallel implementation where an existing one should be extended
* modify files unrelated to the task

If a gate appears wrong, **stop and report it**. Do not work around it. A task
that requires weakening its own evaluator is a task that needs a human.

### Escape valve

The only sanctioned exception mechanism is `.quality/allowlist.toml`
(v5.1 §10): every entry carries a reason and an expiry. There are no
inline suppression comments and no per-tool ignore files.

<!-- aufsicht:end -->

## Agent skills

### Issue tracker

Issues live in the repository's Rohrpost log. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the standard labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, and `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Use a single-context layout. See `docs/agents/domain.md`.

@RTK.md
