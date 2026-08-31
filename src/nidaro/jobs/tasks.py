"""Taskiq tasks: heartbeat, the hourly gather pass, one-shot connector syncs.

The hourly pass dispatches a `connector_sync` job for every household whose
config is due (per-household cadence via `ConnectorConfigService.due`,
NIDAR-8fq38r) and whose connector is actually registered; the job itself runs
the sync through `ApplicationServices.connectors`, the same seam the manual
refresh and any future route or assistant tool use.
"""

from uuid import UUID

from nidaro.config import get_settings
from nidaro.connectors.models import ConnectorConfig, ConnectorContext
from nidaro.container import ApplicationServices
from nidaro.db.engine import create_engine, create_session_factory
from nidaro.jobs.broker import broker

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

    Configs for connectors that are not built yet (WhatsApp, Google Calendar)
    stay in the database but are skipped here instead of failing the pass.
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
    """One connector sync for one household — the worker's and the routes' body."""
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
    """Sync one connector for one household."""
    return await sync_household_now(job_services(), connector_name, household_id)
