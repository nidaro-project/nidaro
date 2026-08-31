from datetime import date, datetime, time
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator


class SubjectInput(BaseModel):
    code: str
    name: str
    teacher: str | None = None


class LessonInput(BaseModel):
    subject: SubjectInput
    start: time
    end: time
    position: int
    teacher: str | None = None
    room: str | None = None
    canceled: bool = False
    substitution: str | None = None


class GradeInput(BaseModel):
    external_id: str
    subject: SubjectInput
    value: str
    weight: int = 1
    graded_on: date
    teacher: str | None = None
    confirmed: bool = False


class HomeworkInput(BaseModel):
    external_id: str
    subject: SubjectInput
    text: str
    due_on: date | None = None
    attachments: list[str] = []


class SubjectView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    member_id: UUID
    code: str
    name: str
    teacher: str | None
    equipment: list[str] = []

    @field_validator("equipment", mode="before")
    @classmethod
    def none_is_empty(cls, value: list[str] | None) -> list[str]:
        return value or []


class LessonView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    updated_at: datetime

    id: UUID
    member_id: UUID
    day: date
    start: time
    end: time
    position: int
    teacher: str | None
    room: str | None
    canceled: bool
    substitution: str | None
    subject: SubjectView | None


class GradeView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    updated_at: datetime

    id: UUID
    member_id: UUID
    external_id: str
    value: str
    weight: int
    graded_on: date
    teacher: str | None
    confirmed: bool
    subject: SubjectView | None


class HomeworkView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    updated_at: datetime

    id: UUID
    member_id: UUID
    external_id: str
    text: str
    due_on: date | None
    attachments: list[str]
    subject: SubjectView | None


class AppliedDay(BaseModel):
    day: date
    member_id: UUID
    lessons: list[LessonView]


class PackItemView(BaseModel):
    subject_code: str
    subject_name: str
    items: list[str]


class PackDayView(BaseModel):
    day: date
    entries: list[PackItemView]
