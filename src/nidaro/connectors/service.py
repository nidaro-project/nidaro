from typing import Protocol
from uuid import UUID

from nidaro.connectors.base import StaleCursorError
from nidaro.connectors.models import ConnectorContext, ConnectorCursor, SyncResult
from nidaro.connectors.registry import ConnectorRegistry


class ConnectorCursorRepositoryProtocol(Protocol):
    async def get(self, household_id: UUID, connector: str) -> str | None: ...

    async def save(self, household_id: UUID, connector: str, cursor: str) -> ConnectorCursor: ...

    async def clear(self, household_id: UUID, connector: str) -> bool: ...


class ConnectorService:
    def __init__(
        self, registry: ConnectorRegistry, cursors: ConnectorCursorRepositoryProtocol
    ) -> None:
        self.registry = registry
        self.cursors = cursors

    async def sync(
        self, name: str, context: ConnectorContext, cursor: str | None = None
    ) -> SyncResult:
        """Run one connector sync for a household, persisting its high-water mark.

        With `cursor=None` the stored cursor for (household, connector) is used,
        so callers do not track cursors across runs or service restarts. An
        explicit `cursor` argument overrides the stored one. A connector that
        rejects the stored cursor raises `StaleCursorError`; the stored cursor
        is cleared before the error propagates, making the next sync start
        fresh. A run without a `next_cursor` leaves the stored cursor as-is.
        """
        household_id = UUID(context.household_id)
        effective = cursor if cursor is not None else await self.cursors.get(household_id, name)
        try:
            result = await self.registry.get(name).sync(context, effective)
        except StaleCursorError:
            await self.cursors.clear(household_id, name)
            raise
        if result.next_cursor is not None:
            await self.cursors.save(household_id, name, result.next_cursor)
        return result
