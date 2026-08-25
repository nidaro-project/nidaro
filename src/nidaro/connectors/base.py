from typing import Protocol

from nidaro.connectors.models import ConnectorContext, SyncResult


class Connector(Protocol):
    name: str

    async def sync(self, context: ConnectorContext, cursor: str | None) -> SyncResult: ...
