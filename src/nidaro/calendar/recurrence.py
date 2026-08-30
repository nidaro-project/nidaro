"""Deterministic read-time expansion for the calendar.

Weekly series (``recurrence_weekdays``) expand to concrete occurrences
through pure date arithmetic in the household timezone. There is no LLM
anywhere in this path. Occurrence identity is ``(event_id, occurrence
date)``; wall-clock times are interpreted naturally in the household
timezone, so DST transitions just shift the UTC offset (zoneinfo
defaults, no special-casing).
"""

from collections.abc import Iterator
from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel

from nidaro.calendar.models import Event

MAX_RANGE_DAYS = 62


class OccurrenceView(BaseModel):
    event_id: UUID
    occurrence_date: date
    title: str
    location: str | None = None
    participant_ids: list[UUID] = []
    is_all_day: bool = False
    starts_at: datetime | None = None
    ends_at: datetime | None = None


def resolve_timezone(name: str | None) -> ZoneInfo:
    """Resolve an IANA timezone name, falling back to UTC when missing or unparseable."""
    if name:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError, KeyError):
            pass
    return ZoneInfo("UTC")


def validate_range(from_date: date, to_date: date) -> None:
    if (to_date - from_date).days > MAX_RANGE_DAYS:
        raise ValueError(f"Range too large: at most {MAX_RANGE_DAYS} days are allowed")


def window_bounds(from_date: date, to_date: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """UTC instants covering the window's calendar days, end-exclusive."""
    start = datetime.combine(from_date, time.min, tzinfo=tz)
    end_exclusive = datetime.combine(to_date + timedelta(days=1), time.min, tzinfo=tz)
    return start.astimezone(timezone.utc), end_exclusive.astimezone(timezone.utc)


def expand_event(
    event: Event, tz: ZoneInfo, from_date: date, to_date: date
) -> list[OccurrenceView]:
    start_local = event.starts_at.astimezone(tz)
    first_date = start_local.date()
    end_local = event.ends_at.astimezone(tz) if event.ends_at else None
    end_time = end_local.time() if end_local else None
    weekdays = set(event.recurrence_weekdays or ())
    participant_ids = sorted(member.id for member in event.participants)

    def view(occurrence_date: date) -> OccurrenceView:
        if event.is_all_day:
            return OccurrenceView(
                event_id=event.id,
                occurrence_date=occurrence_date,
                title=event.title,
                location=event.location,
                participant_ids=participant_ids,
                is_all_day=True,
                starts_at=None,
                ends_at=None,
            )
        return OccurrenceView(
            event_id=event.id,
            occurrence_date=occurrence_date,
            title=event.title,
            location=event.location,
            participant_ids=participant_ids,
            is_all_day=False,
            starts_at=datetime.combine(occurrence_date, start_local.time(), tzinfo=tz),
            ends_at=datetime.combine(occurrence_date, end_time, tzinfo=tz) if end_time else None,
        )

    if weekdays:
        window = _daterange(max(from_date, first_date), to_date)
        dates = [day for day in window if day.weekday() in weekdays]
    elif from_date <= first_date <= to_date:
        dates = [first_date]
    else:
        dates = []
    return [view(day) for day in dates]


def expand_events(
    events: list[Event], tz: ZoneInfo, from_date: date, to_date: date
) -> list[OccurrenceView]:
    """Expand every event and return one merged, time-ordered list."""
    occurrences = [view for event in events for view in expand_event(event, tz, from_date, to_date)]
    return sorted(occurrences, key=_sort_key)


def _daterange(from_date: date, to_date: date) -> Iterator[date]:
    day = from_date
    while day <= to_date:
        yield day
        day += timedelta(days=1)


def _sort_key(view: OccurrenceView) -> tuple[date, time, UUID]:
    wall_clock = view.starts_at.time() if view.starts_at else time.min
    return (view.occurrence_date, wall_clock, view.event_id)
