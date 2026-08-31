"""WhatsApp connector: drains the staging table into external records."""

import hashlib
from typing import Protocol
from uuid import UUID

from nidaro.connectors.base import StaleCursorError
from nidaro.connectors.models import ConnectorContext, ExternalRecord, SyncResult
from nidaro.connectors.whatsapp.models import WhatsAppEvent
from nidaro.connectors.whatsapp.repository import DEFAULT_BATCH

# A staged edit/revoke is a correction of a previously drained message, so
# it rides as its own record type and downstream interpreters apply it
# without mutating the original message's history.
EDIT_EXTERNAL_TYPE = "message.edit"
REVOKED_EXTERNAL_TYPE = "message.revoked"

_EXTERNAL_TYPES = {"edit": EDIT_EXTERNAL_TYPE, "revoke": REVOKED_EXTERNAL_TYPE}


class WhatsAppEventRepositoryProtocol(Protocol):
    """What the drain needs from staging — satisfied by WhatsAppEventRepository."""

    async def stage(self, event: WhatsAppEvent) -> WhatsAppEvent | None: ...

    async def unprocessed(
        self, household_id: UUID, after_id: int | None = None, limit: int = DEFAULT_BATCH
    ) -> list[WhatsAppEvent]: ...


class WhatsAppConnector:
    """Drains staged WhatsApp events into `ExternalRecord`s; writes nothing.

    The sync is a pure function of staging state: it reads rows beyond the
    high-water cursor and never writes back — not to staging, not to any
    domain table. `ConnectorService` persists `next_cursor` (the staging
    high-water id) after a successful run and replays it on the next one,
    which makes repeated drains idempotent. Group messages staged by the
    web bridge ride the same path as official-DM webhook events, tagged
    `source: "web_bridge"`; commitment/task writes happen only when a
    downstream application service applies the emitted records — trigger
    parsing and interpretation stay on the official-DM path, never here.
    """

    name = "whatsapp"

    def __init__(self, events: WhatsAppEventRepositoryProtocol) -> None:
        self.events = events

    async def sync(self, context: ConnectorContext, cursor: str | None) -> SyncResult:
        rows = await self.events.unprocessed(
            UUID(context.household_id), after_id=_parse_cursor(cursor), limit=DEFAULT_BATCH
        )
        return SyncResult(
            records=[_record(row) for row in rows],
            next_cursor=str(rows[-1].id) if rows else None,
        )


def _parse_cursor(cursor: str | None) -> int | None:
    if cursor is None:
        return None
    try:
        return int(cursor)
    except ValueError as error:
        raise StaleCursorError(
            f"whatsapp staging cursor {cursor!r} is not a staging row id"
        ) from error


def _record(row: WhatsAppEvent) -> ExternalRecord:
    return ExternalRecord(
        connector="whatsapp",
        external_type=_EXTERNAL_TYPES.get(row.type, "message"),
        external_id=row.wamid,
        payload={
            "type": row.type,
            "body": row.body,
            "from_user_id": row.from_user_id,
            "wa_id": row.wa_id,
            "group_id": row.group_id,
            "context_id": row.context_id,
            "forwarded": row.forwarded,
            "wamid": row.wamid,
            "source": row.source,
        },
        content_hash=hashlib.sha256(f"{row.wamid}:{row.body}".encode()).hexdigest(),
        observed_at=row.observed_at,
    )
