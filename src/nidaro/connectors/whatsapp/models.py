"""WhatsApp staging: raw message events parked at ingest, drained by the connector."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Identity, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from nidaro.db.base import Base, TimestampMixin

# Producer identity, carried onto every emitted record's payload as `source`.
SOURCE_WEBHOOK = "webhook"
SOURCE_WEB_BRIDGE = "web_bridge"


class WhatsAppEvent(TimestampMixin, Base):
    """One staged WhatsApp message event awaiting the connector drain.

    Producers (official webhook ingest, web-bridge observer) park raw events
    here; `WhatsAppConnector.sync` drains them into `ExternalRecord`s. The
    normalized columns are extracted deterministically at staging time so
    the drain never re-parses. `wamid` is globally unique, so webhook
    retries (Meta redelivers for 36 hours) and batches (up to 1000 updates)
    collapse onto one row.

    `id` is a monotonic sequence, not the house UUID: it doubles as the
    drain's high-water cursor, and two same-millisecond UUIDv7 inserts can
    order arbitrarily, which would silently skip a message. `payload` keeps
    the raw event for reprocessing and retention decisions; `processed_at`
    is reserved for that later retention/extraction flow — the drain itself
    is purely cursor-driven and writes nothing back.
    """

    __tablename__ = "whatsapp_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    household_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("households.id"), index=True
    )
    wamid: Mapped[str] = mapped_column(String(250), unique=True)
    source: Mapped[str] = mapped_column(String(40))
    type: Mapped[str] = mapped_column(String(40))
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    from_user_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    wa_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    group_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    context_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    forwarded: Mapped[bool] = mapped_column(Boolean, default=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
