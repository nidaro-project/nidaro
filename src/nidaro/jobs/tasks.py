"""Taskiq tasks: the connector polling loop.

`sync_due_connectors` is the scheduled sweep (every 5 minutes; per-household
cadence is enforced downstream by `ConnectorConfigService.due` via
`poll_seconds`, so the cron is just the tick — deliberately no jitter, quota
is a non-issue at household scale and deterministic scheduling wins).
`connector_sync` runs one connector for one household on demand (the future
webhook path converges here, since a push notification carries no data).

Both tasks call the same application services HTTP and assistant code use
(AGENTS.md): sync through `ApplicationServices.connectors` (cursor
persistence, cadence stamping, stale-cursor reset all live there), then apply
the records through the connector's domain service — the worker never touches
a repository.
"""

from collections.abc import Awaitable, Callable
from functools import lru_cache
from uuid import UUID

from nidaro.connectors.models import ConnectorContext
from nidaro.jobs.broker import broker

# Which domain service applies each connector's records. A connector without
# an entry is not run at all — producing records nobody applies would be a
# silent loss.
APPLIERS: dict[str, str] = {"google_calendar": "calendar"}


@broker.task(schedule=[{"cron": "*/5 * * * *"}])
async def sync_due_connectors() -> dict:
    """Sync every connector config whose household's cadence has elapsed."""
    return await run_due_connector_syncs(services())


@broker.task
async def connector_sync(connector_name: str, household_id: str) -> dict:
    """Sync one connector for one household, outside the cadence sweep."""
    return await run_connector_sync(services(), connector_name, household_id)


def services():
    """Application services for the worker process, built once per process."""
    return _build_services()


@lru_cache
def _build_services():
    from nidaro.config import get_settings
    from nidaro.container import ApplicationServices
    from nidaro.db.engine import create_engine, create_session_factory

    sessions = create_session_factory(create_engine(get_settings()))
    return ApplicationServices.build(sessions)


async def run_due_connector_syncs(
    services, *, now=None, run: Callable[..., Awaitable[dict]] | None = None
) -> dict:
    """The sweep body: every due config, each household isolated.

    One household's failure must not block the others, so per-config errors
    are reported in the result instead of aborting the sweep.
    """
    due = await services.connector_configs.due(now)
    run_one = run or run_connector_sync
    results = [
        await _isolate(run_one, services, config.connector, str(config.household_id))
        for config in due
    ]
    return {"status": "ok", "ran": len(results), "results": results}


async def run_connector_sync(services, connector_name: str, household_id: str) -> dict:
    """One connector run for one household: sync, then apply to the domain."""
    outcome = {
        "connector": connector_name,
        "household_id": household_id,
    }
    applier = APPLIERS.get(connector_name)
    if applier is None:
        return {**outcome, "status": "no_applier"}
    household = await services.household.get_household(UUID(household_id))
    if household is None:
        return {**outcome, "status": "no_household"}
    result = await services.connectors.sync(
        connector_name,
        ConnectorContext(household_id=household_id, timezone=household.timezone),
    )
    report = await getattr(services, applier).apply_external_records(
        UUID(household_id), result.records
    )
    return {
        **outcome,
        "status": "ok",
        "applied": report.applied,
        "removed": report.removed,
        "skipped": report.skipped,
    }


async def _isolate(run_one, services, connector_name: str, household_id: str) -> dict:
    try:
        return await run_one(services, connector_name, household_id)
    except Exception as error:  # isolation is the point: one household's
        # failure must not block the others' syncs
        return {
            "connector": connector_name,
            "household_id": household_id,
            "status": "error",
            "error": str(error),
        }
