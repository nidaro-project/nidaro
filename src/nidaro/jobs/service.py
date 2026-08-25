from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nidaro.db.types import utc_now
from nidaro.jobs.models import JobRun


class JobService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def start(self, job_type: str, parameters: dict[str, Any]) -> UUID:
        async with self.sessions.begin() as session:
            run = JobRun(
                job_type=job_type, parameters=parameters, status="running", started_at=utc_now()
            )
            session.add(run)
            await session.flush()
            return run.id

    async def finish(
        self, run_id: UUID, result: dict[str, Any] | None = None, error: str | None = None
    ) -> None:
        async with self.sessions.begin() as session:
            run = await session.get(JobRun, run_id)
            if run is not None:
                run.status = "failed" if error else "succeeded"
                run.finished_at = datetime.now().astimezone()
                run.result = result
                run.error = error
