from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from nidaro.db.base import Base, TimestampMixin
from nidaro.db.types import new_uuid


class ConnectorContext(BaseModel):
    household_id: str
    timezone: str


class ExternalRecord(BaseModel):
    """One item landed from an external source.

    A record with `deleted=True` is a tombstone: the source removed the item
    (a Google Calendar event turning `status:"cancelled"`, a CalDAV
    sync-collection REPORT deletion). Its `payload` carries no content and
    must not be applied; the domain application service that mirrors the
    record must remove its mirror instead. Live records keep `deleted=False`.
    """

    connector: str
    external_type: str
    external_id: str
    payload: dict[str, Any]
    content_hash: str
    observed_at: datetime
    deleted: bool = False


class SyncResult(BaseModel):
    records: list[ExternalRecord]
    next_cursor: str | None = None


class ConnectorCursor(TimestampMixin, Base):
    """High-water mark of one connector for one household.

    `cursor` holds whatever opaque token the connector emitted as
    `next_cursor` (Google Calendar syncToken, CalDAV sync-token map, WhatsApp
    high-water id). One row per (household, connector).
    """

    __tablename__ = "connector_cursors"
    __table_args__ = (UniqueConstraint("household_id", "connector"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=new_uuid)
    household_id: Mapped[UUID] = mapped_column(ForeignKey("households.id"), index=True)
    connector: Mapped[str] = mapped_column(String(100))
    cursor: Mapped[str] = mapped_column(Text)
