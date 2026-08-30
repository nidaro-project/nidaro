# Nidaro

Nidaro is an open-source family operating assistant. This repository contains the first vertical slice: PostgreSQL-backed family state, a service layer, typed assistant tools, conversation persistence, Taskiq jobs, and a minimal FastAPI API.

Licensed under [AGPL-3.0-only](LICENSE).

## Local development

Install Python 3.14 and [uv](https://docs.astral.sh/uv/). Start PostgreSQL and Redis with Podman:

```bash
podman compose up -d
uv sync
uv run alembic upgrade head
uv run nidaro-seed
uv run uvicorn nidaro.app:create_app --factory --reload
```

Install Aufsicht as an isolated developer tool. It is not part of Nidaro's Python environment:

```bash
uv tool install aufsicht==0.2.2
```

Use `aufsicht fast` during development and `aufsicht full` before completing a change.

The server exposes the UI shell at `/`, the API under `/api/v1`, and the process checks `/health` and `/ready`. Set `NIDARO_MODEL` and the provider API key before using `/api/v1/assistant/chat`.

The UI shell is served at `/` — a dashboard, placeholder sections, and a settings page with theme switching. Visual conventions and design tokens live in [DESIGN.md](DESIGN.md); a browser smoke test runs via `scripts/e2e_ui_shell.sh` (needs `uv tool install chrome-agent` and a running server).

Run the worker and scheduler in separate terminals:

```bash
uv run taskiq worker nidaro.jobs.broker:broker nidaro.jobs.tasks
uv run taskiq scheduler nidaro.jobs.scheduler:scheduler nidaro.jobs.tasks --skip-first-run
```

Use `podman compose down` to stop the local services. Integration tests require the same PostgreSQL and Redis services and are marked with `integration`.

## Production

Nidaro can run as a fully containerized service in its own Podman pod, next to the development setup. See [docs/deployment.md](docs/deployment.md).

## Layout

Application code is under `src/nidaro`. Alembic migrations are under `migrations`. Domain code uses services and repositories so API and assistant code do not issue SQL directly.
