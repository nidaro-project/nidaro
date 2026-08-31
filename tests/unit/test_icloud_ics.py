from datetime import UTC

import pytest

from nidaro.connectors.icloud_ics import (
    content_hash,
    external_id,
    normalize_tzid,
    parse_events,
    series_weekdays,
)

OSLO = "Europe/Oslo"

VENDOR_TZ = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Apple Inc.//macOS 15//EN
BEGIN:VEVENT
UID:trap@example.com
DTSTAMP:20260831T100000Z
DTSTART;TZID=/freeassociation.sourceforge.net/Europe/Oslo:20260914T160000
DTEND;TZID=/freeassociation.sourceforge.net/Europe/Oslo:20260914T173000
SUMMARY:Soccer practice
LOCATION:The fields
DESCRIPTION:Bring shin pads
BEGIN:VALARM
ACTION:DISPLAY
TRIGGER:-PT15M
DESCRIPTION:Alarm noise
END:VALARM
END:VEVENT
END:VCALENDAR
"""

ALL_DAY = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:offday@example.com
DTSTAMP:20260831T100000Z
DTSTART;VALUE=DATE:20261012
SUMMARY:Autumn break
END:VEVENT
END:VCALENDAR
"""

FLOATING = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:floaty@example.com
DTSTAMP:20260831T100000Z
DTSTART:20260910T140000
DTEND:20260910T150000
SUMMARY:Floating time
END:VEVENT
END:VCALENDAR
"""

UNKNOWN_TZ = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:nowhere@example.com
DTSTAMP:20260831T100000Z
DTSTART;TZID=/vendor.example/Nowhere/Nowhere:20260910T140000
SUMMARY:Unknown zone
END:VEVENT
END:VCALENDAR
"""

WEEKLY_SERIES = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:weekly@example.com
DTSTAMP:20260831T100000Z
DTSTART;TZID=Europe/Oslo:20260907T160000
DTEND;TZID=Europe/Oslo:20260907T170000
RRULE:FREQ=WEEKLY;BYDAY=MO,WE
SUMMARY:Weekly series
END:VEVENT
BEGIN:VEVENT
UID:weekly@example.com
DTSTAMP:20260831T100000Z
RECURRENCE-ID;TZID=Europe/Oslo:20260909T160000
DTSTART;TZID=Europe/Oslo:20260909T180000
DTEND;TZID=Europe/Oslo:20260909T190000
SUMMARY:Weekly series (moved)
END:VEVENT
END:VCALENDAR
"""

CANCELLED = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:sad@example.com
DTSTAMP:20260831T100000Z
DTSTART;TZID=Europe/Oslo:20260910T140000
SUMMARY:Cancelled picnic
STATUS:CANCELLED
END:VEVENT
END:VCALENDAR
"""

NO_UID = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
DTSTAMP:20260831T100000Z
DTSTART:20260910T140000
SUMMARY:Anonymous
END:VEVENT
END:VCALENDAR
"""

NO_DTSTART = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:adrift@example.com
DTSTAMP:20260831T100000Z
SUMMARY:Adrift
END:VEVENT
END:VCALENDAR
"""


def test_basic_event_fields_decode_into_domain_vocabulary():
    (event,) = parse_events(VENDOR_TZ, OSLO)
    assert event.uid == "trap@example.com"
    assert event.title == "Soccer practice"
    assert event.location == "The fields"
    assert event.description == "Bring shin pads"
    assert event.status == "scheduled"
    # 16:00 Oslo in September is 14:00 UTC.
    assert event.starts_at.astimezone(UTC).isoformat() == "2026-09-14T14:00:00+00:00"
    assert event.ends_at is not None
    assert event.ends_at.astimezone(UTC).isoformat() == "2026-09-14T15:30:00+00:00"


def test_valarm_noise_is_not_mirrored():
    assert len(parse_events(VENDOR_TZ, OSLO)) == 1
    assert "Alarm noise" not in str(parse_events(VENDOR_TZ, OSLO)[0].model_dump())


def test_all_day_event_anchors_to_household_midnight():
    (event,) = parse_events(ALL_DAY, OSLO)
    assert event.is_all_day is True
    assert event.starts_at.astimezone(UTC).isoformat() == "2026-10-11T22:00:00+00:00"
    assert event.ends_at is None


def test_floating_time_takes_the_household_timezone():
    (event,) = parse_events(FLOATING, OSLO)
    assert event.starts_at.utcoffset() is not None
    assert event.starts_at.astimezone(UTC).isoformat() == "2026-09-10T12:00:00+00:00"


def test_unresolvable_tzid_falls_back_to_household_timezone():
    (event,) = parse_events(UNKNOWN_TZ, OSLO)
    assert event.starts_at.astimezone(UTC).isoformat() == "2026-09-10T12:00:00+00:00"


def test_exception_gets_its_own_identity():
    master, exception = parse_events(WEEKLY_SERIES, OSLO)
    assert master.recurrence_id is None
    assert external_id(master) == "weekly@example.com"
    assert exception.recurrence_id is not None
    assert external_id(exception) == "weekly@example.com/2026-09-09T14:00:00+00:00"
    assert content_hash(exception) != content_hash(master)


def test_weekly_rrule_maps_onto_domain_weekdays():
    master, exception = parse_events(WEEKLY_SERIES, OSLO)
    assert series_weekdays(master) == [0, 2]
    assert series_weekdays(exception) is None  # exceptions are standalone


def test_daily_rrule_covers_every_weekday():
    daily = WEEKLY_SERIES.replace("FREQ=WEEKLY;BYDAY=MO,WE", "FREQ=DAILY")
    master, _exception = parse_events(daily, OSLO)
    assert series_weekdays(master) == [0, 1, 2, 3, 4, 5, 6]


def test_unrepresentable_rrule_falls_back_to_single_occurrence():
    monthly = WEEKLY_SERIES.replace("FREQ=WEEKLY;BYDAY=MO,WE", "FREQ=MONTHLY;BYMONTHDAY=1")
    master, _exception = parse_events(monthly, OSLO)
    assert series_weekdays(master) is None


def test_cancelled_event_is_marked_for_removal():
    (event,) = parse_events(CANCELLED, OSLO)
    assert event.status == "cancelled"


def test_events_without_uid_or_dtstart_are_skipped():
    assert parse_events(NO_UID, OSLO) == []
    assert parse_events(NO_DTSTART, OSLO) == []


def test_content_hash_ignores_server_rewrites():
    rewritten = VENDOR_TZ.replace("PRODID:-//Apple Inc.//macOS 15//EN", "PRODID:-//Rewritten//X//")
    rewritten = rewritten.replace("DTSTAMP:20260831T100000Z", "DTSTAMP:20270101T000000Z")
    reordered = rewritten.replace(
        "SUMMARY:Soccer practice\nLOCATION:The fields",
        "LOCATION:The fields\nSUMMARY:Soccer practice",
    )
    (original,) = parse_events(VENDOR_TZ, OSLO)
    (other,) = parse_events(reordered, OSLO)
    assert content_hash(original) == content_hash(other)
    retitled = VENDOR_TZ.replace("Soccer practice", "Soccer training")
    (changed,) = parse_events(retitled, OSLO)
    assert content_hash(changed) != content_hash(original)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Europe/Oslo", "Europe/Oslo"),
        ("/freeassociation.sourceforge.net/Europe/Berlin", "Europe/Berlin"),
        ("/a/b/Europe/Paris", "Europe/Paris"),
        ("Mars/Olympus", None),
        ("", None),
    ],
)
def test_normalize_tzid_strips_vendor_prefixes(value, expected):
    assert normalize_tzid(value) == expected
