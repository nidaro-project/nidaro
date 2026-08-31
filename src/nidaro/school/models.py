from datetime import date, time
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nidaro.db.base import Base, TimestampMixin
from nidaro.db.types import new_uuid


class Subject(TimestampMixin, Base):
    __tablename__ = "school_subjects"
    __table_args__ = (UniqueConstraint("member_id", "code"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=new_uuid)
    household_id: Mapped[UUID] = mapped_column(ForeignKey("households.id"), index=True)
    member_id: Mapped[UUID] = mapped_column(
        ForeignKey("family_members.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(250))
    teacher: Mapped[str | None] = mapped_column(String(200), nullable=True)
    equipment: Mapped[list[Any]] = mapped_column(JSONB, default=list)


class Lesson(TimestampMixin, Base):
    __tablename__ = "school_lessons"
    __table_args__ = (UniqueConstraint("member_id", "day", "position"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=new_uuid)
    household_id: Mapped[UUID] = mapped_column(ForeignKey("households.id"), index=True)
    member_id: Mapped[UUID] = mapped_column(
        ForeignKey("family_members.id", ondelete="CASCADE"), index=True
    )
    day: Mapped[date] = mapped_column(Date, index=True)
    subject_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("school_subjects.id", ondelete="SET NULL"), nullable=True
    )
    start: Mapped[time] = mapped_column()
    end: Mapped[time] = mapped_column()
    position: Mapped[int] = mapped_column(Integer)
    teacher: Mapped[str | None] = mapped_column(String(200), nullable=True)
    room: Mapped[str | None] = mapped_column(String(50), nullable=True)
    canceled: Mapped[bool] = mapped_column(Boolean, default=False)
    substitution: Mapped[str | None] = mapped_column(Text, nullable=True)

    subject: Mapped["Subject | None"] = relationship(lazy="joined")


class Grade(TimestampMixin, Base):
    __tablename__ = "school_grades"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=new_uuid)
    household_id: Mapped[UUID] = mapped_column(ForeignKey("households.id"), index=True)
    member_id: Mapped[UUID] = mapped_column(
        ForeignKey("family_members.id", ondelete="CASCADE"), index=True
    )
    subject_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("school_subjects.id", ondelete="SET NULL"), nullable=True
    )
    external_id: Mapped[str] = mapped_column(String(250), index=True)
    value: Mapped[str] = mapped_column(String(20))
    weight: Mapped[int] = mapped_column(Integer, default=1)
    graded_on: Mapped[date] = mapped_column(Date)
    teacher: Mapped[str | None] = mapped_column(String(200), nullable=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)

    subject: Mapped["Subject | None"] = relationship(lazy="joined")


class Homework(TimestampMixin, Base):
    __tablename__ = "school_homework"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=new_uuid)
    household_id: Mapped[UUID] = mapped_column(ForeignKey("households.id"), index=True)
    member_id: Mapped[UUID] = mapped_column(
        ForeignKey("family_members.id", ondelete="CASCADE"), index=True
    )
    subject_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("school_subjects.id", ondelete="SET NULL"), nullable=True
    )
    external_id: Mapped[str] = mapped_column(String(250), index=True)
    text: Mapped[str] = mapped_column(Text)
    due_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    attachments: Mapped[list[Any]] = mapped_column(JSONB, default=list)

    subject: Mapped["Subject | None"] = relationship(lazy="joined")
