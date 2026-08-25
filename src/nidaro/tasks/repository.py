from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nidaro.tasks.models import Task
from nidaro.tasks.schemas import CreateTaskRequest


class TaskRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def open(self, household_id: UUID, days: int = 7) -> list[Task]:
        now = datetime.now(UTC)
        async with self.sessions() as session:
            result = await session.scalars(
                select(Task)
                .where(Task.household_id == household_id, Task.status == "open")
                .where((Task.due_at.is_(None)) | (Task.due_at <= now + timedelta(days=days)))
                .order_by(Task.due_at, Task.priority.desc())
            )
            return list(result)

    async def create(self, request: CreateTaskRequest) -> Task:
        async with self.sessions.begin() as session:
            task = Task(**request.model_dump())
            session.add(task)
            await session.flush()
            return task

    async def complete(self, task_id: UUID) -> bool:
        async with self.sessions.begin() as session:
            result = await session.execute(
                update(Task).where(Task.id == task_id).values(status="done")
            )
            return bool(getattr(result, "rowcount", 0) == 1)
