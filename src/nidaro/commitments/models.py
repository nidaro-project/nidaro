from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from nidaro.db.base import Base, TimestampMixin
from nidaro.db.types import new_uuid


class Commitment(TimestampMixin, Base):
    __tablename__ = "commitments"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=new_uuid)
    household_id: Mapped[UUID] = mapped_column(ForeignKey("households.id"), index=True)
    description: Mapped[str] = mapped_column(Text)
    from_member_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("family_members.id"), nullable=True
    )
    to_person_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    event_id: Mapped[UUID | None] = mapped_column(ForeignKey("events.id"), nullable=True)
    source_id: Mapped[UUID | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="open")
