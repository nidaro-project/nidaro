import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from nidaro.connectors.base import StaleCursorError
from nidaro.connectors.google_calendar.accounts import (
    GoogleAccountCredentials,
    GoogleCalendarAccountService,
)
from nidaro.connectors.google_calendar.client import (
    EventsPage,
    GoogleApiError,
    GoogleCalendarClient,
)
from nidaro.connectors.google_calendar.connector import (
    GoogleCalendarConnector,
    parse_cursor,
)
from nidaro.connectors.google_calendar.oauth import GoogleOAuthSettings, InvalidGrantError
from nidaro.connectors.models import ConnectorContext

CONTEXT = ConnectorContext(household_id=str(uuid4()), timezone="Europe/Prague")

OAUTH_SETTINGS = GoogleOAuthSettings(
    client_id="id", client_secret="secret", redirect_uri="http://localhost/cb"
)


def account(email, calendar_id="primary"):
    return GoogleAccountCredentials(
        email=email,
        calendar_id=calendar_id,
        scopes=["https://www.googleapis.com/auth/calendar.events"],
        refresh_token=f"rt-{email}",
    )


def google_event(event_id, *, status="confirmed", summary="Dentist"):
    event = {"id": event_id, "status": status, "summary": summary}
    if status == "confirmed":
        event["start"] = {"dateTime": "2026-09-03T17:00:00+02:00"}
        event["end"] = {"dateTime": "2026-09-03T18:00:00+02:00"}
    return event


class FakeAccounts(GoogleCalendarAccountService):
    def __init__(self, accounts):
        self.accounts = list(accounts)
        self.asked_households = []

    async def credentials_for_household(self, household_id):
        self.asked_households.append(household_id)
        return list(self.accounts)


class FakeClient(GoogleCalendarClient):
    """Replays queued pages per (email, sync_token-or-full); can raise."""

    def __init__(self):
        self.script: list[tuple[str, str | None, list[EventsPage] | Exception]] = []
        self.calls = []

    def queue(self, email, sync_token, pages):
        self.script.append((email, sync_token, pages))

    def fails(self, email, sync_token, error):
        self.script.append((email, sync_token, error))

    def next_script_entry(self, email, sync_token):
        for index, (script_email, script_token, _pages) in enumerate(self.script):
            if script_email == email and script_token == sync_token:
                return self.script.pop(index)
        raise AssertionError(f"no scripted response for {email} sync_token={sync_token}")

    async def list_events(self, acct, *, sync_token=None, page_token=None, time_min=None):
        self.calls.append(
            {
                "email": acct.email,
                "calendar_id": acct.calendar_id,
                "sync_token": sync_token,
                "page_token": page_token,
                "time_min": time_min,
            }
        )
        entry = self.next_script_entry(acct.email, "incremental" if sync_token else "full")
        if isinstance(entry[2], Exception):
            raise entry[2]
        pages = list(entry[2])
        page = pages.pop(0)
        if pages:
            # Keep the entry queued so the next pageToken call finds it.
            self.script.append((entry[0], entry[1], pages))
            return EventsPage(events=page.events, next_page_token="page-2", next_sync_token=None)
        return page

    def page(self, events, sync_token):
        return EventsPage(events=events, next_sync_token=sync_token)


def make_connector(accounts, client):
    return GoogleCalendarConnector(accounts, client)


def cursor_state(**accounts_states):
    return json.dumps(
        {
            "accounts": {
                email: {"calendar_id": calendar_id, "sync_token": sync_token}
                for email, (calendar_id, sync_token) in accounts_states.items()
            }
        }
    )


@pytest.mark.anyio
async def test_first_sync_runs_full_per_account_and_cursors_both():
    accounts = FakeAccounts([account("ada@example.com"), account("ben@example.com", "work")])
    client = FakeClient()
    client.queue("ada@example.com", "full", [client.page([google_event("a1")], "tok-ada")])
    client.queue("ben@example.com", "full", [client.page([google_event("b1")], "tok-ben")])

    result = await make_connector(accounts, client).sync(CONTEXT, None)

    assert [record.external_id for record in result.records] == [
        "ada@example.com/primary/a1",
        "ben@example.com/work/b1",
    ]
    state = parse_cursor(result.next_cursor)
    assert state.accounts["ada@example.com"].sync_token == "tok-ada"
    assert state.accounts["ben@example.com"].sync_token == "tok-ben"
    # Full syncs are bounded: nothing older than a year is pulled.
    for call in client.calls:
        assert call["sync_token"] is None
        assert call["time_min"] > datetime.now(UTC) - timedelta(days=366)


@pytest.mark.anyio
async def test_incremental_sync_replays_each_accounts_sync_token():
    accounts = FakeAccounts([account("ada@example.com"), account("ben@example.com", "work")])
    client = FakeClient()
    client.queue("ada@example.com", "incremental", [client.page([], "tok-ada-2")])
    client.queue("ben@example.com", "incremental", [client.page([], "tok-ben-2")])
    stored = cursor_state(
        **{"ada@example.com": ("primary", "tok-ada"), "ben@example.com": ("work", "tok-ben")}
    )

    result = await make_connector(accounts, client).sync(CONTEXT, stored)

    assert result.records == []
    assert {call["sync_token"] for call in client.calls} == {"tok-ada", "tok-ben"}
    assert all(call["time_min"] is None for call in client.calls)
    state = parse_cursor(result.next_cursor)
    assert state.accounts["ada@example.com"].sync_token == "tok-ada-2"


@pytest.mark.anyio
async def test_calendar_id_change_forces_full_sync_for_that_account():
    accounts = FakeAccounts([account("ada@example.com", "family-shared")])
    client = FakeClient()
    client.queue("ada@example.com", "full", [client.page([], "tok-new")])

    result = await make_connector(accounts, client).sync(
        CONTEXT, cursor_state(**{"ada@example.com": ("primary", "tok-old")})
    )

    assert client.calls[0]["calendar_id"] == "family-shared"
    assert client.calls[0]["time_min"] is not None
    assert parse_cursor(result.next_cursor).accounts["ada@example.com"].sync_token == "tok-new"


@pytest.mark.anyio
async def test_gone_falls_back_to_full_sync_within_the_run():
    accounts = FakeAccounts([account("ada@example.com")])
    client = FakeClient()
    client.fails("ada@example.com", "incremental", StaleCursorError("410 GONE"))
    client.queue("ada@example.com", "full", [client.page([google_event("a1")], "tok-fresh")])

    result = await make_connector(accounts, client).sync(
        CONTEXT, cursor_state(**{"ada@example.com": ("primary", "tok-expired")})
    )

    assert [record.external_id for record in result.records] == ["ada@example.com/primary/a1"]
    assert parse_cursor(result.next_cursor).accounts["ada@example.com"].sync_token == "tok-fresh"


@pytest.mark.anyio
async def test_dead_refresh_token_skips_only_that_account():
    accounts = FakeAccounts([account("ada@example.com"), account("ben@example.com")])
    client = FakeClient()
    client.queue("ada@example.com", "full", [client.page([google_event("a1")], "tok-ada")])
    client.fails("ben@example.com", "full", InvalidGrantError("invalid_grant"))

    result = await make_connector(accounts, client).sync(CONTEXT, None)

    assert [record.external_id for record in result.records] == ["ada@example.com/primary/a1"]
    state = parse_cursor(result.next_cursor)
    assert "ben@example.com" not in state.accounts
    assert state.accounts["ada@example.com"].sync_token == "tok-ada"


@pytest.mark.anyio
async def test_no_accounts_syncs_nothing_and_keeps_stored_cursor():
    result = await make_connector(FakeAccounts([]), FakeClient()).sync(CONTEXT, "whatever")

    assert result.records == []
    assert result.next_cursor is None


@pytest.mark.anyio
async def test_corrupt_stored_cursor_means_full_resync():
    accounts = FakeAccounts([account("ada@example.com")])
    client = FakeClient()
    client.queue("ada@example.com", "full", [client.page([], "tok-new")])

    result = await make_connector(accounts, client).sync(CONTEXT, "{not json")

    assert client.calls[0]["sync_token"] is None
    assert parse_cursor(result.next_cursor).accounts["ada@example.com"].sync_token == "tok-new"


@pytest.mark.anyio
async def test_pagination_drains_pages_before_accepting_the_sync_token():
    accounts = FakeAccounts([account("ada@example.com")])
    client = FakeClient()
    first = EventsPage(
        events=[google_event("a1"), google_event("a2")],
        next_page_token="page-2",
        next_sync_token=None,
    )
    last = EventsPage(events=[google_event("a3")], next_sync_token="tok-final")
    client.queue("ada@example.com", "full", [first, last])

    result = await make_connector(accounts, client).sync(CONTEXT, None)

    assert len(result.records) == 3
    assert [call["page_token"] for call in client.calls] == [None, "page-2"]
    # Every page of an incremental run must repeat the same sync token.
    assert parse_cursor(result.next_cursor).accounts["ada@example.com"].sync_token == "tok-final"


@pytest.mark.anyio
async def test_missing_final_sync_token_is_refused():
    accounts = FakeAccounts([account("ada@example.com")])
    client = FakeClient()
    client.queue(
        "ada@example.com",
        "full",
        [EventsPage(events=[google_event("a1")], next_sync_token=None)],
    )

    with pytest.raises(GoogleApiError, match="sync token"):
        await make_connector(accounts, client).sync(CONTEXT, None)


def test_parse_cursor_handles_none_and_garbage():
    assert parse_cursor(None).accounts == {}
    assert parse_cursor("garbage").accounts == {}
