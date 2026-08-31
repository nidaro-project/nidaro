"""WhatsAppConnector: staging drain round-trips into ExternalRecords idempotently."""

from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

import pytest

from nidaro.connectors.base import StaleCursorError
from nidaro.connectors.models import ConnectorContext, ConnectorCursor
from nidaro.connectors.registry import ConnectorRegistry
from nidaro.connectors.service import ConnectorService
from nidaro.connectors.whatsapp.connector import WhatsAppConnector
from nidaro.connectors.whatsapp.models import SOURCE_WEB_BRIDGE, SOURCE_WEBHOOK, WhatsAppEvent
from nidaro.db.types import utc_now


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


class FakeEventRepository:
    """In-memory staging store: unique-wamid dedupe and sequence ordering."""

    def __init__(self):
        self.rows: list[WhatsAppEvent] = []
        self.calls: list[str] = []

    async def stage(self, event: WhatsAppEvent) -> WhatsAppEvent | None:
        self.calls.append("stage")
        if any(row.wamid == event.wamid for row in self.rows):
            return None
        event.id = max((row.id for row in self.rows), default=0) + 1
        # Mirror what a real INSERT ... RETURNING row looks like: column
        # defaults applied.
        event.forwarded = bool(event.forwarded)
        event.payload = event.payload or {}
        self.rows.append(event)
        return event

    async def unprocessed(self, household_id, after_id=None, limit=500):
        self.calls.append("unprocessed")
        rows = [row for row in self.rows if row.household_id == household_id]
        if after_id is not None:
            rows = [row for row in rows if row.id > after_id]
        return sorted(rows, key=lambda row: row.id)[:limit]


def staged(
    wamid: str,
    household_id: UUID | None = None,
    *,
    type: str = "text",
    body: str | None = "see you saturday",
    source: str = SOURCE_WEBHOOK,
    **overrides,
) -> WhatsAppEvent:
    return WhatsAppEvent(
        household_id=household_id or uuid4(),
        wamid=wamid,
        source=source,
        type=type,
        body=body,
        observed_at=datetime(2026, 8, 29, 12, 0, tzinfo=UTC),
        payload={"raw": True},
        **overrides,
    )


def service_over(repository: FakeEventRepository, cursors: FakeCursorRepository):
    registry = ConnectorRegistry()
    registry.register(WhatsAppConnector(repository))
    return ConnectorService(registry, cursors)


def context_of(household_id: UUID) -> ConnectorContext:
    return ConnectorContext(household_id=str(household_id), timezone="UTC")


@pytest.mark.anyio
async def test_staged_group_message_round_trips_to_record():
    household = uuid4()
    repository = FakeEventRepository()
    await repository.stage(
        staged("wamid.group.1", household, source=SOURCE_WEB_BRIDGE, group_id="chat-42")
    )

    result = await service_over(repository, FakeCursorRepository()).sync(
        "whatsapp", context_of(household)
    )

    (record,) = result.records
    assert record.connector == "whatsapp"
    assert record.external_type == "message"
    assert record.external_id == "wamid.group.1"
    assert record.payload == {
        "type": "text",
        "body": "see you saturday",
        "from_user_id": None,
        "wa_id": None,
        "group_id": "chat-42",
        "context_id": None,
        "forwarded": False,
        "wamid": "wamid.group.1",
        "source": "web_bridge",
    }
    assert record.content_hash == sha256(b"wamid.group.1:see you saturday").hexdigest()
    assert record.observed_at == datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
    assert record.deleted is False


@pytest.mark.anyio
async def test_sync_is_idempotent_and_cursor_is_the_staging_high_water_id():
    household = uuid4()
    repository = FakeEventRepository()
    await repository.stage(staged("wamid.1", household))
    await repository.stage(staged("wamid.2", household, type="image", body=None))
    await repository.stage(staged("wamid.3", household))
    cursors = FakeCursorRepository()
    service = service_over(repository, cursors)

    first = await service.sync("whatsapp", context_of(household))
    assert [record.external_id for record in first.records] == ["wamid.1", "wamid.2", "wamid.3"]
    assert first.next_cursor == "3"
    assert await cursors.get(household, "whatsapp") == "3"

    second = await service.sync("whatsapp", context_of(household))
    assert second.records == []
    assert second.next_cursor is None
    assert await cursors.get(household, "whatsapp") == "3"


@pytest.mark.anyio
async def test_restaging_a_drained_wamid_collapses():
    repository = FakeEventRepository()
    staged_once = await repository.stage(staged("wamid.1"))
    staged_again = await repository.stage(staged("wamid.1"))
    assert staged_once is not None
    assert staged_again is None
    assert len(repository.rows) == 1


@pytest.mark.anyio
async def test_edits_and_revokes_ride_dedicated_external_types():
    household = uuid4()
    repository = FakeEventRepository()
    await repository.stage(staged("wamid.edit", household, type="edit", body="edited"))
    await repository.stage(staged("wamid.revoked", household, type="revoke", body=None))

    result = await service_over(repository, FakeCursorRepository()).sync(
        "whatsapp", context_of(household)
    )

    assert [record.external_type for record in result.records] == [
        "message.edit",
        "message.revoked",
    ]


@pytest.mark.anyio
async def test_poisoned_cursor_resets_and_redrains_from_scratch():
    household = uuid4()
    repository = FakeEventRepository()
    await repository.stage(staged("wamid.1", household))
    cursors = FakeCursorRepository()
    await cursors.save(household, "whatsapp", "not-an-int")
    service = service_over(repository, cursors)

    with pytest.raises(StaleCursorError):
        await service.sync("whatsapp", context_of(household))
    assert await cursors.get(household, "whatsapp") is None

    result = await service.sync("whatsapp", context_of(household))
    assert [record.external_id for record in result.records] == ["wamid.1"]


@pytest.mark.anyio
async def test_drain_is_scoped_to_one_household():
    household = uuid4()
    repository = FakeEventRepository()
    await repository.stage(staged("wamid.theirs", uuid4()))
    await repository.stage(staged("wamid.ours", household))

    result = await service_over(repository, FakeCursorRepository()).sync(
        "whatsapp", context_of(household)
    )

    assert [record.external_id for record in result.records] == ["wamid.ours"]


@pytest.mark.anyio
async def test_connector_only_reads_staging():
    """The drain writes nothing: not staging, not any domain table."""
    household = uuid4()
    repository = FakeEventRepository()
    await repository.stage(staged("wamid.1", household))

    await service_over(repository, FakeCursorRepository()).sync("whatsapp", context_of(household))

    assert repository.calls == ["stage", "unprocessed"]


@pytest.mark.anyio
async def test_connector_registered_under_its_name():
    connector = WhatsAppConnector(FakeEventRepository())
    registry = ConnectorRegistry()
    registry.register(connector)
    assert connector.name == "whatsapp"
    assert registry.get("whatsapp") is connector
