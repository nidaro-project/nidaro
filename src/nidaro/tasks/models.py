from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from nidaro.db.base import Base, TimestampMixin
from nidaro.db.types import new_uuid


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=new_uuid)
    household_id: Mapped[UUID] = mapped_column(ForeignKey("households.id"), index=True)
    title: Mapped[str] = mapped_column(String(250))
    description: Mapped[str | None]
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="open")
    priority: Mapped[int] = mapped_column(Integer, default=0)
    assignee_id: Mapped[UUID | None] = mapped_column(ForeignKey("family_members.id"), nullable=True)
    event_id: Mapped[UUID | None] = mapped_column(ForeignKey("events.id"), nullable=True)
    source_id: Mapped[UUID | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
