from dataclasses import replace
from uuid import uuid4

import pytest

from nidaro.calendar.models import Event
from nidaro.calendar.repository import CalendarRepository
from nidaro.calendar.service import CalendarService
from nidaro.config import get_settings
from nidaro.connectors.models import ConnectorConfig, ExternalRecord, SyncResult
from nidaro.connectors.registry import ConnectorRegistry
from nidaro.connectors.repository import ConnectorConfigRepository, ConnectorCursorRepository
from nidaro.connectors.service import ConnectorConfigService, ConnectorService
from nidaro.container import ApplicationServices
from nidaro.db.engine import create_engine, create_session_factory
from nidaro.db.types import new_uuid, utc_now
from nidaro.household.models import Household
from nidaro.household.repository import HouseholdRepository
from nidaro.household.service import HouseholdService
from nidaro.jobs.tasks import run_connector_sync, run_due_connector_syncs

HOUSEHOLD_ID = uuid4()


def config_row(connector="google_calendar", household_id=HOUSEHOLD_ID):
    return ConnectorConfig(
        id=new_uuid(),
        household_id=household_id,
        connector=connector,
        enabled=True,
        credential_names=[],
        trigger_word=None,
        poll_seconds=900,
        last_synced_at=None,
        created_at=utc_now(),
        updated_at=utc_now(),
    )


def external_record(external_id="ada@example.com/primary/evt1"):
    return ExternalRecord(
        connector="google_calendar",
        external_type="calendar_event",
        external_id=external_id,
        payload={
            "title": "Dentist",
            "starts_at": "2026-09-03T17:00:00+02:00",
            "ends_at": None,
            "description": None,
            "location": None,
            "is_all_day": False,
        },
        content_hash="hash",
        observed_at=utc_now(),
    )


class ScriptedConnector:
    name = "google_calendar"

    def __init__(self, records=(), error=None):
        self.records = list(records)
        self.error = error
        self.seen = []

    async def sync(self, context, cursor):
        self.seen.append((context, cursor))
        if self.error is not None:
            raise self.error
        return SyncResult(records=list(self.records), next_cursor="tok-2")


class FakeCursorRepository(ConnectorCursorRepository):
    def __init__(self):
        self.rows = {}

    async def get(self, household_id, connector):
        return self.rows.get((household_id, connector))

    async def save(self, household_id, connector, cursor):
        self.rows[(household_id, connector)] = cursor

    async def clear(self, household_id, connector):
        return self.rows.pop((household_id, connector), None) is not None


class FakeConfigRepository(ConnectorConfigRepository):
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.stamped = []

    async def all_enabled(self):
        return list(self.rows)

    async def stamp_synced(self, household_id, connector, at):
        self.stamped.append((household_id, connector))
        return True


class FakeHouseholdRepository(HouseholdRepository):
    def __init__(self):
        pass

    async def get(self, household_id=None):
        return None


class FakeHouseholdsService(HouseholdService):
    def __init__(self):
        self.household = Household(
            id=HOUSEHOLD_ID,
            name="Home",
            timezone="Europe/Prague",
            created_at=utc_now(),
            updated_at=utc_now(),
        )

    async def get_household(self, household_id=None):
        if household_id is None or household_id == self.household.id:
            return self.household
        return None


class FakeMirrorRepository(CalendarRepository):
    def __init__(self):
        self.events = []

    async def upsert_mirror(self, household_id, connector, external_id, fields):
        self.events.append(
            Event(
                id=new_uuid(),
                household_id=household_id,
                external_connector=connector,
                external_id=external_id,
                status="scheduled",
                created_at=utc_now(),
                updated_at=utc_now(),
                **fields,
            )
        )

    async def remove_mirror(self, household_id, connector, external_id):
        return False


def make_services(connector, config_repository):
    """The real container shape; only the worker-touched services are faked.

    The session factory never connects: the fakes serve every path the sweep
    exercises.
    """
    sessions = create_session_factory(create_engine(get_settings()))
    calendar = CalendarService(FakeMirrorRepository(), FakeHouseholdRepository())
    return (
        replace(
            ApplicationServices.build(sessions),
            connectors=ConnectorService(
                _registry(connector), FakeCursorRepository(), config_repository
            ),
            connector_configs=ConnectorConfigService(config_repository),
            household=FakeHouseholdsService(),
            calendar=calendar,
        ),
        calendar,
    )


def _registry(connector):
    registry = ConnectorRegistry()
    registry.register(connector)
    return registry


@pytest.mark.anyio
async def test_connector_run_syncs_applies_and_stamps():
    connector = ScriptedConnector(records=[external_record()])
    config_repository = FakeConfigRepository([config_row()])
    services, calendar = make_services(connector, config_repository)

    outcome = await run_connector_sync(services, "google_calendar", str(HOUSEHOLD_ID))

    assert outcome["status"] == "ok"
    assert outcome["applied"] == 1
    (context, _cursor) = connector.seen[0]
    assert context.timezone == "Europe/Prague"
    assert len(calendar.repository.events) == 1
    assert config_repository.stamped == [(HOUSEHOLD_ID, "google_calendar")]


@pytest.mark.anyio
async def test_connector_without_applier_is_not_run():
    connector = ScriptedConnector()
    services, calendar = make_services(connector, FakeConfigRepository())

    outcome = await run_connector_sync(services, "whatsapp_bridge", str(HOUSEHOLD_ID))

    assert outcome["status"] == "no_applier"
    assert connector.seen == []
    assert calendar.repository.events == []


@pytest.mark.anyio
async def test_connector_run_for_unknown_household_is_reported():
    connector = ScriptedConnector()
    services, _calendar = make_services(connector, FakeConfigRepository())

    outcome = await run_connector_sync(services, "google_calendar", str(uuid4()))

    assert outcome["status"] == "no_household"
    assert connector.seen == []


@pytest.mark.anyio
async def test_sweep_runs_every_due_config_and_isolates_failures():
    failing = ScriptedConnector(error=RuntimeError("Google is down"))
    config_repository = FakeConfigRepository([config_row(), config_row(household_id=HOUSEHOLD_ID)])
    services, _calendar = make_services(failing, config_repository)

    result = await run_due_connector_syncs(services)

    assert result["ran"] == 2
    assert all(entry["status"] == "error" for entry in result["results"])
    assert "Google is down" in result["results"][0]["error"]
    # The sweep itself completed; every due config was attempted despite the
    # first household failing.
    assert len(failing.seen) == 2


@pytest.mark.anyio
async def test_sweep_with_nothing_due_runs_nothing():
    connector = ScriptedConnector(records=[external_record()])
    services, calendar = make_services(connector, FakeConfigRepository())

    result = await run_due_connector_syncs(services)

    assert result["ran"] == 0
    assert connector.seen == []
    assert calendar.repository.events == []
