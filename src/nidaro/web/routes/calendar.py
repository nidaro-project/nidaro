"""Server-rendered family calendar: month wall grid, week and day agenda.

The route owns presentation math only (window bounds, day grouping,
labels). Occurrence data comes from ``CalendarService.range`` through the
same application-services boundary as the API; the visible window and
its offset live in the URL (``?view=month|week|day&o=N``) so every state
deep-links and survives a reload.
"""

from datetime import date, datetime, time, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request

from nidaro.calendar.recurrence import (
    OccurrenceView,
    first_weekday_on_or_after,
    resolve_timezone,
)
from nidaro.calendar.schemas import CreateEventRequest
from nidaro.container import ApplicationServices
from nidaro.household.schemas import HouseholdView
from nidaro.web.dependencies import get_services
from nidaro.web.routes.ui import _nav, templates

router = APIRouter(include_in_schema=False)

VIEWS: dict[str, str] = {"month": "Month", "week": "Week", "day": "Day"}

# Context padded around the visible window before asking the service: any
# weekly series occurs at least twice inside it, so an event id seen on
# 2+ dates is a reliable repeat marker for the ↻ badge.
PAD_DAYS = 7

# Timed chips per month cell before the rest collapses into "+N more".
MAX_CHIPS = 3

# Weekday checkbox group, Monday first (matches recurrence_weekdays 0=Mon..6=Sun).
WEEKDAY_ITEMS = tuple(
    (index, label) for index, label in enumerate(("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"))
)


@router.get("/calendar")
async def calendar_page(
    request: Request,
    services: Annotated[ApplicationServices, Depends(get_services)],
    view: str = "month",
    o: int = 0,
):
    return templates.TemplateResponse(request, "calendar.html", await _context(services, view, o))


@router.post("/calendar/events")
async def create_activity(
    request: Request,
    services: Annotated[ApplicationServices, Depends(get_services)],
    view: Annotated[str, Form()] = "month",
    o: Annotated[int, Form()] = 0,
    title: Annotated[str, Form()] = "",
    mode: Annotated[str, Form()] = "single",
    on: Annotated[str, Form()] = "",
    starts: Annotated[str, Form()] = "",
    ends: Annotated[str, Form()] = "",
    all_day: Annotated[str, Form()] = "",
    weekdays: Annotated[list[int], Form()] | None = None,
    participants: Annotated[list[UUID], Form()] | None = None,
    location: Annotated[str, Form()] = "",
):
    """HTMX add-activity post: create through the application service, then
    re-render the current view as the ``calendar_main`` fragment so the new
    activity is visible. Invalid input re-renders the form open, with the
    submitted values kept and a plain error message."""
    household = await services.household.get_household()
    if household is None:
        raise HTTPException(status_code=404, detail="Household not seeded")
    event, error = _compose_event(
        household,
        title=title,
        mode=mode,
        on=on,
        starts=starts,
        ends=ends,
        all_day=bool(all_day),
        weekdays=weekdays or [],
        participants=participants or [],
        location=location,
    )
    if event is None:
        submitted = {
            "title": title,
            "mode": mode,
            "on": on,
            "starts": starts,
            "ends": ends,
            "all_day": bool(all_day),
            "weekdays": weekdays or [],
            "participants": participants or [],
            "location": location,
        }
        context = await _context(services, view, o, household)
        return templates.TemplateResponse(
            request, "calendar_main.html", context | {"error": error, "form": submitted}
        )
    await services.calendar.create_event(event)
    return templates.TemplateResponse(
        request, "calendar_main.html", await _context(services, view, o, household)
    )


async def _context(services: ApplicationServices, view: str, o: int, household=None):
    """Shared page/fragment context: window, occurrences, people, form data."""
    if view not in VIEWS:
        raise HTTPException(status_code=404, detail="Unknown calendar view")
    household = household or await services.household.get_household()
    if household is None:
        raise HTTPException(status_code=404, detail="Household not seeded")
    today = datetime.now(resolve_timezone(household.timezone)).date()
    first, last = _window(view, today, o)
    occurrences = await services.calendar.range(
        household.id, first - timedelta(days=PAD_DAYS), last + timedelta(days=PAD_DAYS)
    )
    context = _page_context(view, o, today, first, last, occurrences, household)
    # Empty form/error defaults: the add popover renders pristine outside the
    # validation-failure path (which overrides both).
    return context | {"weekday_items": WEEKDAY_ITEMS, "form": {}, "error": ""}


def _compose_event(
    household: HouseholdView,
    *,
    title: str,
    mode: str,
    on: str,
    starts: str,
    ends: str,
    all_day: bool,
    weekdays: list[int],
    participants: list[UUID],
    location: str,
):
    """Turn submitted form values into a CreateEventRequest.

    Returns (request, None) on success and (None, message) on invalid input;
    exactly one side is None. A weekly series is anchored to its first
    occurrence on/after the chosen date, in the household timezone — the
    same deterministic arithmetic the seeds use (see recurrence.py).
    """
    clean_title = title.strip()
    if not clean_title:
        return None, "Give the activity a title."
    start_date = _parse_date(on)
    if start_date is None:
        return None, "Choose a start date."
    weekly = mode == "weekly"
    picked = sorted(set(weekdays))
    if weekly:
        if not picked or any(day not in range(7) for day in picked):
            return None, "Pick at least one weekday."
        start_date = first_weekday_on_or_after(start_date, picked)
    start_time = time.min if all_day else _parse_time(starts)
    if start_time is None:
        return None, "Choose a start time."
    end_time = _parse_time(ends) if not all_day and ends else None
    if end_time is not None and end_time <= start_time:
        return None, "The end time must come after the start time."
    tz = resolve_timezone(household.timezone)
    request = CreateEventRequest(
        household_id=household.id,
        title=clean_title,
        starts_at=datetime.combine(start_date, start_time, tzinfo=tz),
        ends_at=datetime.combine(start_date, end_time, tzinfo=tz) if end_time else None,
        location=location.strip() or None,
        is_all_day=all_day,
        recurrence_weekdays=picked if weekly else None,
        participants=list(participants),
    )
    return request, None


def _parse_date(raw: str):
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _parse_time(raw: str):
    try:
        return time.fromisoformat(raw)
    except ValueError:
        return None


def _page_context(
    view: str,
    o: int,
    today: date,
    first: date,
    last: date,
    occurrences: list[OccurrenceView],
    household,
) -> dict[str, object]:
    repeats = _repeat_ids(occurrences)
    people = {
        member.id: (member.name, index % 4)
        for index, member in enumerate(sorted(household.members, key=lambda m: m.name))
    }
    by_day: dict[date, list[OccurrenceView]] = {}
    for occurrence in occurrences:
        if first <= occurrence.occurrence_date <= last:
            by_day.setdefault(occurrence.occurrence_date, []).append(occurrence)
    days, day = [], first
    anchor_month = _shift_month(today, o).month if view == "month" else today.month
    while day <= last:
        days.append(_day(day, today, anchor_month, by_day.get(day, []), people, repeats))
        day += timedelta(days=1)
    return {
        "nav": _nav("calendar"),
        "view": view,
        "o": o,
        "view_items": list(VIEWS.items()),
        "range_label": _range_label(view, first, last, today, o),
        "days": days,
        "weeks": [days[i : i + 7] for i in range(0, len(days), 7)] if view == "month" else [],
        "people": people,
    }


def _window(view: str, today: date, o: int) -> tuple[date, date]:
    """Visible date range: the month grid (Monday-start), Mon..Sun, or one day."""
    if view == "month":
        first_of_month = _shift_month(today, o)
        last_of_month = (first_of_month + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        grid_start = first_of_month - timedelta(days=first_of_month.weekday())
        grid_end = last_of_month + timedelta(days=6 - last_of_month.weekday())
        return grid_start, grid_end
    if view == "week":
        monday = today - timedelta(days=today.weekday()) + timedelta(weeks=o)
        return monday, monday + timedelta(days=6)
    day = today + timedelta(days=o)
    return day, day


def _shift_month(anchor: date, o: int) -> date:
    return (anchor.replace(day=1) + timedelta(days=32 * o)).replace(day=1)


def _day(
    day: date,
    today: date,
    anchor_month: int,
    views: list[OccurrenceView],
    people: dict[UUID, tuple[str, int]],
    repeats: set[UUID],
) -> dict[str, object]:
    items = [_item(view, people, view.event_id in repeats) for view in views]
    timed = [item for item in items if not item["allday"]]
    return {
        "date": day,
        "iso": day.isoformat(),
        "weekday": day.strftime("%a"),
        "day_num": day.strftime("%-d"),
        "day_long": day.strftime("%A, %B %-d"),
        "is_today": day == today,
        "in_month": day.month == anchor_month,
        "offset": (day - today).days,
        "rows": items,
        "allday": [item for item in items if item["allday"]],
        "timed": timed,
        "more": max(len(timed) - MAX_CHIPS, 0),
    }


def _item(
    view: OccurrenceView,
    people: dict[UUID, tuple[str, int]],
    repeat: bool,
) -> dict[str, object]:
    participants = [people[pid] for pid in view.participant_ids if pid in people]
    return {
        "title": view.title,
        "location": view.location,
        "repeat": repeat,
        "allday": view.is_all_day,
        "time_long": _time_long(view),
        "time_short": "" if view.starts_at is None else view.starts_at.strftime("%H:%M"),
        "initials": "".join(name[0] for name, _ in participants),
        "names": ", ".join(name for name, _ in participants),
        "avatars": [index for _, index in participants],
    }


def _time_long(view: OccurrenceView) -> str:
    if view.starts_at is None:
        return ""
    start = _clock(view.starts_at)
    return start if view.ends_at is None else f"{start} - {_clock(view.ends_at)}"


def _clock(at: datetime) -> str:
    return at.strftime("%-I:%M %p").lstrip("0")


def _range_label(view: str, first: date, last: date, today: date, o: int) -> str:
    if view == "month":
        return _shift_month(today, o).strftime("%B %Y")
    if view == "week":
        return f"{first.strftime('%b %-d')} - {last.strftime('%b %-d')}"
    return first.strftime("%A, %B %-d")


def _repeat_ids(occurrences: list[OccurrenceView]) -> set[UUID]:
    """Event ids occurring on 2+ dates inside the padded window = weekly series."""
    counts: dict[UUID, int] = {}
    for occurrence in occurrences:
        counts[occurrence.event_id] = counts.get(occurrence.event_id, 0) + 1
    return {event_id for event_id, count in counts.items() if count > 1}
