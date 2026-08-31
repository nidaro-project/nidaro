from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from nidaro.connectors.base import StaleCursorError
from nidaro.connectors.models import (
    ConnectorContext,
    ConnectorCursor,
    ExternalRecord,
    SyncResult,
)
from nidaro.connectors.registry import ConnectorRegistry
from nidaro.connectors.service import ConnectorService
from nidaro.db.types import utc_now


class FakeConnector:
    name = "fake"

    async def sync(self, context, cursor):
        return SyncResult(
            records=[
                ExternalRecord(
                    connector=self.name,
                    external_type="note",
                    external_id="1",
                    payload={"title": "hello"},
                    content_hash="hash",
                    observed_at=datetime.now(UTC),
                )
            ],
            next_cursor="2",
        )


@pytest.mark.anyio
async def test_fake_connector_sync_and_registry():
    registry = ConnectorRegistry()
    connector = FakeConnector()
    registry.register(connector)
    result = await registry.get("fake").sync(
        ConnectorContext(household_id="1", timezone="UTC"), None
    )
    assert registry.names() == ["fake"]
    assert result.next_cursor == "2"
    assert result.records[0].payload["title"] == "hello"


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


class RecordingConnector:
    """Returns one queued cursor per call and can reject a poisoned one."""

    name = "recording"

    def __init__(self, next_cursors, reject=None):
        self.next_cursors = list(next_cursors)
        self.reject = reject
        self.seen: list[str | None] = []

    async def sync(self, context, cursor):
        self.seen.append(cursor)
        if cursor is not None and cursor == self.reject:
            raise StaleCursorError("source rejected the cursor")
        return SyncResult(records=[], next_cursor=self.next_cursors.pop(0))


def household_of(context: ConnectorContext) -> UUID:
    return UUID(context.household_id)


@pytest.mark.anyio
async def test_sync_persists_next_cursor():
    store = FakeCursorRepository()
    connector = RecordingConnector(["cursor-1"])
    registry = ConnectorRegistry()
    registry.register(connector)
    context = ConnectorContext(household_id=str(uuid4()), timezone="UTC")

    result = await ConnectorService(registry, store).sync("recording", context)

    assert result.next_cursor == "cursor-1"
    assert connector.seen == [None]
    (stored,) = store.rows.values()
    assert (stored.household_id, stored.connector, stored.cursor) == (
        household_of(context),
        "recording",
        "cursor-1",
    )


@pytest.mark.anyio
async def test_cursor_survives_service_restart():
    store = FakeCursorRepository()
    context = ConnectorContext(household_id=str(uuid4()), timezone="UTC")

    first_registry = ConnectorRegistry()
    first_registry.register(RecordingConnector(["cursor-1"]))
    await ConnectorService(first_registry, store).sync("recording", context)

    # A restarted process builds new service and connector objects over the
    # same database; the stored cursor must reach the connector untouched.
    second_connector = RecordingConnector(["cursor-2"])
    second_registry = ConnectorRegistry()
    second_registry.register(second_connector)
    await ConnectorService(second_registry, store).sync("recording", context)

    assert second_connector.seen == ["cursor-1"]


@pytest.mark.anyio
async def test_stale_cursor_is_cleared_and_next_sync_starts_fresh():
    store = FakeCursorRepository()
    connector = RecordingConnector(["bad-token", "good-token"], reject="bad-token")
    registry = ConnectorRegistry()
    registry.register(connector)
    service = ConnectorService(registry, store)
    context = ConnectorContext(household_id=str(uuid4()), timezone="UTC")

    await service.sync("recording", context)
    with pytest.raises(StaleCursorError):
        await service.sync("recording", context)
    assert connector.seen == [None, "bad-token"]
    assert await store.get(household_of(context), "recording") is None

    await service.sync("recording", context)
    assert connector.seen == [None, "bad-token", None]


@pytest.mark.anyio
async def test_explicit_cursor_overrides_stored_one():
    store = FakeCursorRepository()
    connector = RecordingConnector(["fresh"])
    registry = ConnectorRegistry()
    registry.register(connector)
    context = ConnectorContext(household_id=str(uuid4()), timezone="UTC")
    await store.save(household_of(context), "recording", "stored")

    await ConnectorService(registry, store).sync("recording", context, cursor="explicit")

    assert connector.seen == ["explicit"]
    assert await store.get(household_of(context), "recording") == "fresh"


@pytest.mark.anyio
async def test_run_without_next_cursor_keeps_stored_cursor():
    store = FakeCursorRepository()
    connector = RecordingConnector([None])
    registry = ConnectorRegistry()
    registry.register(connector)
    context = ConnectorContext(household_id=str(uuid4()), timezone="UTC")
    await store.save(household_of(context), "recording", "kept")

    await ConnectorService(registry, store).sync("recording", context)

    assert connector.seen == ["kept"]
    assert await store.get(household_of(context), "recording") == "kept"
