from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator


class CreateEventRequest(BaseModel):
    household_id: UUID
    title: str
    starts_at: datetime
    ends_at: datetime | None = None
    description: str | None = None
    location: str | None = None
    is_all_day: bool = False
    recurrence_weekdays: list[int] | None = None
    participants: list[UUID] = []

    @field_validator("recurrence_weekdays")
    @classmethod
    def check_weekdays(cls, value):
        if value and any(day not in range(7) for day in value):
            raise ValueError("recurrence_weekdays must contain integers 0..6 (0=Monday)")
        return value


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
    is_all_day: bool = False
    recurrence_weekdays: list[int] | None = None
    participants: list[UUID] = []

    @field_validator("participants", mode="before")
    @classmethod
    def member_ids(cls, value):
        return [getattr(member, "id", member) for member in value]


class UpcomingEvents(BaseModel):
    events: list[EventView] = []


class ExternalEventPayload(BaseModel):
    """Fields a live `external_type="calendar_event"` record must carry.

    The connector resolves source-specific shapes (Google event JSON, iCalendar
    properties, school-portal entries) into this contract; `model_dump()` maps
    one-to-one onto the writable columns of a mirrored `Event`.
    """

    title: str
    starts_at: datetime
    ends_at: datetime | None = None
    description: str | None = None
    location: str | None = None
    is_all_day: bool = False


class MirrorApplyReport(BaseModel):
    """What one `apply_external_records` batch did to the calendar mirrors."""

    applied: int = 0
    removed: int = 0
    skipped: int = 0
