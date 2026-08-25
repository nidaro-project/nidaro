# AGENTS.md

## Project rules

- Use Python 3.14 and `uv`.
- Use `podman compose` for local infrastructure. `docker compose` is also compatible.
- Keep PostgreSQL as the authoritative family state. Redis is only a task broker.
- Keep the boundary `route/tool/worker -> service -> repository -> database`.
- Do not add secrets to source control.
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
