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

The API is available at `http://localhost:8000`. `/health` is process-only. `/ready` checks PostgreSQL and Redis. Set `NIDARO_MODEL` and the provider API key before using `/api/v1/assistant/chat`.

Run the worker and scheduler in separate terminals:

```bash
uv run taskiq worker nidaro.jobs.broker:broker --fs-discover
uv run taskiq scheduler nidaro.jobs.scheduler:scheduler --skip-first-run
```

Use `podman compose down` to stop the local services. Integration tests require the same PostgreSQL and Redis services and are marked with `integration`.

## Layout

Application code is under `src/nidaro`. Alembic migrations are under `migrations`. Domain code uses services and repositories so API and assistant code do not issue SQL directly.
