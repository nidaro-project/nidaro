# AGENTS.md

## Project rules

- Use Python 3.14 and `uv`.
- Use `podman compose` for local infrastructure. `docker compose` is also compatible.
- Keep PostgreSQL as the authoritative family state. Redis is only a task broker.
- Keep the boundary `route/tool/worker -> service -> repository -> database`.
- Do not add secrets to source control.
- Run `uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright`, and `uv run pytest` before a change is complete.
