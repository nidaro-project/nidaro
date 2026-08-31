"""Gatherer wiring: registry registration, dispatch selection, refresh route.

Real services over fake repositories (house pattern); the school HTTP layer is
never touched — connector syncs go through fakes that record the calls.
"""

from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import nidaro.jobs.tasks as tasks
from nidaro.app import create_app
from nidaro.connectors.base import StaleCursorError
from nidaro.connectors.models import ConnectorConfig, ConnectorContext, SyncResult
from nidaro.connectors.registry import ConnectorRegistry
from nidaro.connectors.service import ConnectorConfigService, ConnectorService
from nidaro.container import ApplicationServices
from nidaro.db.types import utc_now
from nidaro.household.repository import HouseholdRepository
from nidaro.household.service import HouseholdService
from nidaro.web.dependencies import get_services


class RecordingConnector:
    name = "bakalari"

    def __init__(self, error: Exception | None = None):
        self.error = error
        self.calls: list[tuple[ConnectorContext, str | None]] = []

    async def sync(self, context: ConnectorContext, cursor: str | None) -> SyncResult:
        self.calls.append((context, cursor))
        if self.error is not None:
            raise self.error
        return SyncResult(records=[])


class FakeCursorRepository:
    async def get(self, household_id, connector):
        return None

    async def save(self, household_id, connector, cursor):
        raise StaleCursorError("not used here")

    async def clear(self, household_id, connector):
        return True


class FakeConfigRepository:
    def __init__(self, rows: list[ConnectorConfig]):
        self.rows = rows

    async def get(self, household_id, connector):
        return next((row for row in self.rows if row.connector == connector), None)

    async def upsert(
        self, household_id, connector, *, enabled, credential_names, trigger_word, poll_seconds
    ):
        raise StaleCursorError("not used here")

    async def enabled_for_household(self, household_id):
        return [row for row in self.rows if row.household_id == household_id]

    async def all_enabled(self) -> list[ConnectorConfig]:
        return self.rows

    async def stamp_synced(self, household_id, connector, at):
        return True


def config(connector: str, *, synced: timedelta | None) -> ConnectorConfig:
    return ConnectorConfig(
        household_id=uuid4(),
        connector=connector,
        enabled=True,
        credential_names=[],
        poll_seconds=900,
        last_synced_at=None if synced is None else utc_now() - synced,
    )


def base_services() -> ApplicationServices:
    return ApplicationServices.build(async_sessionmaker())


def test_bakalari_connector_is_registered():
    services = base_services()

    assert sorted(services.connectors.registry.names()) == [
        "bakalari",
        "google_calendar",
        "icloud_calendar",
        "whatsapp",
    ]


@pytest.mark.anyio
async def test_due_dispatch_skips_unregistered_and_fresh_configs():
    base = base_services()
    connector = RecordingConnector()
    registry = ConnectorRegistry()
    registry.register(connector)
    due = config("bakalari", synced=timedelta(hours=2))
    fresh = config("bakalari", synced=timedelta(seconds=10))
    unregistered = config("whatsapp", synced=None)
    services = replace(
        base,
        connectors=ConnectorService(registry, FakeCursorRepository()),
        connector_configs=ConnectorConfigService(FakeConfigRepository([due, fresh, unregistered])),
    )

    selected = await tasks.due_registered(services)

    assert [row.household_id for row in selected] == [due.household_id]


@pytest.mark.anyio
async def test_sync_household_now_builds_context_and_counts_records():
    base = base_services()
    household_id = uuid4()
    connector = RecordingConnector()
    registry = ConnectorRegistry()
    registry.register(connector)
    services = replace(
        base,
        household=HouseholdService(FakeHouseholdRepository(_household_with_id(household_id))),
        connectors=ConnectorService(registry, FakeCursorRepository()),
    )

    result = await tasks.sync_household_now(services, "bakalari", str(household_id))

    assert result["status"] == "ok"
    assert result["records"] == 0
    context, _cursor = connector.calls[0]
    assert context.household_id == str(household_id)
    assert context.timezone == "Europe/Prague"


@pytest.mark.anyio
async def test_sync_household_now_reports_missing_household():
    base = base_services()
    services = replace(base, household=HouseholdService(FakeHouseholdRepository(None)))

    result = await tasks.sync_household_now(services, "bakalari", str(uuid4()))

    assert result["status"] == "household_not_found"


class FakeHouseholdRepository(HouseholdRepository):
    def __init__(self, household):
        self.household = household

    async def get(self, household_id=None):
        return self.household


def _client(services: ApplicationServices) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_services] = lambda: services
    return TestClient(app)


def _household(household_id=None):
    from nidaro.household.models import Household

    return Household(
        id=household_id or uuid4(),
        name="Morgan",
        timezone="Europe/Prague",
        created_at=utc_now(),
        updated_at=utc_now(),
    )


def _household_with_id(household_id):
    return _household(household_id)


def _services_with_connector(error: Exception | None = None):
    connector = RecordingConnector(error=error)
    registry = ConnectorRegistry()
    registry.register(connector)
    services = replace(
        base_services(),
        household=HouseholdService(FakeHouseholdRepository(_household())),
        connectors=ConnectorService(registry, FakeCursorRepository()),
    )
    return services, connector


def test_manual_refresh_syncs_bakalari_and_redirects():
    services, connector = _services_with_connector()
    client = _client(services)

    response = client.post("/school/refresh", data={}, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/school"
    assert connector.calls[0][0].timezone == "Europe/Prague"


def test_manual_refresh_failure_lands_an_error_notice():
    services, connector = _services_with_connector(error=RuntimeError("school down"))
    client = _client(services)

    response = client.post("/school/refresh", data={}, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/school?gather=error"
    page = client.get("/school?gather=error")
    assert "The gather failed" in page.text
    assert connector.calls  # the gather was attempted


def test_manual_refresh_keeps_the_selected_kid():
    services, _connector = _services_with_connector()
    client = _client(services)
    kid_id = uuid4()

    response = client.post("/school/refresh", data={"kid": str(kid_id)}, follow_redirects=False)

    assert response.headers["location"] == f"/school?kid={kid_id}"
