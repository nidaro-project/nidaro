from uuid import UUID

from nidaro.calendar.repository import CalendarRepository
from nidaro.calendar.schemas import CreateEventRequest, EventView


class CalendarService:
    def __init__(self, repository: CalendarRepository) -> None:
        self.repository = repository

    async def get_upcoming_events(self, household_id: UUID, days: int = 7) -> list[EventView]:
        return [
            EventView.model_validate(event)
            for event in await self.repository.upcoming(household_id, days)
        ]

    async def create_event(self, request: CreateEventRequest) -> EventView:
        return EventView.model_validate(await self.repository.create(request))
