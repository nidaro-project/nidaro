# Architecture

Nidaro is a modular monolith for the first vertical slice.

```text
FastAPI route / assistant tool / Taskiq job / connector
                         |
                      service
                         |
                    repository
                         |
                    PostgreSQL
```

PostgreSQL owns household state, facts, conversations, and job history. Redis only transports Taskiq jobs. Connectors return external records and do not mutate domain tables. The assistant is created by one factory and can use only typed application tools.

The UI is server-rendered Jinja2 templates with vendored HTMX, styled entirely from the design tokens in [DESIGN.md](../DESIGN.md). UI routes live under `src/nidaro/web/routes/ui.py` and render the shell; they call no repositories directly.

There is no authentication, tenancy, vector database, or external connector in this slice.
