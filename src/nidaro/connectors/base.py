from typing import Protocol

from nidaro.connectors.models import ConnectorContext, SyncResult


class Connector(Protocol):
    name: str

    async def sync(self, context: ConnectorContext, cursor: str | None) -> SyncResult: ...


class StaleCursorError(Exception):
    """The source rejected the passed cursor (Google Calendar 410 GONE,
    expired CalDAV sync token, compacted WhatsApp stream).

    ConnectorService clears the persisted cursor before re-raising, so the
    next sync starts from scratch."""
