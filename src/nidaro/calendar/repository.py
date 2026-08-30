from datetime import UTC, date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from nidaro.calendar.models import Event
from nidaro.calendar.recurrence import window_bounds
from nidaro.calendar.schemas import CreateEventRequest
from nidaro.household.models import FamilyMember


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

    async def range(
        self, household_id: UUID, from_date: date, to_date: date, tz: ZoneInfo
    ) -> list[Event]:
        start, end_exclusive = window_bounds(from_date, to_date, tz)
        async with self.sessions() as session:
            result = await session.scalars(
                select(Event)
                .options(selectinload(Event.participants))
                .where(
                    Event.household_id == household_id,
                    Event.starts_at < end_exclusive,
                    or_(
                        Event.starts_at >= start,
                        func.cardinality(Event.recurrence_weekdays) > 0,
                    ),
                )
                .order_by(Event.starts_at)
            )
            return list(result)

    async def count(self, household_id: UUID) -> int:
        async with self.sessions() as session:
            result = await session.scalars(
                select(func.count()).select_from(Event).where(Event.household_id == household_id)
            )
            return result.one()

    async def add(self, event: Event, participant_ids: tuple[UUID, ...] = ()) -> Event:
        async with self.sessions.begin() as session:
            if participant_ids:
                members = await session.scalars(
                    select(FamilyMember).where(FamilyMember.id.in_(participant_ids))
                )
                event.participants = list(members)
            session.add(event)
            await session.flush()
            return event

    async def create(self, request: CreateEventRequest) -> Event:
        async with self.sessions.begin() as session:
            event = Event(**request.model_dump())
            session.add(event)
            await session.flush()
            return event
