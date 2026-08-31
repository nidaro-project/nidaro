from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from nidaro.connectors.google_calendar.accounts import GoogleAccountCredentials
from nidaro.connectors.google_calendar.mapping import (
    MARKER_KEY,
    UpdateGoogleEventFields,
    build_event_body,
    content_hash,
    external_id,
    merge_event_update,
    new_google_event_id,
    split_external_id,
    to_external_record,
)
from nidaro.connectors.models import ExternalRecord

PRAGUE = ZoneInfo("Europe/Prague")
OBSERVED = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
ACCOUNT = GoogleAccountCredentials(
    email="ada@example.com",
    calendar_id="primary",
    scopes=["https://www.googleapis.com/auth/calendar.events"],
    refresh_token="rt",
)


def google_event(**overrides):
    event = {
        "id": "evt1",
        "status": "confirmed",
        "summary": "Dentist",
        "description": "six-month check",
        "location": "Vinohrady",
        "start": {"dateTime": "2026-09-03T17:00:00+02:00"},
        "end": {"dateTime": "2026-09-03T18:00:00+02:00"},
        "etag": '"etag/1"',
        "updated": "2026-08-30T10:00:00Z",
    }
    event.update(overrides)
    return {key: value for key, value in event.items() if value is not None}


def record_for(event, **kwargs):
    overrides = {
        "account": ACCOUNT,
        "event": event,
        "observed_at": OBSERVED,
        "timezone": "Europe/Prague",
    }
    overrides.update(kwargs)
    return to_external_record(**overrides)


def test_external_id_composes_and_splits():
    identity = external_id("ada@example.com", "primary", "evt1")
    assert identity == "ada@example.com/primary/evt1"
    assert split_external_id(identity) == ("ada@example.com", "primary", "evt1")


@pytest.mark.parametrize("composite", ["", "onlyone", "two/parts", "a//c"])
def test_split_rejects_malformed_ids(composite):
    with pytest.raises(ValueError, match="external id"):
        split_external_id(composite)


def test_new_event_ids_are_nidaro_prefixed_base32hex():
    event_id = new_google_event_id()
    assert event_id.startswith("nidaro")
    assert set(event_id) <= set("nidaro0123456789abcdef")
    assert 5 <= len(event_id) <= 1024
    assert event_id != new_google_event_id()


def test_timed_event_maps_into_the_external_payload_shape():
    record = record_for(google_event())

    assert record.connector == "google_calendar"
    assert record.external_type == "calendar_event"
    assert record.external_id == "ada@example.com/primary/evt1"
    assert record.deleted is False
    assert record.payload == {
        "title": "Dentist",
        "starts_at": "2026-09-03T17:00:00+02:00",
        "ends_at": "2026-09-03T18:00:00+02:00",
        "description": "six-month check",
        "location": "Vinohrady",
        "is_all_day": False,
        "recurrence_weekdays": None,
    }
    assert len(record.content_hash) == 64


def test_all_day_event_pins_midnight_in_household_timezone():
    record = record_for(
        google_event(
            start={"date": "2026-09-03"},
            end={"date": "2026-09-05"},
            description=None,
            location=None,
        )
    )

    assert record.payload["is_all_day"] is True
    assert record.payload["starts_at"] == "2026-09-03T00:00:00+02:00"
    # Google's end.date is exclusive: it lands as-is, still midnight.
    assert record.payload["ends_at"] == "2026-09-05T00:00:00+02:00"


def test_event_without_summary_gets_an_empty_title():
    record = record_for(google_event(summary=None))
    assert record.payload["title"] == ""


def test_cancelled_event_becomes_a_bare_tombstone():
    record = record_for(google_event(status="cancelled", recurringEventId="evt-parent"))

    assert record.deleted is True
    assert record.payload == {}
    assert record.content_hash == ""
    assert record.external_id == "ada@example.com/primary/evt1"


def test_content_hash_ignores_etag_and_reminder_noise():
    base = google_event()
    noisy = google_event(
        etag='"etag/2"', updated="2026-08-31T09:00:00Z", reminders={"useDefault": True}
    )

    assert content_hash(base) == content_hash(noisy)


def test_content_hash_changes_when_content_changes():
    base = google_event()
    moved = google_event(start={"dateTime": "2026-09-04T17:00:00+02:00"})

    assert content_hash(base) != content_hash(moved)


def test_body_carries_client_id_markers_and_fields():
    body = build_event_body(
        event_id="nidaroabc123",
        title="Swim class",
        starts_at=datetime(2026, 9, 3, 17, 0, tzinfo=PRAGUE),
        ends_at=datetime(2026, 9, 3, 18, 0, tzinfo=PRAGUE),
        description="weekly",
        location="Pool",
        is_all_day=False,
        recurrence_weekdays=[3],
        attendees=["ben@example.com"],
        tz=PRAGUE,
    )

    assert body["id"] == "nidaroabc123"
    assert body["summary"] == "Swim class"
    assert body["start"] == {"dateTime": "2026-09-03T17:00:00+02:00"}
    assert body["end"] == {"dateTime": "2026-09-03T18:00:00+02:00"}
    assert body["description"] == "weekly"
    assert body["location"] == "Pool"
    assert body["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=TH"]
    assert body["attendees"] == [{"email": "ben@example.com"}]
    assert body["extendedProperties"]["private"][MARKER_KEY] == "1"


def test_body_omits_absent_fields_and_treats_all_day_end_as_exclusive():
    body = build_event_body(
        event_id="nidaroabc123",
        title="Picnic",
        starts_at=datetime(2026, 9, 3, tzinfo=PRAGUE),
        ends_at=None,
        description=None,
        location=None,
        is_all_day=True,
        recurrence_weekdays=None,
        attendees=[],
        tz=PRAGUE,
    )

    assert "description" not in body
    assert "location" not in body
    assert "recurrence" not in body
    assert "attendees" not in body
    assert body["start"] == {"date": "2026-09-03"}
    assert body["end"] == {"date": "2026-09-04"}


def test_body_assumes_household_timezone_for_naive_datetimes():
    body = build_event_body(
        event_id="nidaroabc123",
        title="Naive",
        starts_at=datetime(2026, 9, 3, 17, 0),
        ends_at=None,
        description=None,
        location=None,
        is_all_day=False,
        recurrence_weekdays=None,
        attendees=[],
        tz=PRAGUE,
    )

    assert body["start"] == {"dateTime": "2026-09-03T17:00:00+02:00"}


def fetched_event():
    return google_event(
        attendees=[{"email": "ben@example.com", "responseStatus": "accepted"}],
        extendedProperties={"private": {MARKER_KEY: "1"}},
        reminders={"useDefault": True},
        transparency="transparent",
        recurrence=["RRULE:FREQ=WEEKLY;BYDAY=TH"],
    )


def test_merge_strips_server_fields_and_keeps_member_fields():
    merged = merge_event_update(fetched_event(), UpdateGoogleEventFields(title="Moved"), tz=PRAGUE)

    for stripped in ("kind", "etag", "htmlLink", "created", "updated", "creator", "organizer"):
        assert stripped not in merged
    assert merged["summary"] == "Moved"
    assert merged["reminders"] == {"useDefault": True}
    assert merged["transparency"] == "transparent"
    assert merged["extendedProperties"]["private"][MARKER_KEY] == "1"
    assert merged["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=TH"]


def test_merge_leaves_untouched_fields_alone():
    original = fetched_event()

    merged = merge_event_update(original, UpdateGoogleEventFields(location="New hall"), tz=PRAGUE)

    assert merged["summary"] == original["summary"]
    assert merged["start"] == original["start"]
    assert merged["end"] == original["end"]


def test_merge_reschedules_respecting_all_day_mode():
    merged = merge_event_update(
        fetched_event(),
        UpdateGoogleEventFields(starts_at=datetime(2026, 9, 10, 9, 0, tzinfo=PRAGUE)),
        tz=PRAGUE,
    )
    assert merged["start"] == {"dateTime": "2026-09-10T09:00:00+02:00"}

    all_day = merge_event_update(
        google_event(start={"date": "2026-09-03"}, end={"date": "2026-09-04"}),
        UpdateGoogleEventFields(starts_at=datetime(2026, 9, 10, tzinfo=PRAGUE)),
        tz=PRAGUE,
    )
    assert all_day["start"] == {"date": "2026-09-10"}
    assert all_day["end"] == {"date": "2026-09-04"}


def test_merge_flips_all_day_mode_from_starts_at():
    merged = merge_event_update(
        fetched_event(),
        UpdateGoogleEventFields(
            is_all_day=True, starts_at=datetime(2026, 9, 10, 8, 0, tzinfo=PRAGUE)
        ),
        tz=PRAGUE,
    )

    assert merged["start"] == {"date": "2026-09-10"}
    assert merged["end"] == {"date": "2026-09-11"}


def test_merge_flip_uses_existing_start_when_not_given():
    merged = merge_event_update(
        fetched_event(), UpdateGoogleEventFields(is_all_day=True), tz=PRAGUE
    )

    assert merged["start"] == {"date": "2026-09-03"}
    assert merged["end"] == {"date": "2026-09-04"}


def test_merge_flip_without_any_start_is_refused():
    with pytest.raises(ValueError, match="all-day"):
        merge_event_update({"id": "evt1"}, UpdateGoogleEventFields(is_all_day=True), tz=PRAGUE)


def test_record_type_defaults_live():
    record = ExternalRecord(
        connector="google_calendar",
        external_type="calendar_event",
        external_id="x",
        payload={},
        content_hash="",
        observed_at=OBSERVED,
    )
    assert record.deleted is False
