from nidaro.config import get_settings
from nidaro.connectors.runner import sync_due
from nidaro.container import ApplicationServices
from nidaro.db.engine import create_engine, create_session_factory
from nidaro.jobs.broker import broker
from nidaro.jobs.service import JobService


@broker.task(schedule=[{"cron": "*/5 * * * *"}])
async def heartbeat() -> dict[str, str]:
    """Prove that the Taskiq worker can execute a job."""
    return {"status": "ok"}


@broker.task(schedule=[{"cron": "*/5 * * * *"}])
async def connector_sync(connector_name: str | None = None) -> dict:
    """Poll every due connector and mirror its records into the domains.

    This is polling, stated plainly: sources like iCloud CalDAV have no
    push channel (no webhooks, no subscriptions), so staleness up to the
    per-household cadence — 15 minutes by default, see
    `DEFAULT_POLL_SECONDS` — is inherent to the design. The cron label
    only sets how often due-ness is checked; `ConnectorConfigService.due`
    decides which households actually sync, so adding a connector or a
    household needs no schedule change.

    Each run is recorded in `job_runs` via `JobService`, like every other
    scheduled job.
    """
    engine = create_engine(get_settings())
    sessions = create_session_factory(engine)
    services = ApplicationServices.build(sessions)
    runs = JobService(sessions)
    run_id = await runs.start("connector_sync", {"connector": connector_name})
    try:
        report = await sync_due(services, connector_name)
        result = report.model_dump()
        await runs.finish(run_id, result=result)
        return result
    except Exception as error:
        await runs.finish(run_id, error=str(error))
        raise
    finally:
        await engine.dispose()
