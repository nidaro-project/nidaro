from datetime import UTC, datetime
from uuid import uuid4

import pytest

from nidaro.calendar.models import Event
from nidaro.calendar.repository import CalendarRepository
from nidaro.calendar.schemas import CreateEventRequest, EventView
from nidaro.calendar.service import CalendarService
from nidaro.connectors.google_calendar.accounts import (
    GoogleAccountCredentials,
    GoogleCalendarAccountService,
)
from nidaro.connectors.google_calendar.client import (
    GoogleCalendarClient,
    GooglePreconditionFailedError,
)
from nidaro.connectors.google_calendar.mapping import MARKER_KEY, UpdateGoogleEventFields
from nidaro.connectors.google_calendar.writes import (
    GoogleCalendarWriteError,
    GoogleCalendarWriteService,
    GoogleConflictError,
    NoGoogleAccountError,
)
from nidaro.db.types import new_uuid, utc_now
from nidaro.household.models import Household
from nidaro.household.repository import HouseholdRepository
from nidaro.household.schemas import HouseholdView
from nidaro.household.service import HouseholdService

HOUSEHOLD_ID = uuid4()
ADA = GoogleAccountCredentials(
    email="ada@example.com",
    calendar_id="primary",
    scopes=["https://www.googleapis.com/auth/calendar.events"],
    refresh_token="rt-ada",
)


def google_event_json(event_id="nidaroabc123", **overrides):
    event = {
        "id": event_id,
        "status": "confirmed",
        "summary": "Swim class",
        "start": {"dateTime": "2026-09-03T17:00:00+02:00"},
        "end": {"dateTime": "2026-09-03T18:00:00+02:00"},
        "etag": '"etag/1"',
        "extendedProperties": {"private": {MARKER_KEY: "1"}},
    }
    event.update(overrides)
    return {key: value for key, value in event.items() if value is not None}


class FakeAccounts(GoogleCalendarAccountService):
    def __init__(self, accounts):
        self.accounts = list(accounts)

    async def credentials_for_household(self, household_id):
        return list(self.accounts)


class FakeClient(GoogleCalendarClient):
    """Records calls; one scripted response per (method, path-suffix)."""

    def __init__(self, responses=None):
        self.calls = []
        self.responses = dict(responses or {})

    def script(self, method, path_suffix, value):
        self.responses[(method, path_suffix)] = value

    def pop(self, method, path_suffix):
        self.calls.append((method, path_suffix))
        value = self.responses[(method, path_suffix)]
        if isinstance(value, Exception):
            raise value
        return value

    async def insert_event(self, account, body, *, send_updates=None):
        self.last_insert = {"body": body, "send_updates": send_updates}
        return self.pop("POST", "/events")

    async def get_event(self, account, event_id):
        return self.pop("GET", f"/events/{event_id}")

    async def update_event(self, account, event_id, body, *, if_match=None):
        self.last_update = {"body": body, "if_match": if_match}
        return self.pop("PUT", f"/events/{event_id}")

    async def delete_event(self, account, event_id):
        return self.pop("DELETE", f"/events/{event_id}")


class FakeMirrorRepository(CalendarRepository):
    def __init__(self):
        self.events = []

    def find(self, household_id, connector, external_id):
        return next(
            (
                event
                for event in self.events
                if (
                    event.household_id,
                    event.external_connector,
                    event.external_id,
                )
                == (household_id, connector, external_id)
            ),
            None,
        )

    async def get_by_external_identity(self, household_id, connector, external_id):
        return self.find(household_id, connector, external_id)

    async def upsert_mirror(self, household_id, connector, external_id, fields):
        event = self.find(household_id, connector, external_id)
        if event is None:
            event = Event(
                id=new_uuid(),
                household_id=household_id,
                external_connector=connector,
                external_id=external_id,
                status="scheduled",
                created_at=utc_now(),
                updated_at=utc_now(),
                **fields,
            )
            self.events.append(event)
        else:
            for name, value in fields.items():
                setattr(event, name, value)
        return event

    async def remove_mirror(self, household_id, connector, external_id):
        event = self.find(household_id, connector, external_id)
        if event is None:
            return False
        self.events.remove(event)
        return True


class FakeHouseholdRepository(HouseholdRepository):
    def __init__(self):
        pass

    async def get(self, household_id=None):
        return Household(
            id=new_uuid(),
            name="Home",
            timezone="Europe/Prague",
            created_at=utc_now(),
            updated_at=utc_now(),
        )


class FakeHouseholds(HouseholdService):
    def __init__(self, timezone="Europe/Prague"):
        self.timezone = timezone

    async def get_household(self, household_id=None):
        return HouseholdView(
            id=HOUSEHOLD_ID,
            name="Home",
            timezone=self.timezone,
            created_at=datetime.now(UTC),
        )


def make_service(accounts=None, client=None):
    mirror_repository = FakeMirrorRepository()
    calendar = CalendarService(mirror_repository, FakeHouseholdRepository())
    service = GoogleCalendarWriteService(
        accounts if accounts is not None else FakeAccounts([ADA]),
        client if client is not None else FakeClient(),
        calendar,
        FakeHouseholds(),
    )
    return service, mirror_repository


def create_request(**overrides):
    # Naive times on purpose: the write path pins them to the household tz.
    fields = {
        "household_id": HOUSEHOLD_ID,
        "title": "Swim class",
        "starts_at": datetime(2026, 9, 3, 17, 0),
        "ends_at": datetime(2026, 9, 3, 18, 0),
    }
    fields.update(overrides)
    return CreateEventRequest(**fields)


@pytest.mark.anyio
async def test_create_posts_marker_and_lands_the_mirror_immediately():
    client = FakeClient({("POST", "/events"): google_event_json()})
    service, mirrors = make_service(client=client)

    view = await service.create_event(HOUSEHOLD_ID, create_request())

    insert = client.last_insert
    assert insert["send_updates"] is None
    assert insert["body"]["summary"] == "Swim class"
    assert insert["body"]["id"].startswith("nidaro")
    assert insert["body"]["extendedProperties"]["private"][MARKER_KEY] == "1"
    assert insert["body"]["start"] == {"dateTime": "2026-09-03T17:00:00+02:00"}
    assert isinstance(view, EventView)
    (event,) = mirrors.events
    assert event.external_connector == "google_calendar"
    assert event.external_id == f"ada@example.com/primary/{google_event_json()['id']}"


@pytest.mark.anyio
async def test_create_with_attendees_sends_updates_all():
    client = FakeClient({("POST", "/events"): google_event_json()})
    service, _ = make_service(client=client)

    await service.create_event(HOUSEHOLD_ID, create_request(), attendees=["ben@example.com"])

    insert = client.last_insert
    assert insert["send_updates"] == "all"
    assert insert["body"]["attendees"] == [{"email": "ben@example.com"}]


@pytest.mark.anyio
async def test_create_refuses_recurring_writes_for_now():
    service, mirrors = make_service()

    with pytest.raises(GoogleCalendarWriteError, match="recurring"):
        await service.create_event(HOUSEHOLD_ID, create_request(recurrence_weekdays=[0, 2]))
    assert mirrors.events == []


@pytest.mark.anyio
async def test_create_without_connected_account_fails_loudly():
    service, _ = make_service(accounts=FakeAccounts([]))

    with pytest.raises(NoGoogleAccountError, match="no Google account"):
        await service.create_event(HOUSEHOLD_ID, create_request())


@pytest.mark.anyio
async def test_update_gets_merges_and_puts_with_if_match():
    client = FakeClient(
        {
            ("GET", "/events/nidaroabc123"): google_event_json(summary="Old title"),
            ("PUT", "/events/nidaroabc123"): google_event_json(summary="New title"),
        }
    )
    service, mirrors = make_service(client=client)

    view = await service.update_event(
        HOUSEHOLD_ID,
        "ada@example.com/primary/nidaroabc123",
        UpdateGoogleEventFields(title="New title"),
    )

    assert client.last_update["if_match"] == '"etag/1"'
    assert client.last_update["body"]["summary"] == "New title"
    assert view.title == "New title"
    (event,) = mirrors.events
    assert event.title == "New title"


@pytest.mark.anyio
async def test_update_conflict_surfaces_instead_of_clobbering():
    client = FakeClient(
        {
            ("GET", "/events/nidaroabc123"): google_event_json(),
            ("PUT", "/events/nidaroabc123"): GooglePreconditionFailedError(
                "changed since read (412)"
            ),
        }
    )
    service, _ = make_service(client=client)

    with pytest.raises(GoogleConflictError, match="412"):
        await service.update_event(
            HOUSEHOLD_ID,
            "ada@example.com/primary/nidaroabc123",
            UpdateGoogleEventFields(title="New title"),
        )


@pytest.mark.anyio
async def test_update_for_foreign_account_is_refused():
    service, _ = make_service(accounts=FakeAccounts([ADA]))

    with pytest.raises(NoGoogleAccountError, match="matches"):
        await service.update_event(
            HOUSEHOLD_ID,
            "mallory@example.com/primary/nidaroabc123",
            UpdateGoogleEventFields(title="?"),
        )


@pytest.mark.anyio
async def test_update_with_malformed_external_id_is_refused():
    service, _ = make_service()

    with pytest.raises(ValueError, match="external id"):
        await service.update_event(HOUSEHOLD_ID, "not-an-id", UpdateGoogleEventFields(title="?"))


@pytest.mark.anyio
async def test_delete_removes_google_event_and_the_mirror():
    client = FakeClient(
        {
            ("POST", "/events"): google_event_json(),
            ("DELETE", "/events/nidaroabc123"): None,
        }
    )
    service, mirrors = make_service(client=client)
    await service.create_event(HOUSEHOLD_ID, create_request())
    assert len(mirrors.events) == 1

    removed = await service.delete_event(HOUSEHOLD_ID, "ada@example.com/primary/nidaroabc123")

    assert removed is True
    assert mirrors.events == []
    assert client.calls[-1] == ("DELETE", "/events/nidaroabc123")


@pytest.mark.anyio
async def test_delete_without_mirror_returns_false():
    client = FakeClient({("DELETE", "/events/nidarodeadbeef"): None})
    service, _ = make_service(client=client)

    assert (
        await service.delete_event(HOUSEHOLD_ID, "ada@example.com/primary/nidarodeadbeef") is False
    )
