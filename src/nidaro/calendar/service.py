from datetime import date, datetime, timedelta
from uuid import UUID

from nidaro.calendar.recurrence import (
    OccurrenceView,
    expand_events,
    resolve_timezone,
    validate_range,
)
from nidaro.calendar.repository import CalendarRepository
from nidaro.calendar.schemas import CreateEventRequest, EventView
from nidaro.household.repository import HouseholdRepository


class CalendarService:
    def __init__(self, repository: CalendarRepository, households: HouseholdRepository) -> None:
        self.repository = repository
        self.households = households

    async def range(
        self, household_id: UUID, from_date: date, to_date: date
    ) -> list[OccurrenceView]:
        validate_range(from_date, to_date)
        tz = await self._household_timezone(household_id)
        events = await self.repository.range(household_id, from_date, to_date, tz)
        return expand_events(events, tz, from_date, to_date)

    async def get_upcoming_events(self, household_id: UUID, days: int = 7) -> list[OccurrenceView]:
        tz = await self._household_timezone(household_id)
        today = datetime.now(tz).date()
        return await self.range(household_id, today, today + timedelta(days=days - 1))

    async def create_event(self, request: CreateEventRequest) -> EventView:
        return EventView.model_validate(await self.repository.create(request))

    async def _household_timezone(self, household_id: UUID):
        household = await self.households.get(household_id)
        return resolve_timezone(household.timezone if household else None)
