from nidaro.connectors.models import ConnectorContext, SyncResult
from nidaro.connectors.registry import ConnectorRegistry


class ConnectorService:
    def __init__(self, registry: ConnectorRegistry) -> None:
        self.registry = registry

    async def sync(
        self, name: str, context: ConnectorContext, cursor: str | None = None
    ) -> SyncResult:
        return await self.registry.get(name).sync(context, cursor)
