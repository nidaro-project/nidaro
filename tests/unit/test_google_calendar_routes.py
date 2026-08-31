"""Google Calendar OAuth route tests: gating, CSRF state, callback wiring.

Real app + FastAPI dependency override (house pattern); the OAuth exchange
itself lives behind GoogleCalendarAccountService.complete_connection and is
unit-tested against fixture replays in test_google_calendar_accounts.py.
"""

from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from nidaro.app import create_app
from nidaro.config import Settings
from nidaro.container import ApplicationServices
from nidaro.db.types import utc_now
from nidaro.household.models import Household
from nidaro.household.repository import HouseholdRepository
from nidaro.household.service import HouseholdService
from nidaro.web.dependencies import get_services
from nidaro.web.routes import google_calendar as routes


class FakeHouseholdRepository(HouseholdRepository):
    def __init__(self, household=None):
        self.household = household

    async def get(self, household_id=None):
        return self.household


class FakeGoogleAccounts:
    def __init__(self):
        self.calls = []

    async def complete_connection(self, household_id, code, *, oauth):
        self.calls.append((household_id, code, oauth))
        return SimpleAccount()


class SimpleAccount:
    id = uuid4()


def _household():
    return Household(
        id=uuid4(),
        name="Morgan",
        timezone="Europe/Prague",
        created_at=utc_now(),
        updated_at=utc_now(),
    )


def _services(household, accounts):
    base = ApplicationServices.build(async_sessionmaker())
    return replace(
        base,
        household=HouseholdService(FakeHouseholdRepository(household)),
        google_accounts=accounts,
    )


def _client(services):
    app = create_app()
    app.dependency_overrides[get_services] = lambda: services
    return TestClient(app)


@pytest.fixture
def configured_settings(monkeypatch):
    settings = Settings(google_client_id="id", google_client_secret="secret")
    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    return settings


def test_connect_requires_configuration(monkeypatch):
    monkeypatch.setattr(routes, "get_settings", lambda: Settings())
    client = _client(_services(_household(), FakeGoogleAccounts()))

    response = client.get("/api/v1/connectors/google-calendar/connect")

    assert response.status_code == 503
    assert "NIDARO_GOOGLE_CLIENT_ID" in response.json()["detail"]


def test_connect_needs_a_seeded_household(configured_settings):
    client = _client(_services(None, FakeGoogleAccounts()))

    response = client.get("/api/v1/connectors/google-calendar/connect")

    assert response.status_code == 404


def test_connect_redirects_to_google_with_state_cookie(configured_settings):
    client = _client(_services(_household(), FakeGoogleAccounts()))

    response = client.get("/api/v1/connectors/google-calendar/connect", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"].startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "state=" in response.headers["location"]
    assert routes._STATE_COOKIE in response.headers["set-cookie"]


def test_callback_rejects_state_mismatch(configured_settings):
    client = _client(_services(_household(), FakeGoogleAccounts()))

    response = client.get("/api/v1/connectors/google-calendar/callback?code=the-code&state=wrong")

    assert response.status_code == 400


def test_callback_rejects_google_error(configured_settings):
    client = _client(_services(_household(), FakeGoogleAccounts()))
    client.get("/api/v1/connectors/google-calendar/connect")
    state = client.cookies[routes._STATE_COOKIE]

    response = client.get(
        f"/api/v1/connectors/google-calendar/callback?code=x&state={state}&error=access_denied"
    )

    assert response.status_code == 400
    assert "access_denied" in response.json()["detail"]


def test_callback_exchanges_and_redirects_to_settings(configured_settings):
    accounts = FakeGoogleAccounts()
    household = _household()
    client = _client(_services(household, accounts))
    client.get("/api/v1/connectors/google-calendar/connect")
    state = client.cookies[routes._STATE_COOKIE]

    response = client.get(
        f"/api/v1/connectors/google-calendar/callback?code=the-code&state={state}",
        follow_redirects=False,
    )

    assert response.status_code == 307
    assert response.headers["location"] == "/settings?connected=google-calendar"
    ((stored_household, stored_code, _oauth),) = accounts.calls
    assert stored_household == household.id
    assert stored_code == "the-code"
