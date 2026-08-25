from datetime import UTC, datetime

import pytest

from nidaro.connectors.models import ConnectorContext, ExternalRecord, SyncResult
from nidaro.connectors.registry import ConnectorRegistry


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
