"""Staging store for WhatsApp events: producers park events, the connector drains."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nidaro.connectors.whatsapp.models import WhatsAppEvent

# Upper bound on one drain pass. Meta batches webhooks at <=1000 updates;
# a household bridge produces far less, and the cursor resumes next run.
DEFAULT_BATCH = 500


class WhatsAppEventRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def stage(self, event: WhatsAppEvent) -> WhatsAppEvent | None:
        """Park one event; return None when its wamid is already staged.

        Dedupe collapses webhook retries and double-staging from both
        producers; the first staged copy of a wamid wins.
        """
        async with self.sessions.begin() as session:
            stmt = (
                insert(WhatsAppEvent)
                .values(
                    household_id=event.household_id,
                    wamid=event.wamid,
                    source=event.source,
                    type=event.type,
                    body=event.body,
                    from_user_id=event.from_user_id,
                    wa_id=event.wa_id,
                    group_id=event.group_id,
                    context_id=event.context_id,
                    # Column defaults apply at flush, too late for an explicit
                    # values() insert — normalize here instead.
                    forwarded=bool(event.forwarded),
                    payload=event.payload or {},
                    observed_at=event.observed_at,
                )
                .on_conflict_do_nothing(index_elements=[WhatsAppEvent.wamid])
                .returning(WhatsAppEvent)
            )
            return await session.scalar(stmt)

    async def unprocessed(
        self, household_id: UUID, after_id: int | None = None, limit: int = DEFAULT_BATCH
    ) -> list[WhatsAppEvent]:
        """Staged events beyond `after_id` in staging order, oldest first.

        "Unprocessed" means not yet reached by the drain's cursor: rows
        strictly newer than the high-water id. The drain itself marks
        nothing; replaying the same cursor re-reads the same rows, so
        idempotency comes from the cursor plus the wamid uniqueness.
        """
        async with self.sessions() as session:
            stmt = select(WhatsAppEvent).where(WhatsAppEvent.household_id == household_id)
            if after_id is not None:
                stmt = stmt.where(WhatsAppEvent.id > after_id)
            result = await session.scalars(stmt.order_by(WhatsAppEvent.id).limit(limit))
            return list(result)
