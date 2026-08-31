from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nidaro.db.base import Base, TimestampMixin
from nidaro.db.types import new_uuid
from nidaro.household.models import FamilyMember

event_participants = Table(
    "event_participants",
    Base.metadata,
    Column(
        "event_id",
        PGUUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "member_id",
        PGUUID(as_uuid=True),
        ForeignKey("family_members.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Event(TimestampMixin, Base):
    """A calendar event, human-created or mirroring an external item.

    A mirror carries the `external_connector` name plus the source's
    `external_id`, so the application service can upsert it on every sync and
    remove it when the source sends a tombstone (ExternalRecord.deleted). The
    partial unique index makes one mirror per (household, connector, external
    id) a database guarantee, not just an application habit.
    """

    __tablename__ = "events"
    __table_args__ = (
        Index(
            "uq_events_external_identity",
            "household_id",
            "external_connector",
            "external_id",
            unique=True,
            postgresql_where=text("external_id IS NOT NULL"),
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=new_uuid)
    household_id: Mapped[UUID] = mapped_column(ForeignKey("households.id"), index=True)
    external_connector: Mapped[str | None] = mapped_column(String(100), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(250), nullable=True)
    title: Mapped[str] = mapped_column(String(250))
    description: Mapped[str | None]
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_all_day: Mapped[bool] = mapped_column(default=False)
    recurrence_weekdays: Mapped[list[int] | None] = mapped_column(ARRAY(Integer), nullable=True)
    location: Mapped[str | None]
    status: Mapped[str] = mapped_column(String(40), default="scheduled")
    source_id: Mapped[UUID | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    participants: Mapped[list[FamilyMember]] = relationship(secondary=event_participants)
