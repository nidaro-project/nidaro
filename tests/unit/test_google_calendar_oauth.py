from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from nidaro.connectors.google_calendar.oauth import (
    CALENDAR_EVENTS_SCOPE,
    SCOPES,
    GoogleOAuthError,
    GoogleOAuthSettings,
    InvalidGrantError,
    authorization_url,
    exchange_code,
    refresh_access_token,
)

OAUTH = GoogleOAuthSettings(
    client_id="client-id", client_secret="client-secret", redirect_uri="http://localhost:8100/cb"
)


def test_scopes_request_read_and_write_events():
    assert SCOPES == [CALENDAR_EVENTS_SCOPE]
    assert CALENDAR_EVENTS_SCOPE.endswith("/calendar.events")


def test_settings_require_client_id_and_secret():
    from nidaro.config import Settings

    assert GoogleOAuthSettings.from_settings(Settings(google_client_id=None)) is None
    assert (
        GoogleOAuthSettings.from_settings(
            Settings(google_client_id="id", google_client_secret=None)
        )
        is None
    )
    configured = GoogleOAuthSettings.from_settings(
        Settings(google_client_id="id", google_client_secret="secret")
    )
    assert configured is not None
    assert configured.client_id == "id"


def test_authorization_url_requests_offline_access_and_forced_consent():
    url = authorization_url(OAUTH, state="state-123")
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.hostname == "accounts.google.com"
    assert query["response_type"] == ["code"]
    assert query["client_id"] == ["client-id"]
    assert query["redirect_uri"] == ["http://localhost:8100/cb"]
    assert query["scope"] == [CALENDAR_EVENTS_SCOPE]
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]
    assert query["state"] == ["state-123"]


@pytest.mark.anyio
async def test_exchange_code_posts_the_web_server_flow_form():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["form"] = parse_qs(request.content.decode())
        return httpx.Response(
            200,
            json={
                "access_token": "at-1",
                "expires_in": 3600,
                "refresh_token": "rt-1",
                "scope": CALENDAR_EVENTS_SCOPE,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        tokens = await exchange_code(OAUTH, "the-code", http=http)

    assert tokens.access_token == "at-1"
    assert tokens.refresh_token == "rt-1"
    assert seen["form"]["code"] == ["the-code"]
    assert seen["form"]["grant_type"] == ["authorization_code"]
    assert seen["form"]["client_id"] == ["client-id"]
    assert seen["form"]["client_secret"] == ["client-secret"]
    assert seen["form"]["redirect_uri"] == ["http://localhost:8100/cb"]


@pytest.mark.anyio
async def test_exchange_without_refresh_token_means_google_still_holds_it():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "at-1", "expires_in": 3600})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        tokens = await exchange_code(OAUTH, "the-code", http=http)

    assert tokens.refresh_token is None


@pytest.mark.anyio
async def test_invalid_grant_means_reconnect_not_retry():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    transport = httpx.MockTransport(handler)
    with pytest.raises(InvalidGrantError, match="reconnected"):
        async with httpx.AsyncClient(transport=transport) as http:
            await refresh_access_token(OAUTH, "dead-token", http=http)


@pytest.mark.anyio
async def test_other_token_errors_surface_verbatim():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "backend_error"})

    transport = httpx.MockTransport(handler)
    with pytest.raises(GoogleOAuthError, match="500"):
        async with httpx.AsyncClient(transport=transport) as http:
            await refresh_access_token(OAUTH, "token", http=http)
