from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nidaro.calendar.models import Event
from nidaro.calendar.schemas import CreateEventRequest


class CalendarRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def upcoming(self, household_id: UUID, days: int = 7) -> list[Event]:
        now = datetime.now(UTC)
        async with self.sessions() as session:
            result = await session.scalars(
                select(Event)
                .where(Event.household_id == household_id, Event.starts_at >= now)
                .where(Event.starts_at <= now + timedelta(days=days))
                .order_by(Event.starts_at)
            )
            return list(result)

    async def create(self, request: CreateEventRequest) -> Event:
        async with self.sessions.begin() as session:
            event = Event(**request.model_dump())
            session.add(event)
            await session.flush()
            return event
