from datetime import UTC, date, datetime, timedelta
from typing import Any
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
        fields = request.model_dump()
        participant_ids = fields.pop("participants")
        async with self.sessions.begin() as session:
            event = Event(**fields)
            # Always assign the collection (empty or not): the returned event
            # is detached once the session closes, and an unloaded lazy
            # relationship cannot be read afterwards.
            members: list[FamilyMember] = []
            if participant_ids:
                members = list(
                    await session.scalars(
                        select(FamilyMember).where(FamilyMember.id.in_(participant_ids))
                    )
                )
            event.participants = members
            session.add(event)
            await session.flush()
            return event

    async def get_by_external_identity(
        self, household_id: UUID, connector: str, external_id: str
    ) -> Event | None:
        async with self.sessions() as session:
            return await self._mirror_row(session, household_id, connector, external_id)

    async def upsert_mirror(
        self,
        household_id: UUID,
        connector: str,
        external_id: str,
        fields: dict[str, Any],
    ) -> Event:
        """Insert or update the mirror of one external item, atomically.

        `fields` carries the domain-facing mirror content (title, starts_at,
        ...); identity and household come from the arguments. The partial
        unique index on (household, connector, external id) is the race
        safety net under concurrent syncs.
        """
        async with self.sessions.begin() as session:
            row = await self._mirror_row(session, household_id, connector, external_id)
            if row is None:
                row = Event(
                    household_id=household_id,
                    external_connector=connector,
                    external_id=external_id,
                    status="scheduled",
                    **fields,
                )
                session.add(row)
            else:
                for name, value in fields.items():
                    setattr(row, name, value)
            await session.flush()
            return row

    async def remove_mirror(self, household_id: UUID, connector: str, external_id: str) -> bool:
        """Drop the mirror of one external item; False when none existed."""
        async with self.sessions.begin() as session:
            row = await self._mirror_row(session, household_id, connector, external_id)
            if row is None:
                return False
            await session.delete(row)
            await session.flush()
            return True

    @staticmethod
    async def _mirror_row(
        session: AsyncSession, household_id: UUID, connector: str, external_id: str
    ) -> Event | None:
        return await session.scalar(
            select(Event).where(
                Event.household_id == household_id,
                Event.external_connector == connector,
                Event.external_id == external_id,
            )
        )
