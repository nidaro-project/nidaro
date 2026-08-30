from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from nidaro.app import create_app
from nidaro.calendar.recurrence import OccurrenceView
from nidaro.calendar.service import CalendarService
from nidaro.household.schemas import FamilyMemberView, HouseholdView
from nidaro.household.service import HouseholdService
from nidaro.web.dependencies import get_services
from nidaro.web.routes.calendar import PAD_DAYS


def _client() -> TestClient:
    # No lifespan context: UI pages must render without touching PostgreSQL or Redis.
    return TestClient(create_app())


def test_home_renders_shell():
    response = _client().get("/")
    assert response.status_code == 200
    assert "Good morning, Morgan family" in response.text
    assert 'data-theme="daylight"' in response.text
    assert response.text.count('class="nav__link"') == 9


def test_home_links_static_assets():
    response = _client().get("/")
    for asset in (
        "/static/css/tokens.css",
        "/static/css/app.css",
        "/static/js/htmx.min.js",
        "/static/img/plant.png",
    ):
        assert asset in response.text


def test_settings_renders_theme_picker():
    response = _client().get("/settings")
    assert response.status_code == 200
    for theme in ("daylight", "meadow", "dusk"):
        assert f'data-theme-choice="{theme}"' in response.text


def test_section_renders_placeholder():
    response = _client().get("/meals")
    assert response.status_code == 200
    assert "Meals is on its way" in response.text


def test_unknown_section_is_not_found():
    assert _client().get("/does-not-exist").status_code == 404


def test_static_asset_is_served():
    response = _client().get("/static/js/htmx.min.js")
    assert response.status_code == 200


# ---- calendar page ----


def _household() -> HouseholdView:
    members = [
        FamilyMemberView(id=uuid4(), name="Alex", role="parent", birth_date=None),
        FamilyMemberView(id=uuid4(), name="Emma", role="child", birth_date=None),
    ]
    return HouseholdView(
        id=uuid4(),
        name="Morgan",
        timezone="UTC",
        members=members,
        created_at=datetime.now(UTC),
    )


def _occurrence(event_id, day, title, *, start=None, end=None, location=None, participants=()):
    return OccurrenceView(
        event_id=event_id,
        occurrence_date=day,
        title=title,
        location=location,
        participant_ids=list(participants),
        is_all_day=start is None,
        starts_at=datetime.combine(day, start, tzinfo=UTC) if start else None,
        ends_at=datetime.combine(day, end, tzinfo=UTC) if end else None,
    )


def _calendar_client(seeded: bool = True) -> TestClient:
    """Calendar page with stubbed services. Most of the stub schedule is
    pinned to the requested window (the route pads it by PAD_DAYS on both
    sides, so the first visible day is PAD_DAYS after from_date): a weekly
    series on day 0, a one-off and three extra timed entries on day 1, and
    an all-day entry on day 2. "Family photo shoot" is anchored to absolute
    today + 10 so the day-view offset test proves the window really moves.
    """
    app = create_app()
    household = _household() if seeded else None
    emma = household.members[1].id if household else None

    class StubHouseholds(HouseholdService):
        def __init__(self):
            self.household = household

        async def get_household(self, household_id=None):
            return self.household

    class StubCalendar(CalendarService):
        def __init__(self):
            pass

        async def range(self, household_id, from_date, to_date):
            first = from_date + timedelta(days=PAD_DAYS)
            series, one_off = uuid4(), uuid4()
            busy = first + timedelta(days=1)
            return [
                _occurrence(
                    series,
                    first,
                    "Volleyball practice",
                    start=time(16, 0),
                    end=time(17, 30),
                    location="The gym",
                    participants=[emma],
                ),
                _occurrence(
                    series,
                    first + timedelta(days=7),
                    "Volleyball practice",
                    start=time(16, 0),
                    end=time(17, 30),
                    location="The gym",
                    participants=[emma],
                ),
                _occurrence(
                    one_off,
                    busy,
                    "Dentist appointment",
                    start=time(11, 30),
                    end=time(12, 15),
                    location="Dr. Patel",
                    participants=[emma],
                ),
                _occurrence(uuid4(), busy, "Swim class", start=time(9, 0), end=time(10, 0)),
                _occurrence(uuid4(), busy, "Park playdate", start=time(14, 0), end=time(15, 0)),
                _occurrence(uuid4(), busy, "Music lesson", start=time(18, 0), end=time(19, 0)),
                _occurrence(uuid4(), first + timedelta(days=2), "No school — long weekend"),
                _occurrence(
                    uuid4(),
                    datetime.now(UTC).date() + timedelta(days=10),
                    "Family photo shoot",
                ),
            ]

    services = replace(app.state.services, household=StubHouseholds(), calendar=StubCalendar())
    app.dependency_overrides[get_services] = lambda: services
    return TestClient(app)


def test_calendar_month_renders_wall_grid():
    response = _calendar_client().get("/calendar")
    assert response.status_code == 200
    assert "/static/css/calendar.css" in response.text
    assert 'href="/calendar" aria-current="page"' in response.text  # Calendar marked active
    assert response.text.count("cal-cell__num") >= 35  # 5-6 week grid, Monday start
    assert 'cal-chip__time">16:00' in response.text  # compact 24h chip time
    assert "Volleyball practice" in response.text
    assert "(E)" in response.text  # participant initials on the chip
    assert "cal-chip--band" in response.text  # all-day activities as banded chips
    assert "cal-cell__more" in response.text  # day 1 has four timed entries: +1 more


def test_calendar_week_renders_agenda():
    response = _calendar_client().get("/calendar?view=week")
    assert response.status_code == 200
    assert response.text.count("cal-daysect__head") == 7  # Mon..Sun day sections
    assert 'Volleyball practice <span class="cal-repeat"' in response.text  # ↻ on series
    assert "Dentist appointment</span>" in response.text  # one-off carries no ↻
    assert "4:00 PM - 5:30 PM" in response.text  # roomy time range
    assert "avatar-stack" in response.text
    assert "Emma" in response.text
    assert "The gym" in response.text  # location
    assert response.text.count("Nothing planned.") == 4  # Thu..Sun are empty


def test_calendar_day_view_shows_only_that_day():
    client = _calendar_client()
    today = client.get("/calendar?view=day")
    assert today.status_code == 200
    assert "Volleyball practice" in today.text
    assert "Dentist appointment" not in today.text  # one-off lives on the next day
    assert "Nothing planned." not in today.text
    tomorrow = client.get("/calendar?view=day&o=1")
    assert "Volleyball practice" in tomorrow.text  # the stub pins day 0 to the visible day
    assert "Dentist appointment" not in tomorrow.text


def test_calendar_offset_deep_link_reaches_distant_days():
    client = _calendar_client()
    assert "Family photo shoot" not in client.get("/calendar?view=day").text
    future = client.get("/calendar?view=day&o=10")
    assert future.status_code == 200
    assert "Family photo shoot" in future.text  # anchored to today + 10
    assert "Today" in future.text  # today button appears once o != 0


def test_calendar_unknown_view_is_not_found():
    assert _calendar_client().get("/calendar?view=decade").status_code == 404


def test_calendar_without_seeded_household_is_not_found():
    response = _calendar_client(seeded=False).get("/calendar")
    assert response.status_code == 404
    assert "Household not seeded" in response.text
