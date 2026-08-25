from nidaro.jobs.broker import broker


@broker.task(schedule=[{"cron": "*/5 * * * *"}])
async def heartbeat() -> dict[str, str]:
    """Prove that the Taskiq worker can execute a job."""
    return {"status": "ok"}


@broker.task
async def connector_sync(connector_name: str) -> dict[str, str]:
    """Placeholder for a future connector synchronization job."""
    return {"connector": connector_name, "status": "not_implemented"}
