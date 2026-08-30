from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ARRAY, Column, DateTime, ForeignKey, Integer, String, Table
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
    __tablename__ = "events"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=new_uuid)
    household_id: Mapped[UUID] = mapped_column(ForeignKey("households.id"), index=True)
    title: Mapped[str] = mapped_column(String(250))
    description: Mapped[str | None]
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    location: Mapped[str | None]
    status: Mapped[str] = mapped_column(String(40), default="scheduled")
    source_id: Mapped[UUID | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    is_all_day: Mapped[bool] = mapped_column(default=False)
    recurrence_weekdays: Mapped[list[int] | None] = mapped_column(ARRAY(Integer), nullable=True)
    participants: Mapped[list[FamilyMember]] = relationship(secondary=event_participants)
