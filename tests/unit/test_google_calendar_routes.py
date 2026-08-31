from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from nidaro.config import Settings
from nidaro.web.routes import google_calendar as routes


def make_settings(configured=True):
    if configured:
        return Settings(google_client_id="id", google_client_secret="secret")
    return Settings()


class FakeGoogleAccounts:
    def __init__(self):
        self.calls = []

    async def complete_connection(self, household_id, code, *, oauth):
        self.calls.append((household_id, code, oauth))
        return SimpleNamespace(id=uuid4())


class FakeServices:
    def __init__(self, household, accounts):
        class Households:
            async def get_household(self, household_id=None):
                return household

        self.household = Households()
        self.google_accounts = accounts


def request_with_cookie(cookie: str | None) -> Request:
    headers = []
    if cookie is not None:
        headers.append((b"cookie", f"{routes._STATE_COOKIE}={cookie}".encode()))
    return Request(scope={"type": "http", "method": "GET", "headers": headers})


@pytest.mark.anyio
async def test_connect_requires_configuration(monkeypatch):
    monkeypatch.setattr(routes, "get_settings", lambda: make_settings(configured=False))

    with pytest.raises(HTTPException) as excinfo:
        await routes.connect(FakeServices(None, FakeGoogleAccounts()))
    assert excinfo.value.status_code == 503


@pytest.mark.anyio
async def test_connect_needs_a_seeded_household(monkeypatch):
    monkeypatch.setattr(routes, "get_settings", lambda: make_settings())

    with pytest.raises(HTTPException) as excinfo:
        await routes.connect(FakeServices(None, FakeGoogleAccounts()))
    assert excinfo.value.status_code == 404


@pytest.mark.anyio
async def test_connect_redirects_to_google_with_state_cookie(monkeypatch):
    monkeypatch.setattr(routes, "get_settings", lambda: make_settings())

    response = await routes.connect(FakeServices(SimpleNamespace(id=uuid4()), FakeGoogleAccounts()))

    assert response.status_code == 307
    assert response.headers["location"].startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "state=" in response.headers["location"]
    assert routes._STATE_COOKIE in response.headers["set-cookie"]


@pytest.mark.anyio
async def test_callback_rejects_state_mismatch(monkeypatch):
    monkeypatch.setattr(routes, "get_settings", lambda: make_settings())

    with pytest.raises(HTTPException) as excinfo:
        await routes.callback(
            request_with_cookie("cookie-state"),
            code="code",
            state="query-state",
            services=FakeServices(SimpleNamespace(id=uuid4()), FakeGoogleAccounts()),
        )
    assert excinfo.value.status_code == 400


@pytest.mark.anyio
async def test_callback_rejects_google_error(monkeypatch):
    monkeypatch.setattr(routes, "get_settings", lambda: make_settings())

    with pytest.raises(HTTPException) as excinfo:
        await routes.callback(
            request_with_cookie("state-1"),
            code="code",
            state="state-1",
            error="access_denied",
            services=FakeServices(SimpleNamespace(id=uuid4()), FakeGoogleAccounts()),
        )
    assert excinfo.value.status_code == 400
    assert "access_denied" in excinfo.value.detail


@pytest.mark.anyio
async def test_callback_exchanges_and_redirects_to_settings(monkeypatch):
    monkeypatch.setattr(routes, "get_settings", lambda: make_settings())
    accounts = FakeGoogleAccounts()
    household_id = uuid4()

    response = await routes.callback(
        request_with_cookie("state-1"),
        code="the-code",
        state="state-1",
        services=FakeServices(SimpleNamespace(id=household_id), accounts),
    )

    assert response.status_code == 307
    assert response.headers["location"] == "/settings?connected=google-calendar"
    assert "Max-Age=0" in response.headers["set-cookie"]
    ((stored_household, stored_code, _oauth),) = accounts.calls
    assert stored_household == household_id
    assert stored_code == "the-code"
