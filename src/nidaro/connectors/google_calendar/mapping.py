"""Pure translation between Google event JSON and nidaro's connector contract.

Deterministic by design (AGENTS.md): no I/O, no clocks — everything the
functions need arrives as arguments. The sync side turns raw `events.list`
items into `ExternalRecord`s (live records shaped as `ExternalEventPayload`,
deletions into tombstones); the write side builds event JSON with nidaro's
mirror-loop markers and merges updates onto a fetched event.

Conventions:
- external id: `"{email}/{calendar_id}/{google_event_id}"` — Google event ids
  are only unique per calendar.
- all-day events: `starts_at` is midnight of `start.date` in the household
  timezone; `ends_at` stays Google's exclusive `end.date` at midnight.
- tombstones (`status: "cancelled"`) carry no payload and no content hash.
  With `singleEvents=True` a cancelled exception of a recurring series is its
  own instance row, so every cancellation tombstones exactly its own event id
  — no `recurringEventId` branching needed at the applier.
"""

import hashlib
import json
from collections.abc import Sequence
from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from nidaro.calendar.recurrence import resolve_timezone
from nidaro.calendar.schemas import ExternalEventPayload
from nidaro.connectors.google_calendar.accounts import CONNECTOR_NAME
from nidaro.connectors.google_calendar.models import GoogleAccountCredentials
from nidaro.connectors.models import ExternalRecord

EXTERNAL_TYPE = "calendar_event"

# Full syncs reach one year back: enough history for "what happened" questions
# without resyncing a lifetime on every 410 reset (the sync guide's own sample
# window).
FULL_SYNC_DAYS = 365

# Mirror-loop markers: events nidaro wrote carry these so the write path can
# recognize its own creations in a fetched event, and a future applier can
# tell own echoes from external edits.
MARKER_KEY = "nidaro"
MARKER_VALUE = "1"
EVENT_ID_PREFIX = "nidaro"  # base32hex-safe ('n','i','d','a','r','o' ≤ 'v')

# nidaro weekday 0..6 (Monday first) → RFC 5545 BYDAY.
BYDAY = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")

# Server-managed fields a get→modify→update merge must not send back.
READ_ONLY_EVENT_FIELDS = (
    "kind",
    "etag",
    "htmlLink",
    "created",
    "updated",
    "creator",
    "organizer",
    "eventType",
)


class UpdateGoogleEventFields(BaseModel):
    """The event fields the write path can change; None leaves them as they are."""

    title: str | None = None
    description: str | None = None
    location: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    is_all_day: bool | None = None


def new_google_event_id() -> str:
    """Client-supplied event id (`nidaro` + UUID4 hex) — valid base32hex, makes
    nidaro→Google creates idempotent and self-identifying."""
    return f"{EVENT_ID_PREFIX}{uuid4().hex}"


def external_id(email: str, calendar_id: str, google_event_id: str) -> str:
    return f"{email}/{calendar_id}/{google_event_id}"


def split_external_id(composite: str) -> tuple[str, str, str]:
    parts = composite.split("/", 2)
    if len(parts) != 3 or not all(parts):
        raise ValueError(
            f"external id {composite!r} is not '<email>/<calendar_id>/<google_event_id>'"
        )
    return parts[0], parts[1], parts[2]


def content_hash(event: dict) -> str:
    """SHA-256 over the semantically relevant fields, canonicalized.

    Deliberately excludes `etag`/`updated`: reminders-only changes bump them
    without touching event content, and etags change on fields nidaro ignores.
    """
    semantic = {
        "attendees": sorted(
            str(attendee.get("email", "")) for attendee in event.get("attendees") or []
        ),
        "extendedProperties": event.get("extendedProperties"),
        "description": event.get("description"),
        "end": event.get("end"),
        "location": event.get("location"),
        "recurrence": event.get("recurrence"),
        "start": event.get("start"),
        "status": event.get("status"),
        "summary": event.get("summary"),
    }
    canonical = json.dumps(semantic, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def to_external_record(
    account: GoogleAccountCredentials,
    event: dict,
    *,
    observed_at: datetime,
    timezone: str,
) -> ExternalRecord:
    """One `events.list` item → one ExternalRecord (or tombstone)."""
    identity = external_id(account.email, account.calendar_id, str(event.get("id", "")))
    if event.get("status") == "cancelled":
        return ExternalRecord(
            connector=CONNECTOR_NAME,
            external_type=EXTERNAL_TYPE,
            external_id=identity,
            payload={},
            content_hash="",
            observed_at=observed_at,
            deleted=True,
        )
    tz = resolve_timezone(timezone)
    starts_at, is_all_day = parse_when(event.get("start") or {}, tz)
    ends_at, _ = parse_when(event.get("end") or {}, tz)
    if starts_at is None:
        raise ValueError(f"Google event {identity} carries no start time")
    payload = ExternalEventPayload(
        title=str(event.get("summary") or ""),
        starts_at=starts_at,
        ends_at=ends_at,
        description=event.get("description"),
        location=event.get("location"),
        is_all_day=is_all_day,
    )
    return ExternalRecord(
        connector=CONNECTOR_NAME,
        external_type=EXTERNAL_TYPE,
        external_id=identity,
        payload=payload.model_dump(mode="json"),
        content_hash=content_hash(event),
        observed_at=observed_at,
    )


def parse_when(when: dict, tz: ZoneInfo) -> tuple[datetime | None, bool]:
    """Google `start`/`end` JSON → aware datetime plus the all-day flag.

    `date` (all-day) has no offset — it is a calendar date, pinned to midnight
    in the household timezone; `dateTime` is RFC 3339 with an offset.
    """
    if not when:
        return None, False
    if "date" in when:
        day = datetime.fromisoformat(str(when["date"]))
        return day.replace(tzinfo=tz), True
    return datetime.fromisoformat(str(when["dateTime"])), False


def build_event_body(
    *,
    event_id: str,
    title: str,
    starts_at: datetime,
    ends_at: datetime | None,
    description: str | None,
    location: str | None,
    is_all_day: bool,
    recurrence_weekdays: list[int] | None,
    attendees: Sequence[str],
    tz: ZoneInfo,
) -> dict:
    """nidaro event fields → `events.insert` body with mirror-loop markers."""
    start = _when_json(_aware(starts_at, tz), is_all_day)
    body: dict = {
        "id": event_id,
        "summary": title,
        "start": start,
        "extendedProperties": {"private": {MARKER_KEY: MARKER_VALUE}},
    }
    if ends_at is not None:
        body["end"] = _when_json(_aware(ends_at, tz), is_all_day)
    elif is_all_day:
        # Google's all-day end.date is exclusive; a same-day event needs the
        # next day as end to appear at all.
        day = _aware(starts_at, tz).date() + timedelta(days=1)
        body["end"] = {"date": day.isoformat()}
    if description is not None:
        body["description"] = description
    if location is not None:
        body["location"] = location
    if recurrence_weekdays:
        byday = ",".join(BYDAY[weekday] for weekday in recurrence_weekdays)
        body["recurrence"] = [f"RRULE:FREQ=WEEKLY;BYDAY={byday}"]
    if attendees:
        body["attendees"] = [{"email": email} for email in attendees]
    return body


def merge_event_update(existing: dict, fields: UpdateGoogleEventFields, *, tz: ZoneInfo) -> dict:
    """Apply the requested changes onto the fetched event (get→modify→put).

    The fetched resource is the base so member-maintained fields (reminders,
    colors, visibility) survive the full-resource PUT; server-managed fields
    are stripped. A 412 on the subsequent update means someone edited the
    event in Google mid-flight — surfaced as a conflict, never clobbered.
    """
    body = {key: value for key, value in existing.items() if key not in READ_ONLY_EVENT_FIELDS}
    if fields.title is not None:
        body["summary"] = fields.title
    if fields.description is not None:
        body["description"] = fields.description
    if fields.location is not None:
        body["location"] = fields.location
    currently_all_day = "date" in (existing.get("start") or {})
    if fields.is_all_day is not None and fields.is_all_day != currently_all_day:
        starts_at = fields.starts_at or _existing_start(existing, tz)
        if starts_at is None:
            raise ValueError("changing all-day mode requires starts_at")
        body["start"] = _when_json(_aware(starts_at, tz), fields.is_all_day)
        if fields.is_all_day:
            body["end"] = {"date": (_aware(starts_at, tz).date() + timedelta(days=1)).isoformat()}
        else:
            body["end"] = _when_json(_aware(starts_at, tz) + timedelta(days=1), False)
    else:
        if fields.starts_at is not None:
            all_day = "date" in (body.get("start") or existing.get("start") or {})
            body["start"] = _when_json(_aware(fields.starts_at, tz), all_day)
        if fields.ends_at is not None:
            all_day = "date" in (body.get("end") or existing.get("end") or {})
            body["end"] = _when_json(_aware(fields.ends_at, tz), all_day)
    return body


def _existing_start(existing: dict, tz: ZoneInfo) -> datetime | None:
    parsed, _ = parse_when(existing.get("start") or {}, tz)
    return parsed


def _when_json(moment: datetime, is_all_day: bool) -> dict:
    if is_all_day:
        return {"date": moment.date().isoformat()}
    return {"dateTime": moment.isoformat()}


def _aware(moment: datetime, tz: ZoneInfo) -> datetime:
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=tz)
