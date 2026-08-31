from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from nidaro.connectors.base import StaleCursorError
from nidaro.connectors.models import (
    DEFAULT_POLL_SECONDS,
    ConnectorConfig,
    ConnectorContext,
    ConnectorCursor,
    SyncResult,
)
from nidaro.connectors.registry import ConnectorRegistry
from nidaro.connectors.service import ConnectorConfigService, ConnectorService
from nidaro.db.types import new_uuid, utc_now


class FakeConfigRepository:
    def __init__(self):
        self.rows: dict[tuple[UUID, str], ConnectorConfig] = {}

    async def get(self, household_id, connector):
        return self.rows.get((household_id, connector))

    async def upsert(
        self, household_id, connector, *, enabled, credential_names, trigger_word, poll_seconds
    ):
        row = self.rows.get((household_id, connector))
        if row is None:
            row = ConnectorConfig(
                id=new_uuid(),
                household_id=household_id,
                connector=connector,
                enabled=enabled,
                credential_names=credential_names,
                trigger_word=trigger_word,
                poll_seconds=poll_seconds,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            self.rows[(household_id, connector)] = row
        else:
            row.enabled = enabled
            row.credential_names = credential_names
            row.trigger_word = trigger_word
            row.poll_seconds = poll_seconds
            row.updated_at = utc_now()
        return row

    async def enabled_for_household(self, household_id):
        return sorted(
            (row for (hid, _), row in self.rows.items() if hid == household_id and row.enabled),
            key=lambda row: row.connector,
        )

    async def all_enabled(self):
        return sorted(
            (row for row in self.rows.values() if row.enabled),
            key=lambda row: (row.household_id, row.connector),
        )

    async def stamp_synced(self, household_id, connector, at):
        row = self.rows.get((household_id, connector))
        if row is None:
            return False
        row.last_synced_at = at
        return True


class FakeCursorRepository:
    def __init__(self):
        self.rows: dict[tuple[UUID, str], ConnectorCursor] = {}

    async def get(self, household_id, connector):
        row = self.rows.get((household_id, connector))
        return row.cursor if row else None

    async def save(self, household_id, connector, cursor):
        row = self.rows.get((household_id, connector))
        if row is None:
            row = ConnectorCursor(
                household_id=household_id,
                connector=connector,
                cursor=cursor,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            self.rows[(household_id, connector)] = row
        else:
            row.cursor = cursor
            row.updated_at = utc_now()
        return row

    async def clear(self, household_id, connector):
        return self.rows.pop((household_id, connector), None) is not None


class PunctualConnector:
    name = "punctual"

    def __init__(self, fail=False):
        self.fail = fail

    async def sync(self, context, cursor):
        if self.fail:
            raise StaleCursorError("source rejected the cursor")
        return SyncResult(records=[], next_cursor=None)


def make_service() -> tuple[ConnectorConfigService, FakeConfigRepository]:
    repository = FakeConfigRepository()
    return ConnectorConfigService(repository), repository


@pytest.mark.anyio
async def test_enable_is_one_call_and_stores_full_intake():
    service, repository = make_service()
    household_id = uuid4()

    row = await service.enable(
        household_id,
        "bakalari",
        credential_names=["emma"],
        trigger_word="škola",
        poll_seconds=300,
    )

    assert row.enabled is True
    assert row.credential_names == ["emma"]
    assert row.trigger_word == "škola"
    assert row.poll_seconds == 300
    assert repository.rows[(household_id, "bakalari")] is row


@pytest.mark.anyio
async def test_enable_defaults_to_standard_cadence_and_no_references():
    service, _ = make_service()
    household_id = uuid4()

    row = await service.enable(household_id, "whatsapp")

    assert row.enabled is True
    assert row.credential_names == []
    assert row.trigger_word is None
    assert row.poll_seconds == DEFAULT_POLL_SECONDS


@pytest.mark.anyio
async def test_enable_reconfigures_existing_row_in_place():
    service, repository = make_service()
    household_id = uuid4()

    first = await service.enable(household_id, "bakalari", credential_names=["emma"])
    second = await service.enable(
        household_id, "bakalari", credential_names=["emma", "leo"], poll_seconds=60
    )

    assert first.id == second.id
    assert len(repository.rows) == 1
    assert second.credential_names == ["emma", "leo"]
    assert second.poll_seconds == 60


@pytest.mark.anyio
async def test_enable_rejects_nonpositive_cadence():
    service, _ = make_service()
    household_id = uuid4()

    with pytest.raises(ValueError, match="poll_seconds"):
        await service.enable(household_id, "bakalari", poll_seconds=0)
    with pytest.raises(ValueError, match="poll_seconds"):
        await service.enable(household_id, "bakalari", poll_seconds=-5)


@pytest.mark.anyio
async def test_disable_keeps_intake_and_reports_presence():
    service, _ = make_service()
    household_id = uuid4()
    await service.enable(
        household_id, "bakalari", credential_names=["emma"], trigger_word="škola", poll_seconds=300
    )

    assert await service.disable(household_id, "bakalari")
    assert not await service.disable(household_id, "bakalari")

    row = await service.get(household_id, "bakalari")
    assert row is not None
    assert row.enabled is False
    assert row.credential_names == ["emma"]
    assert row.trigger_word == "škola"
    assert row.poll_seconds == 300


@pytest.mark.anyio
async def test_disable_never_onboarded_returns_false():
    service, _ = make_service()

    assert not await service.disable(uuid4(), "bakalari")


@pytest.mark.anyio
async def test_enabled_lists_only_enabled_rows_of_one_household():
    service, _ = make_service()
    household_a, household_b = uuid4(), uuid4()
    await service.enable(household_a, "bakalari")
    await service.enable(household_a, "whatsapp", trigger_word="nali")
    await service.enable(household_a, "gcal")
    await service.disable(household_a, "gcal")
    await service.enable(household_b, "bakalari")

    names = [row.connector for row in await service.enabled(household_a)]

    assert names == ["bakalari", "whatsapp"]


@pytest.mark.anyio
async def test_due_returns_never_synced_and_elapsed_configs():
    service, repository = make_service()
    household_id = uuid4()
    now = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

    await service.enable(household_id, "bakalari", poll_seconds=300)
    await service.enable(household_id, "whatsapp", poll_seconds=600)
    await service.enable(household_id, "gcal", poll_seconds=3600)
    # whatsapp synced twice its cadence ago; gcal half its cadence ago.
    await repository.stamp_synced(household_id, "whatsapp", now - timedelta(seconds=1200))
    await repository.stamp_synced(household_id, "gcal", now - timedelta(seconds=1800))

    names = [row.connector for row in await service.due(now)]

    assert names == ["bakalari", "whatsapp"]


@pytest.mark.anyio
async def test_due_skips_disabled_configs():
    service, _ = make_service()
    household_id = uuid4()
    now = utc_now()

    await service.enable(household_id, "bakalari")
    await service.enable(household_id, "gcal")
    await service.disable(household_id, "gcal")

    # gcal was never synced, so only the enabled filter keeps it out of due.
    assert [row.connector for row in await service.due(now)] == ["bakalari"]


@pytest.mark.anyio
async def test_sync_stamps_last_synced_at_on_the_config():
    config_service, repository = make_service()
    household_id = uuid4()
    await config_service.enable(household_id, "punctual", poll_seconds=300)
    registry = ConnectorRegistry()
    registry.register(PunctualConnector())
    connector_service = ConnectorService(registry, FakeCursorRepository(), configs=repository)

    assert repository.rows[(household_id, "punctual")].last_synced_at is None
    await connector_service.sync(
        "punctual", ConnectorContext(household_id=str(household_id), timezone="UTC")
    )

    stamped = await config_service.get(household_id, "punctual")
    assert stamped is not None
    assert stamped.last_synced_at is not None


@pytest.mark.anyio
async def test_sync_without_config_row_does_not_create_one():
    config_service, repository = make_service()
    registry = ConnectorRegistry()
    registry.register(PunctualConnector())
    connector_service = ConnectorService(registry, FakeCursorRepository(), configs=repository)

    await connector_service.sync(
        "punctual", ConnectorContext(household_id=str(uuid4()), timezone="UTC")
    )

    assert repository.rows == {}
    assert await config_service.due() == []


@pytest.mark.anyio
async def test_failed_sync_does_not_stamp():
    config_service, repository = make_service()
    household_id = uuid4()
    await config_service.enable(household_id, "punctual")
    registry = ConnectorRegistry()
    registry.register(PunctualConnector(fail=True))
    connector_service = ConnectorService(registry, FakeCursorRepository(), configs=repository)

    with pytest.raises(StaleCursorError):
        await connector_service.sync(
            "punctual", ConnectorContext(household_id=str(household_id), timezone="UTC")
        )

    failed = await config_service.get(household_id, "punctual")
    assert failed is not None
    assert failed.last_synced_at is None
