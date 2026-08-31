from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
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


# Cadence a household gets when onboarding without stating one: 15 minutes.
DEFAULT_POLL_SECONDS = 900


class ConnectorConfig(TimestampMixin, Base):
    """Per-household onboarding of one connector, stored in PostgreSQL.

    One row per (household, connector): whether the connector is enabled,
    the names of the credentials it uses (references into
    `connector_credentials` — identifiers, never secret material), the
    WhatsApp trigger word, and the polling cadence. `last_synced_at` is
    stamped by `ConnectorService.sync` after every completed run; the
    scheduler derives which configs are due from it plus `poll_seconds`.
    Disabling keeps the row so a re-enable needs no re-intake.
    """

    __tablename__ = "connector_configs"
    __table_args__ = (UniqueConstraint("household_id", "connector"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=new_uuid)
    household_id: Mapped[UUID] = mapped_column(ForeignKey("households.id"), index=True)
    connector: Mapped[str] = mapped_column(String(100))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    credential_names: Mapped[list[str]] = mapped_column(JSONB, default=list)
    trigger_word: Mapped[str | None] = mapped_column(String(100), nullable=True)
    poll_seconds: Mapped[int] = mapped_column(Integer, default=DEFAULT_POLL_SECONDS)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ConnectorCredential(TimestampMixin, Base):
    """One named secret for one connector in one household, stored encrypted.

    `secret` holds a Fernet token produced by `SecretBox`; plaintext exists
    only in memory on its way through `ConnectorCredentialService` and is
    never written, logged, or migrated. `name` distinguishes several
    credentials per connector (one Bakaláři account per kid, an OAuth
    refresh token next to an app-specific password).
    """

    __tablename__ = "connector_credentials"
    __table_args__ = (UniqueConstraint("household_id", "connector", "name"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=new_uuid)
    household_id: Mapped[UUID] = mapped_column(ForeignKey("households.id"), index=True)
    connector: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(100))
    secret: Mapped[str] = mapped_column(Text)
