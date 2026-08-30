from datetime import date, datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from nidaro.calendar.models import Event
from nidaro.calendar.recurrence import (
    MAX_RANGE_DAYS,
    expand_event,
    expand_events,
    resolve_timezone,
    validate_range,
    window_bounds,
)
from nidaro.household.models import FamilyMember

PRAGUE = ZoneInfo("Europe/Prague")
MONDAY = date(2030, 6, 3)
THURSDAY = date(2030, 6, 6)


def make_event(**overrides):
    fields = dict(
        id=uuid4(),
        household_id=uuid4(),
        title="Swimming",
        starts_at=datetime.combine(MONDAY, time(16, 0), tzinfo=PRAGUE),
        ends_at=datetime.combine(MONDAY, time(17, 0), tzinfo=PRAGUE),
        location="The pool",
        status="scheduled",
        participants=[],
    )
    fields.update(overrides)
    return Event(**fields)


def make_member(name):
    return FamilyMember(id=uuid4(), household_id=uuid4(), name=name, role="child")


def test_single_event_expands_once_inside_window():
    event = make_event()
    occurrences = expand_event(event, PRAGUE, MONDAY, MONDAY + timedelta(days=6))
    assert len(occurrences) == 1
    occurrence = occurrences[0]
    assert occurrence.event_id == event.id
    assert occurrence.occurrence_date == MONDAY
    assert occurrence.starts_at == event.starts_at
    assert occurrence.ends_at == event.ends_at
    assert occurrence.is_all_day is False
    assert occurrence.participant_ids == []


def test_single_event_outside_window_expands_to_nothing():
    event = make_event()
    assert expand_event(event, PRAGUE, MONDAY + timedelta(days=1), MONDAY + timedelta(days=7)) == []


def test_series_expands_on_matching_weekdays_only():
    event = make_event(recurrence_weekdays=[0, 3], title="Volleyball practice")
    occurrences = expand_event(event, PRAGUE, MONDAY, MONDAY + timedelta(days=13))
    assert [o.occurrence_date for o in occurrences] == [
        MONDAY,
        THURSDAY,
        MONDAY + timedelta(days=7),
        THURSDAY + timedelta(days=7),
    ]
    assert all(
        o.starts_at.hour == 16 and o.starts_at.minute == 0 for o in occurrences if o.starts_at
    )
    assert all(o.ends_at.hour == 17 for o in occurrences if o.ends_at)
    assert len({(o.event_id, o.occurrence_date) for o in occurrences}) == len(occurrences)


def test_series_skips_dates_before_first_occurrence():
    event = make_event(starts_at=datetime.combine(MONDAY, time(16, 0), tzinfo=PRAGUE))
    event.recurrence_weekdays = [0]
    window_start = MONDAY - timedelta(days=14)
    occurrences = expand_event(event, PRAGUE, window_start, MONDAY + timedelta(days=8))
    assert [o.occurrence_date for o in occurrences] == [MONDAY, MONDAY + timedelta(days=7)]


def test_empty_weekdays_treated_as_single_event():
    event = make_event(recurrence_weekdays=[])
    occurrences = expand_event(event, PRAGUE, MONDAY, MONDAY + timedelta(days=6))
    assert len(occurrences) == 1


def test_all_day_occurrences_carry_no_times():
    event = make_event(is_all_day=True, ends_at=None)
    occurrences = expand_event(event, PRAGUE, MONDAY - timedelta(days=1), MONDAY)
    assert len(occurrences) == 1
    occurrence = occurrences[0]
    assert occurrence.occurrence_date == MONDAY
    assert occurrence.is_all_day is True
    assert occurrence.starts_at is None
    assert occurrence.ends_at is None


def test_all_day_series_expands_to_dates_on_weekdays():
    event = make_event(is_all_day=True, ends_at=None, recurrence_weekdays=[3])
    occurrences = expand_event(event, PRAGUE, MONDAY, MONDAY + timedelta(days=13))
    assert [o.occurrence_date for o in occurrences] == [
        THURSDAY,
        THURSDAY + timedelta(days=7),
    ]
    assert all(o.starts_at is None and o.ends_at is None for o in occurrences)


def test_participant_ids_are_copied_and_sorted():
    emma, leo = make_member("Emma"), make_member("Leo")
    event = make_event(participants=[emma, leo])
    occurrence = expand_event(event, PRAGUE, MONDAY, MONDAY)[0]
    assert occurrence.participant_ids == sorted([emma.id, leo.id])


def test_dst_transitions_keep_wall_clock_natural():
    # Europe/Prague leaves DST on Sunday 2030-10-27; wall clock stays 16:00.
    event = make_event(
        starts_at=datetime(2030, 10, 25, 16, 0, tzinfo=PRAGUE),
        recurrence_weekdays=[4, 0],
    )
    occurrences = expand_event(event, PRAGUE, date(2030, 10, 25), date(2030, 11, 4))
    assert [
        (o.occurrence_date, o.starts_at.utcoffset() if o.starts_at else None) for o in occurrences
    ] == [
        (date(2030, 10, 25), timedelta(hours=2)),
        (date(2030, 10, 28), timedelta(hours=1)),
        (date(2030, 11, 1), timedelta(hours=1)),
        (date(2030, 11, 4), timedelta(hours=1)),
    ]


def test_series_within_62_day_window_has_no_duplicate_identity():
    event = make_event(recurrence_weekdays=list(range(7)))
    occurrences = expand_event(event, PRAGUE, MONDAY, MONDAY + timedelta(days=61))
    assert len({(o.event_id, o.occurrence_date) for o in occurrences}) == len(occurrences)
    assert len(occurrences) == 62


def test_resolve_timezone_falls_back_to_utc():
    utc = ZoneInfo("UTC")
    assert resolve_timezone(None) == utc
    assert resolve_timezone("") == utc
    assert resolve_timezone("Mars/Olympus_Mons") == utc
    assert resolve_timezone("Europe/Prague") == PRAGUE


def test_window_bounds_are_utc_midnight_instants():
    start, end_exclusive = window_bounds(MONDAY, THURSDAY, PRAGUE)
    assert start == datetime(2030, 6, 2, 22, 0, tzinfo=ZoneInfo("UTC"))
    assert end_exclusive == datetime(2030, 6, 6, 22, 0, tzinfo=ZoneInfo("UTC"))


def test_validate_range_allows_up_to_62_days():
    validate_range(MONDAY, MONDAY + timedelta(days=MAX_RANGE_DAYS))
    with pytest.raises(ValueError, match="62 days"):
        validate_range(MONDAY, MONDAY + timedelta(days=MAX_RANGE_DAYS + 1))


def test_expand_events_merges_time_ordered_across_events():
    all_day = make_event(title="Birthday", is_all_day=True, ends_at=None)
    early = make_event(title="Early", starts_at=datetime.combine(MONDAY, time(9, 0), tzinfo=PRAGUE))
    late = make_event(
        title="Late", starts_at=datetime.combine(THURSDAY, time(16, 0), tzinfo=PRAGUE)
    )
    merged = expand_events([late, all_day, early], PRAGUE, MONDAY, THURSDAY)
    assert [o.title for o in merged] == ["Birthday", "Early", "Late"]


def test_expand_events_filters_everything_outside_window():
    event = make_event()
    merged = expand_events(
        [event], PRAGUE, MONDAY + timedelta(days=40), MONDAY + timedelta(days=50)
    )
    assert merged == []
