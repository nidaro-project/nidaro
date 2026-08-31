import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, unquote, urlparse

import httpx
import pytest

from nidaro.connectors.base import StaleCursorError
from nidaro.connectors.google_calendar.accounts import GoogleAccountCredentials
from nidaro.connectors.google_calendar.client import (
    GoogleApiError,
    GoogleCalendarClient,
    GoogleNotConfigured,
    GooglePreconditionFailedError,
)
from nidaro.connectors.google_calendar.oauth import (
    GoogleOAuthSettings,
    InvalidGrantError,
)

OAUTH = GoogleOAuthSettings(
    client_id="client-id", client_secret="client-secret", redirect_uri="http://localhost/cb"
)
ACCOUNT = GoogleAccountCredentials(
    email="ada@example.com",
    calendar_id="ada@example.com",
    scopes=["https://www.googleapis.com/auth/calendar.events"],
    refresh_token="refresh-token-1",
)


class GoogleReplay:
    """Fixture replay: routes by (method, path), records everything seen."""

    def __init__(self, routes: dict[tuple[str, str], object]):
        self.routes = routes
        self.requests: list[httpx.Request] = []
        self.token_posts = 0

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            parsed = urlparse(str(request.url))
            key = (request.method, unquote(parsed.path))
            if request.method == "POST" and parsed.path == "/token":
                self.token_posts += 1
                return httpx.Response(
                    200,
                    json={
                        "access_token": f"access-token-{self.token_posts}",
                        "expires_in": 3600,
                        "scope": "https://www.googleapis.com/auth/calendar.events",
                    },
                )
            route = self.routes.get(key)
            if route is None:
                return httpx.Response(404, json={"error": "unrouted"})
            if isinstance(route, httpx.Response):
                return route
            return httpx.Response(200, json=route)

        return httpx.MockTransport(handler)

    def query_of(self, request: httpx.Request) -> dict[str, list[str]]:
        return parse_qs(urlparse(str(request.url)).query)

    def form_of(self, request: httpx.Request) -> dict[str, list[str]]:
        return parse_qs(request.content.decode())

    def bearer_of(self, request: httpx.Request) -> str:
        return request.headers["Authorization"].removeprefix("Bearer ")


def make_client(replay: GoogleReplay, *, oauth: GoogleOAuthSettings | None = OAUTH, clock=None):
    return GoogleCalendarClient(
        oauth,
        transport=replay.transport(),
        clock=clock or (lambda: datetime(2026, 9, 1, 12, 0, tzinfo=UTC)),
    )


@pytest.mark.anyio
async def test_full_sync_sends_time_min_and_single_events():
    replay = GoogleReplay({("GET", "/calendar/v3/calendars/ada@example.com/events"): {"items": []}})
    client = make_client(replay)

    await client.list_events(ACCOUNT, time_min=datetime(2025, 9, 1, tzinfo=UTC))

    request = replay.requests[-1]
    query = replay.query_of(request)
    assert query["singleEvents"] == ["true"]
    assert query["timeMin"] == ["2025-09-01T00:00:00+00:00"]
    assert query["maxResults"] == ["2500"]
    assert "syncToken" not in query


@pytest.mark.anyio
async def test_incremental_sync_sends_sync_token_without_time_bounds():
    replay = GoogleReplay(
        {
            (
                "GET",
                "/calendar/v3/calendars/ada@example.com/events",
            ): {"items": [{"id": "evt1", "status": "confirmed"}], "nextSyncToken": "tok-2"}
        }
    )
    client = make_client(replay)

    page = await client.list_events(ACCOUNT, sync_token="tok-1")

    query = replay.query_of(replay.requests[-1])
    assert query["syncToken"] == ["tok-1"]
    assert "timeMin" not in query
    assert page.next_sync_token == "tok-2"
    assert page.events[0]["id"] == "evt1"


@pytest.mark.anyio
async def test_pagination_passes_page_token():
    replay = GoogleReplay({("GET", "/calendar/v3/calendars/ada@example.com/events"): {"items": []}})
    client = make_client(replay)

    await client.list_events(ACCOUNT, sync_token="tok-1", page_token="page-7")

    assert replay.query_of(replay.requests[-1])["pageToken"] == ["page-7"]


@pytest.mark.anyio
async def test_gone_raises_stale_cursor():
    replay = GoogleReplay(
        {("GET", "/calendar/v3/calendars/ada@example.com/events"): httpx.Response(410, json={})}
    )
    client = make_client(replay)

    with pytest.raises(StaleCursorError, match="410"):
        await client.list_events(ACCOUNT, sync_token="expired")


@pytest.mark.anyio
async def test_refreshes_token_then_caches_it():
    replay = GoogleReplay({("GET", "/calendar/v3/calendars/ada@example.com/events"): {"items": []}})
    client = make_client(replay)

    await client.list_events(ACCOUNT)
    await client.list_events(ACCOUNT)

    assert replay.token_posts == 1
    token_request, *event_requests = replay.requests
    assert replay.form_of(token_request).get("refresh_token") == ["refresh-token-1"]
    assert replay.form_of(token_request).get("grant_type") == ["refresh_token"]
    assert replay.bearer_of(event_requests[0]) == "access-token-1"
    assert replay.bearer_of(event_requests[-1]) == "access-token-1"


@pytest.mark.anyio
async def test_expired_cache_token_is_refreshed_again():
    replay = GoogleReplay({("GET", "/calendar/v3/calendars/ada@example.com/events"): {"items": []}})
    now = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    client = make_client(replay, clock=lambda: now)

    await client.list_events(ACCOUNT)
    now = now + timedelta(hours=2)
    await client.list_events(ACCOUNT)

    assert replay.token_posts == 2


@pytest.mark.anyio
async def test_without_oauth_settings_google_is_not_called():
    replay = GoogleReplay({})
    client = make_client(replay, oauth=None)

    with pytest.raises(GoogleNotConfigured, match="NIDARO_GOOGLE"):
        await client.list_events(ACCOUNT)
    assert replay.requests == []


@pytest.mark.anyio
async def test_invalid_grant_maps_to_reconnect_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    client = GoogleCalendarClient(OAUTH, transport=httpx.MockTransport(handler))

    with pytest.raises(InvalidGrantError, match="reconnected"):
        await client.list_events(ACCOUNT)


@pytest.mark.anyio
async def test_other_api_errors_surface_verbatim():
    replay = GoogleReplay(
        {
            ("GET", "/calendar/v3/calendars/ada@example.com/events"): httpx.Response(
                403, json={"error": "quota"}
            )
        }
    )
    client = make_client(replay)

    with pytest.raises(GoogleApiError, match="403"):
        await client.list_events(ACCOUNT)


@pytest.mark.anyio
async def test_primary_calendar_lookup_identifies_the_consenting_account():
    replay = GoogleReplay(
        {("GET", "/calendar/v3/users/me/calendarList/primary"): {"id": "ada@example.com"}}
    )
    client = make_client(replay)

    calendar = await client.primary_calendar_for_token("refresh-token-1")

    assert calendar["id"] == "ada@example.com"
    assert replay.requests[-1].url.path == "/calendar/v3/users/me/calendarList/primary"


@pytest.mark.anyio
async def test_insert_send_updates_only_when_asked():
    replay = GoogleReplay(
        {("POST", "/calendar/v3/calendars/ada@example.com/events"): {"id": "evt9"}}
    )
    client = make_client(replay)

    await client.insert_event(ACCOUNT, {"summary": "Dentist"})
    body = json.loads(replay.requests[-1].content)
    assert body == {"summary": "Dentist"}
    assert "sendUpdates" not in replay.query_of(replay.requests[-1])

    await client.insert_event(ACCOUNT, {"summary": "Party"}, send_updates="all")
    assert replay.query_of(replay.requests[-1])["sendUpdates"] == ["all"]


@pytest.mark.anyio
async def test_update_sends_if_match_and_maps_412():
    replay = GoogleReplay(
        {
            ("PUT", "/calendar/v3/calendars/ada@example.com/events/evt1"): httpx.Response(
                412, json={"error": "etag mismatch"}
            )
        }
    )
    client = make_client(replay)

    with pytest.raises(GooglePreconditionFailedError, match="412"):
        await client.update_event(ACCOUNT, "evt1", {"summary": "moved"}, if_match='"etag/1"')

    assert replay.requests[-1].headers["If-Match"] == '"etag/1"'


@pytest.mark.anyio
async def test_delete_is_idempotent_on_already_gone():
    replay = GoogleReplay(
        {("DELETE", "/calendar/v3/calendars/ada@example.com/events/evt1"): httpx.Response(410)}
    )
    client = make_client(replay)

    await client.delete_event(ACCOUNT, "evt1")
    assert replay.requests[-1].method == "DELETE"
