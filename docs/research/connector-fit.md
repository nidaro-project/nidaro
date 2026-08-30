# Connector-fit: how a school gatherer would ride Nidaro's connector infrastructure

Research for [school-3] (NIDAR-1q5xx4), feeding the shortlist fit statement on the
wayfinding map epic. Facts only, no design. Every claim cites a file, module, or
Rohrpost ticket id. Researched 2026-08 against the repo at `4bb0f39`.

## 1. The connector lifecycle as intended

- The contract is the `Connector` protocol in `src/nidaro/connectors/base.py`:
  a `name` plus one method, `async sync(context: ConnectorContext, cursor: str | None) -> SyncResult`.
  Connectors are pull-based and cursor-driven; there is no push/webhook concept in the contract.
- `ConnectorContext` carries `household_id` and `timezone`
  (`src/nidaro/connectors/models.py`) — sync is always scoped to one household.
- A run returns a `SyncResult`: a list of `ExternalRecord` plus an optional
  `next_cursor` for the next run (`src/nidaro/connectors/models.py`).
- `ExternalRecord` is the landing shape for external data (school announcements,
  events, grades, messages): `connector`, `external_type`, `external_id`,
  `payload` (free-form dict), `content_hash`, `observed_at`
  (`src/nidaro/connectors/models.py`). No tombstone field exists.
- `ConnectorRegistry` (`src/nidaro/connectors/registry.py`) is an in-memory
  name→connector map (`register`/`get`/`names`); unknown names raise `KeyError`.
- `ConnectorService.sync` (`src/nidaro/connectors/service.py`) is a thin
  dispatcher: registry lookup, call `sync`. It persists nothing.
- Wiring: `ApplicationServices.build` constructs
  `connectors=ConnectorService(ConnectorRegistry())` — the registry is empty; no
  connector implementation exists anywhere in `src/nidaro/`
  (`src/nidaro/container.py`).
- Triggering: `src/nidaro/jobs/tasks.py` defines `connector_sync(connector_name)`
  as a placeholder returning `{"status": "not_implemented"}`. The Taskiq
  machinery around it is real: `ListQueueBroker` over Redis
  (`src/nidaro/jobs/broker.py`) and a `TaskiqScheduler` with `LabelScheduleSource`
  (`src/nidaro/jobs/scheduler.py`); the `heartbeat` task proves cron-labeled
  scheduling works (`*/5 * * * *`, `src/nidaro/jobs/tasks.py`).
- `docs/architecture.md` scopes the current slice explicitly: "There is no
  authentication, tenancy, vector database, or external connector in this slice."
  The connector seam is scaffolding, not a populated plugin system.

## 2. Where school data would land

- Intended landing: `ExternalRecord`s produced by a connector's `sync`, applied
  to domain tables by an application service — never by the connector itself.
  That division is stated in `docs/architecture.md` ("Connectors return external
  records and do not mutate domain tables"), `AGENTS.md` ("Connectors produce
  external records and do not directly mutate unrelated domains"), and worked
  out concretely in `docs/research/google-calendar-integration.md` §7 (connector
  emits `ExternalRecord`s → `CalendarService.apply_external_records(...)` upserts
  domain rows → cursor persisted after the run).
- But `ExternalRecord` has **no persistence today**: it exists only as a Pydantic
  model. The SQLAlchemy model registry imports no connector models
  (`src/nidaro/db/registry.py`), and the Alembic migrations create only
  `households`, `family_members`, `events`, `event_participants`, `sources`,
  `facts`, `tasks`, `commitments`, `conversations`, `job_runs`, `dishes`,
  `planned_meals` (`migrations/versions/0001_initial.py`, `0002_meals.py`,
  `0003_calendar_activity_fields.py`). No `external_records` table, no
  `connector_cursors` table, no credential table.
- The closest existing landing surface is the `sources` table
  (`src/nidaro/sources/models.py`: `household_id` FK, `type`, `external_id`,
  `title`, `content`, `metadata` JSONB) with `SourceRepository.create` and
  `SourceService.record` (`src/nidaro/sources/repository.py`,
  `src/nidaro/sources/service.py`). Provenance is already wired into a domain:
  `Event.source_id` is a nullable FK to `sources`
  (`src/nidaro/calendar/models.py`). Whether school data routes through
  `sources` or a new external-record table is an open seam, not a settled one.

## 3. Exists vs. missing for a read-only school source

Exists today:

- The connector contract and envelope types (`src/nidaro/connectors/base.py`,
  `src/nidaro/connectors/models.py`).
- Registry + dispatch service, wired into `ApplicationServices`
  (`src/nidaro/connectors/registry.py`, `src/nidaro/connectors/service.py`,
  `src/nidaro/container.py`).
- Working Taskiq scheduling with cron labels and Redis transport
  (`src/nidaro/jobs/broker.py`, `src/nidaro/jobs/scheduler.py`), plus the
  `connector_sync` placeholder awaiting a body (`src/nidaro/jobs/tasks.py`).
- A provenance table and service (`src/nidaro/sources/*`) and a precedent for
  how external rows are applied to a domain and provenance-linked
  (`docs/research/google-calendar-integration.md` §7).
- Three connector research dossiers (Google Calendar, Apple/CalDAV, WhatsApp)
  under `docs/research/` that establish the intended pattern; the epic
  NIDAR-683r6h cites all three.

Missing (each tracked as a child of the connector-plugin epic NIDAR-683r6h):

- **Cursor persistence** (NIDAR-gdcw4e): `Connector.sync(context, cursor)` is a
  pure function; nothing stores a high-water mark between runs. Ticket proposes
  a per-(household, connector) `connector_cursors` row via repository → service,
  persisted by `ConnectorService.sync`. Until it lands, a school gatherer cannot
  do incremental fetches across runs. Epic NIDAR-683r6h lists this as gap 1.
- **Encrypted credential storage** (NIDAR-cy2xmf): no secret storage exists.
  Ticket requires symmetric encryption keyed from Settings/env, ciphertext in
  PostgreSQL, no plaintext in logs or migrations. A school portal login (if the
  source needs one) depends on this; a fully public source would not.
- **Tombstone semantics** (NIDAR-ryzjms): `ExternalRecord` carries no deletion
  signal, so domain application can upsert but never delete. Ticket acceptance:
  "deleting an external event removes the mirror in nidaro via the application
  service". Matters for a school source the moment a school cancels or
  withdraws an item.
- **Per-household connector config** (NIDAR-8fq38r): no onboarding exists —
  enabled connectors, credential references (ids, not inline secrets), polling
  cadence are to live in PostgreSQL behind the service boundary; the scheduler
  must honor per-household cadence. Today the only scheduling input is the
  static cron label on `heartbeat` (`src/nidaro/jobs/tasks.py`).
- **The connector itself**: the registry is empty and no school connector
  implementation or client exists anywhere under `src/nidaro/connectors/`.
- **A worker body**: `connector_sync` does not iterate households or call
  `ApplicationServices.connectors.sync` yet (`src/nidaro/jobs/tasks.py`).

Epic gating: NIDAR-683r6h states that integration tasks (Calendar, WhatsApp)
"stay blocked until 1, 2 and 4 land" — i.e. cursors, credentials, and config
gate any real connector, including a school one. Tombstones are priority 2.

## 4. Conventions a school connector must follow

- Boundary: route/tool/worker → service → repository → database
  (`docs/architecture.md` diagram; `AGENTS.md`). A school connector calls
  application services; it never opens a session or writes a table itself.
- Connectors produce external records and do not directly mutate unrelated
  domains (`AGENTS.md`; `docs/architecture.md`). School data enters domain
  tables only through a domain application service — the same discipline the
  calendar dossier encodes (`docs/research/google-calendar-integration.md` §7,
  "Applying records: service, not connector").
- PostgreSQL is authoritative for family state; Redis is only the Taskiq
  broker (`AGENTS.md`; `docs/architecture.md`). School state, cursors,
  credentials, and config all belong in PostgreSQL, not Redis and not env-only
  Settings (NIDAR-8fq38r).
- Tombstones: deletions must arrive as a first-class signal on
  `ExternalRecord`/`SyncResult`, and domain mirrors are removed via the
  application service (NIDAR-ryzjms).
- No secrets in source control (`AGENTS.md`; NIDAR-cy2xmf).
- All I/O is async unless a dependency requires otherwise (`AGENTS.md`); the
  calendar dossier deliberately keeps HTTP async (`docs/research/google-calendar-integration.md` §5).
- Scheduled jobs call the same application services as HTTP and assistant code
  (`AGENTS.md`) — a school sync worker goes through
  `ApplicationServices.connectors` and the domain service, not a private path.
- Domain services must not depend on FastAPI, Taskiq, or Pydantic Deep
  (`AGENTS.md`); connector code that a domain service might share must keep
  those imports out.

## Sources

- `docs/architecture.md` — layering diagram, Postgres/Redis split, connector
  record rule, slice scope ("no external connector in this slice").
- `AGENTS.md` — Nidaro architecture rules (boundaries, connector role, async,
  secrets).
- `src/nidaro/connectors/base.py`, `models.py`, `registry.py`, `service.py`,
  `__init__.py` — contract, envelope types, registry, dispatcher.
- `src/nidaro/container.py` — `ApplicationServices.build`, empty registry wiring.
- `src/nidaro/jobs/tasks.py`, `src/nidaro/jobs/broker.py`,
  `src/nidaro/jobs/scheduler.py` — cron scheduling, `connector_sync` placeholder.
- `src/nidaro/sources/models.py`, `repository.py`, `service.py` — `sources`
  table and `SourceService.record`.
- `src/nidaro/calendar/models.py` — `Event.source_id` FK to `sources`.
- `src/nidaro/db/registry.py` — model registry (no connector models).
- `migrations/versions/0001_initial.py`, `0002_meals.py`,
  `0003_calendar_activity_fields.py` — full table set; no external-record,
  cursor, or credential tables.
- `docs/research/google-calendar-integration.md` — intended connector pattern
  (§5 async HTTP, §7 layout, apply-through-service, cursor persistence sketch).
- Rohrpost: NIDAR-683r6h (epic, four gaps, gating), NIDAR-gdcw4e (cursor
  persistence), NIDAR-cy2xmf (encrypted credentials), NIDAR-ryzjms (tombstones),
  NIDAR-8fq38r (per-household config).
