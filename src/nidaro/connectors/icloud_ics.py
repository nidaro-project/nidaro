"""Deterministic iCalendar parsing for the iCloud CalDAV connector.

Pure code: no network, no clock, no I/O. `parse_events` decodes one
VCALENDAR resource — exactly what the server returns for an .ics object —
into `IcsEvent` values; the helpers derive the identities, hashes, and
payloads the `ExternalRecord` contract needs. Keeping this outside the
connector class makes every RFC 5545 edge (vendor TZIDs, floating times,
all-day values, RRULEs, exceptions, VALARM noise) unit-testable against
fixture text.

Design decisions this module encodes:

- TZID parameters are normalized before decoding (RFC 5545 §3.2.19).
  Apple-ecosystem servers historically emit vendor-prefixed TZIDs such as
  ``/freeassociation.sourceforge.net/Europe/Berlin``; icalendar would only
  *guess* those with a warning, so the prefix is stripped here and the
  result must be a real zoneinfo key — otherwise the event decodes with
  the household timezone (RFC floating-time semantics).
- ``STATUS:CANCELLED`` events become tombstones at the connector layer
  (same policy as Google's cancelled events): the calendar domain cannot
  express struck-through occurrences, so a cancelled event is removed from
  the mirror rather than shown as if it would still happen.
- Only daily and weekly RRULEs map onto the domain's
  ``recurrence_weekdays`` model; any other recurrence falls back to a
  single occurrence (the first). Exceptions (``RECURRENCE-ID``) mirror as
  standalone events keyed ``uid/recurrence-id``; a moved weekly occurrence
  therefore shows in both the old and the new slot — a known, accepted
  artifact of the weekly-only domain model.
- ``content_hash`` is a SHA-256 over a canonical projection of the parsed
  fields, never over raw ICS bytes: Apple's server rewrites property
  order, DTSTAMP, and PRODID on round-trip, so byte hashing would produce
  phantom changes on every poll.
"""

import hashlib
import json
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from icalendar import Calendar
from pydantic import BaseModel

from nidaro.calendar.recurrence import resolve_timezone

WEEKDAY_CODES = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}

CANCELLED = "cancelled"


class IcsEvent(BaseModel):
    """One VEVENT decoded into calendar-domain vocabulary."""

    uid: str
    title: str
    starts_at: datetime
    ends_at: datetime | None = None
    is_all_day: bool = False
    description: str | None = None
    location: str | None = None
    status: str = "scheduled"
    recurrence_id: datetime | None = None
    rrule: dict[str, list[str]] | None = None


def normalize_tzid(value: str) -> str | None:
    """Strip vendor prefixes from a TZID until a real zoneinfo key remains.

    ``/freeassociation.sourceforge.net/Europe/Berlin`` becomes
    ``Europe/Berlin``; a plain IANA name passes through unchanged; a value
    with no usable segment returns None (the caller applies floating-time
    semantics).
    """
    candidate = value.strip()
    while candidate:
        try:
            ZoneInfo(candidate)
            return candidate
        except (ZoneInfoNotFoundError, ValueError, KeyError):
            pass
        if "/" not in candidate:
            return None
        candidate = candidate.split("/", 1)[1]
    return None


def parse_events(ics_text: str, default_timezone: str) -> list[IcsEvent]:
    """Decode every VEVENT of one VCALENDAR resource, VALARMs stripped.

    VEVENTs without a UID are skipped: the UID is the only stable identity
    the mirror contract has, and an event without one cannot be mirrored
    idempotently.
    """
    tz = resolve_timezone(default_timezone)
    calendar = Calendar.from_ical(ics_text)
    events: list[IcsEvent] = []
    for component in calendar.walk("VEVENT"):
        uid = str(component.get("UID") or "").strip()
        if not uid:
            continue
        event = _decode_event(component, uid, tz)
        if event is not None:
            events.append(event)
    return events


def external_id(event: IcsEvent) -> str:
    """Stable mirror identity: the UID, plus the recurrence-id for exceptions."""
    if event.recurrence_id is None:
        return event.uid
    return f"{event.uid}/{event.recurrence_id.astimezone(UTC).isoformat()}"


def series_weekdays(event: IcsEvent) -> list[int] | None:
    """Map an RRULE onto the domain's weekly recurrence model, if expressible.

    Daily series cover every weekday; weekly series map BYDAY (falling back
    to the series anchor's weekday); anything else — monthly, yearly,
    count-bounded oddities — is not representable and returns None, which
    the mirror stores as a single occurrence.
    """
    if event.rrule is None:
        return None
    freq = [value.upper() for value in event.rrule.get("freq", [])]
    if "DAILY" in freq:
        return list(range(7))
    if "WEEKLY" in freq:
        byday = event.rrule.get("byday", [])
        weekdays = sorted(
            WEEKDAY_CODES[code.upper()] for code in byday if code.upper() in WEEKDAY_CODES
        )
        if weekdays:
            return weekdays
        return [event.starts_at.weekday()]
    return None


def content_hash(event: IcsEvent) -> str:
    """SHA-256 over the canonical field projection — never over ICS bytes."""
    projection = {
        "title": event.title,
        "starts_at": event.starts_at.astimezone(UTC).isoformat(),
        "ends_at": event.ends_at.astimezone(UTC).isoformat() if event.ends_at else None,
        "is_all_day": event.is_all_day,
        "description": event.description,
        "location": event.location,
        "status": event.status,
        "recurrence_id": (
            event.recurrence_id.astimezone(UTC).isoformat() if event.recurrence_id else None
        ),
        "rrule": _canonical_rrule(event.rrule),
    }
    canonical = json.dumps(projection, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def record_payload(event: IcsEvent, calendar_url: str, href: str) -> dict:
    """Mirror fields (the ExternalEventPayload contract) plus provenance.

    The provenance keys ride along for debugging; the calendar service
    validates payloads against ExternalEventPayload and ignores extras.
    """
    return {
        "title": event.title,
        "starts_at": event.starts_at,
        "ends_at": event.ends_at,
        "description": event.description,
        "location": event.location,
        "is_all_day": event.is_all_day,
        "recurrence_weekdays": series_weekdays(event),
        "recurrence_id": (
            event.recurrence_id.astimezone(UTC).isoformat() if event.recurrence_id else None
        ),
        "rrule": _canonical_rrule(event.rrule),
        "calendar_url": calendar_url,
        "href": href,
    }


def _decode_event(component, uid: str, tz: ZoneInfo) -> IcsEvent | None:
    """Decode one VEVENT; None when it cannot be placed on a timeline."""
    starts = component.get("DTSTART")
    if starts is None:
        return None
    start = _decode_when(starts, tz)
    if isinstance(start, date) and not isinstance(start, datetime):
        start = datetime.combine(start, time.min, tzinfo=tz)
        all_day = True
    else:
        all_day = False
    ends = component.get("DTEND")
    end = _decode_when(ends, tz) if ends is not None else None
    if isinstance(end, date) and not isinstance(end, datetime):
        end = datetime.combine(end, time.min, tzinfo=tz)
    status = str(component.get("STATUS") or "").strip().upper()
    recurrence = component.get("RECURRENCE-ID")
    rrule = component.get("RRULE")
    return IcsEvent(
        uid=uid,
        title=str(component.get("SUMMARY") or uid),
        starts_at=start,
        ends_at=end,
        is_all_day=all_day,
        description=_text(component.get("DESCRIPTION")),
        location=_text(component.get("LOCATION")),
        status=CANCELLED if status == "CANCELLED" else "scheduled",
        recurrence_id=_decode_when(recurrence, tz) if recurrence is not None else None,
        rrule=_canonical_rrule_dict(rrule) if rrule is not None else None,
    )


def _decode_when(prop, tz: ZoneInfo) -> datetime | date:
    """Decode one date/date-time property with explicit TZID handling.

    icalendar resolves TZIDs itself at parse time — including by guessing
    on vendor-prefixed values — so the raw value text is decoded here
    instead, with the TZID parameter normalized first.
    """
    value = prop.to_ical().decode("ascii").strip()
    if prop.params.get("VALUE") == "DATE" or len(value) == 8:
        return date(int(value[0:4]), int(value[4:6]), int(value[6:8]))
    utc = value.endswith("Z")
    raw = value.rstrip("Z")
    if "." in raw:
        raw = raw.split(".", 1)[0]
    moment = datetime.strptime(raw, "%Y%m%dT%H%M%S")
    if utc:
        return moment.replace(tzinfo=UTC)
    tzid = normalize_tzid(str(prop.params.get("TZID") or ""))
    return moment.replace(tzinfo=ZoneInfo(tzid) if tzid else tz)


def _text(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _canonical_rrule_dict(rrule) -> dict[str, list[str]]:
    return {str(key).lower(): [str(item) for item in values] for key, values in rrule.items()}


def _canonical_rrule(rrule: dict[str, list[str]] | None) -> list[str] | None:
    if rrule is None:
        return None
    return [f"{key}={'|'.join(values)}" for key, values in sorted(rrule.items())]
