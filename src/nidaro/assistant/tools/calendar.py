from collections.abc import Callable
from typing import Any
from uuid import UUID

from nidaro.calendar.recurrence import OccurrenceView
from nidaro.calendar.schemas import CreateEventRequest, EventView
from nidaro.container import ApplicationServices


def build_calendar_tools(services: ApplicationServices) -> list[Callable[..., Any]]:
    async def get_upcoming_events(household_id: UUID) -> list[OccurrenceView]:
        """Get events for the next seven days, expanded to occurrences."""
        return await services.calendar.get_upcoming_events(household_id)

    async def create_event(request: CreateEventRequest) -> EventView:
        """Create an event in the household calendar."""
        return await services.calendar.create_event(request)

    return [get_upcoming_events, create_event]
