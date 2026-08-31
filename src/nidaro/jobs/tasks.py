"""Taskiq tasks: heartbeat, the hourly gather pass, one-shot connector syncs.

The hourly pass dispatches a `connector_sync` job for every household whose
config is due (per-household cadence via `ConnectorConfigService.due`,
NIDAR-8fq38r) and whose connector is actually registered; the job itself runs
the sync through `ApplicationServices.connectors`, the same seam the manual
refresh and any future route or assistant tool use.

Routing per connector:
- google_calendar runs the sync-then-apply body (APPLIERS -> CalendarService
  applies the mirrored events).
- icloud_calendar runs through the credential-aware runner
  (`connectors.runner.sync_connector`), which decrypts the household's
  credentials into the run's context and mirrors calendar events.
- bakalari and whatsapp apply internally during sync (WhatsApp events, the
  Bakaláři gather into the school domain) — the plain body counts records.
"""

from collections.abc import Awaitable, Callable
from uuid import UUID

from nidaro.config import get_settings
from nidaro.connectors.models import ConnectorConfig, ConnectorContext
from nidaro.connectors.runner import sync_connector
from nidaro.container import ApplicationServices
from nidaro.db.engine import create_engine, create_session_factory
from nidaro.jobs.broker import broker

APPLIERS: dict[str, str] = {"google_calendar": "calendar"}

_services: ApplicationServices | None = None


def job_services() -> ApplicationServices:
    """Worker-process singleton; Taskiq workers are long-lived."""
    global _services
    if _services is None:
        sessions = create_session_factory(create_engine(get_settings()))
        _services = ApplicationServices.build(sessions)
    return _services


@broker.task(schedule=[{"cron": "*/5 * * * *"}])
async def heartbeat() -> dict[str, str]:
    """Prove that the Taskiq worker can execute a job."""
    return {"status": "ok"}


async def due_registered(services: ApplicationServices) -> list[ConnectorConfig]:
    """Enabled configs whose cadence elapsed, limited to registered connectors.

    Configs for connectors that are not built yet stay in the database but are
    skipped here instead of failing the pass.
    """
    registered = set(services.connectors.registry.names())
    return [
        config
        for config in await services.connector_configs.due()
        if config.connector in registered
    ]


async def sync_household_now(
    services: ApplicationServices, connector_name: str, household_id: str
) -> dict[str, str | int]:
    """One connector sync for one household — the internal-applier body.

    The connector applies its own records during sync (WhatsApp events, the
    Bakaláři gather); this body reports the record count.
    """
    household = await services.household.get_household(UUID(household_id))
    if household is None:
        return {
            "connector": connector_name,
            "household": household_id,
            "status": "household_not_found",
        }
    context = ConnectorContext(household_id=household_id, timezone=household.timezone)
    result = await services.connectors.sync(connector_name, context)
    return {
        "connector": connector_name,
        "household": household_id,
        "status": "ok",
        "records": len(result.records),
    }


async def run_connector_sync(services, connector_name: str, household_id: str) -> dict:
    """One google_calendar run for one household: sync, then mirror to the domain."""
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


@broker.task(schedule=[{"cron": "0 * * * *"}])
async def gather_due() -> dict[str, int]:
    """Roughly hourly: dispatch every due registered connector, per household."""
    dispatched = 0
    for config in await due_registered(job_services()):
        await connector_sync.kiq(config.connector, str(config.household_id))
        dispatched += 1
    return {"dispatched": dispatched}


@broker.task
async def connector_sync(connector_name: str, household_id: str) -> dict[str, str | int]:
    """Sync one connector for one household, routed by applier kind."""
    if connector_name == "icloud_calendar":
        return dict(sync_connector(job_services(), connector_name, UUID(household_id)))
    if connector_name in APPLIERS:
        return await run_connector_sync(job_services(), connector_name, household_id)
    return await sync_household_now(job_services(), connector_name, household_id)
