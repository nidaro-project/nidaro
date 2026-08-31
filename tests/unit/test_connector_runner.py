from uuid import UUID, uuid4

import pytest
from cryptography.fernet import Fernet

from nidaro.calendar.models import Event
from nidaro.calendar.repository import CalendarRepository
from nidaro.calendar.service import CalendarService
from nidaro.connectors.crypto import SecretBox
from nidaro.connectors.icloud_calendar import CONNECTOR_NAME
from nidaro.connectors.models import ExternalRecord, SyncResult
from nidaro.connectors.registry import ConnectorRegistry
from nidaro.connectors.repository import ConnectorConfigRepository
from nidaro.connectors.runner import sync_connector, sync_due
from nidaro.connectors.service import (
    ConnectorConfigService,
    ConnectorCredentialService,
    ConnectorService,
)
from nidaro.db.types import new_uuid, utc_now
from nidaro.household.repository import HouseholdRepository


class FakeHouseholdRepository(HouseholdRepository):
    def __init__(self):
        pass

    async def get(self, household_id=None):
        return None


class FakeMirrorRepository(CalendarRepository):
    """Identity lookups in Python; the seam CalendarService applies through."""

    def __init__(self):
        self.events = []

    async def upsert_mirror(self, household_id, connector, external_id, fields):
        event = next(
            (
                e
                for e in self.events
                if (e.household_id, e.external_connector, e.external_id)
                == (household_id, connector, external_id)
            ),
            None,
        )
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
        for index, event in enumerate(self.events):
            if (event.household_id, event.external_connector, event.external_id) == (
                household_id,
                connector,
                external_id,
            ):
                del self.events[index]
                return True
        return False


class FakeCursorRepository:
    def __init__(self):
        self.rows: dict[tuple[UUID, str], str] = {}

    async def get(self, household_id, connector):
        return self.rows.get((household_id, connector))

    async def save(self, household_id, connector, cursor):
        self.rows[(household_id, connector)] = cursor

    async def clear(self, household_id, connector):
        return self.rows.pop((household_id, connector), None) is not None


def calendar_record(external_id, **overrides):
    from datetime import UTC, datetime

    record = ExternalRecord(
        connector=CONNECTOR_NAME,
        external_type="calendar_event",
        external_id=external_id,
        payload={
            "title": f"Event {external_id}",
            "starts_at": datetime(2030, 6, 10, 8, 0, tzinfo=UTC),
        },
        content_hash=f"hash-{external_id}",
        observed_at=datetime.now(UTC),
    )
    return record.model_copy(update=overrides) if overrides else record


class FakeConfigRepository(ConnectorConfigRepository):
    """In-memory connector_configs rows for the sweep."""

    def __init__(self, rows=()):
        self.rows = list(rows)

    async def get(self, household_id, connector):
        return next(
            (
                row
                for row in self.rows
                if (row.household_id, row.connector) == (household_id, connector)
            ),
            None,
        )

    async def upsert(
        self,
        household_id,
        connector,
        *,
        enabled,
        credential_names,
        trigger_word,
        poll_seconds,
    ):
        from nidaro.connectors.models import ConnectorConfig

        row = await self.get(household_id, connector)
        if row is None:
            row = ConnectorConfig(
                household_id=household_id,
                connector=connector,
                enabled=enabled,
                credential_names=credential_names,
                trigger_word=trigger_word,
                poll_seconds=poll_seconds,
            )
            self.rows.append(row)
        else:
            row.enabled = enabled
            row.credential_names = credential_names
            row.poll_seconds = poll_seconds
        return row

    async def enabled_for_household(self, household_id):
        return [row for row in self.rows if row.household_id == household_id and row.enabled]

    async def all_enabled(self):
        return [row for row in self.rows if row.enabled]

    async def stamp_synced(self, household_id, connector, at):
        row = await self.get(household_id, connector)
        if row is None:
            return False
        row.last_synced_at = at
        return True


class FakeCredentialRepository:
    """Ciphertext-at-rest stand-in: values only decryptable with the box."""

    def __init__(self):
        self.rows: dict[tuple[UUID, str, str], str] = {}

    async def get_ciphertext(self, household_id, connector, name):
        return self.rows.get((household_id, connector, name))

    async def save_ciphertext(self, household_id, connector, name, ciphertext):
        self.rows[(household_id, connector, name)] = ciphertext
        return ciphertext

    async def delete(self, household_id, connector, name):
        return self.rows.pop((household_id, connector, name), None) is not None

    async def names(self, household_id, connector):
        return [key[2] for key in self.rows if key[:2] == (household_id, connector)]

    async def all(self):
        return []


class RecordingConnector:
    """Emits one queued batch per sync so the sweep's routing is visible."""

    def __init__(self, batches):
        self.name = CONNECTOR_NAME
        self.batches = list(batches)
        self.seen_credentials = []

    async def sync(self, context, cursor):
        self.seen_credentials.append(dict(context.credentials))
        return SyncResult(
            records=self.batches.pop(0), next_cursor=f"cursor-{len(self.seen_credentials)}"
        )


class RunnerServices:
    """The ConnectorSyncServices slice, real services over fakes."""

    def __init__(self, rows, batches):
        self.mirrors = FakeMirrorRepository()
        self.calendar = CalendarService(self.mirrors, FakeHouseholdRepository())
        self.credentials = ConnectorCredentialService(
            FakeCredentialRepository(), SecretBox(Fernet.generate_key())
        )
        self.connectors = ConnectorService(ConnectorRegistry(), FakeCursorRepository())
        self.connector_configs = ConnectorConfigService(FakeConfigRepository(rows))
        self.household = FakeHouseholdRepository()

        self.connector = RecordingConnector(batches)
        self.connectors.registry.register(self.connector)

    async def onboard(self, household_id, *, credential_names=()):
        await self.connector_configs.enable(
            household_id, CONNECTOR_NAME, credential_names=credential_names
        )
        for name in credential_names:
            await self.credentials.set(household_id, CONNECTOR_NAME, name, f"secret-for-{name}")


@pytest.mark.anyio
async def test_sync_connector_routes_records_into_the_calendar_domain():
    household_id = uuid4()
    services = RunnerServices([], [[calendar_record("e1"), calendar_record("e2")]])
    await services.onboard(household_id)

    outcome = await sync_connector(services, CONNECTOR_NAME, household_id)

    assert (outcome.records, outcome.applied, outcome.removed) == (2, 2, 0)
    assert {event.title for event in services.mirrors.events} == {"Event e1", "Event e2"}


@pytest.mark.anyio
async def test_sync_connector_resolves_credential_names_into_the_context():
    household_id = uuid4()
    services = RunnerServices([], [[]])
    await services.onboard(household_id, credential_names=("apple_id",))

    await sync_connector(services, CONNECTOR_NAME, household_id)

    assert services.connector.seen_credentials == [{"apple_id": "secret-for-apple_id"}]


@pytest.mark.anyio
async def test_sync_connector_skips_records_without_an_applier():
    household_id = uuid4()
    foreign = calendar_record("w1")
    foreign = foreign.model_copy(update={"external_type": "school_note"})
    services = RunnerServices([], [[foreign]])
    await services.onboard(household_id)

    outcome = await sync_connector(services, CONNECTOR_NAME, household_id)

    assert (outcome.records, outcome.applied, outcome.skipped) == (1, 0, 1)
    assert services.mirrors.events == []


@pytest.mark.anyio
async def test_sync_connector_unknown_config_raises():
    services = RunnerServices([], [])
    with pytest.raises(LookupError):
        await sync_connector(services, CONNECTOR_NAME, uuid4())


@pytest.mark.anyio
async def test_tombstone_records_remove_the_mirror():
    household_id = uuid4()
    services = RunnerServices(
        [],
        [
            [calendar_record("e1")],
            [calendar_record("e1", deleted=True)],
        ],
    )
    await services.onboard(household_id)

    await sync_connector(services, CONNECTOR_NAME, household_id)
    assert len(services.mirrors.events) == 1
    outcome = await sync_connector(services, CONNECTOR_NAME, household_id)

    assert (outcome.applied, outcome.removed) == (0, 1)
    assert services.mirrors.events == []


@pytest.mark.anyio
async def test_sync_due_sweeps_only_due_configs_and_survives_failures():
    healthy, broken = uuid4(), uuid4()

    class PerHouseholdConnector:
        """Succeeds for the healthy household, explodes for the broken one."""

        name = CONNECTOR_NAME

        async def sync(self, context, cursor):
            if UUID(context.household_id) == broken:
                raise RuntimeError("boom")
            return SyncResult(records=[calendar_record("e1")], next_cursor="c1")

    services = RunnerServices(rows=[], batches=[])
    services.connectors.registry.register(PerHouseholdConnector())
    await services.onboard(healthy)
    await services.onboard(broken)

    report = await sync_due(services)

    assert [outcome.household_id for outcome in report.outcomes] == [str(healthy)]
    assert (report.outcomes[0].applied) == 1
    assert len(report.errors) == 1
    assert str(broken) in report.errors[0]


@pytest.mark.anyio
async def test_sync_due_respects_the_connector_filter():
    household_id = uuid4()
    services = RunnerServices([], [[calendar_record("e1")]])
    await services.onboard(household_id)

    report = await sync_due(services, connector="other_connector")

    assert report.outcomes == []
    assert report.errors == []
    assert services.connector.seen_credentials == []
