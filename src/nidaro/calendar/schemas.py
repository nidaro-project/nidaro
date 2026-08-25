from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class CreateEventRequest(BaseModel):
    household_id: UUID
    title: str
    starts_at: datetime
    ends_at: datetime | None = None
    description: str | None = None
    location: str | None = None


class EventView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    household_id: UUID
    title: str
    starts_at: datetime
    ends_at: datetime | None
    description: str | None
    location: str | None
    status: str


class UpcomingEvents(BaseModel):
    events: list[EventView] = []
