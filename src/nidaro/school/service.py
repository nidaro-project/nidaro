from datetime import date
from typing import Protocol
from uuid import UUID

from nidaro.school.models import Grade, Homework, Lesson, Subject
from nidaro.school.schemas import (
    GradeInput,
    GradeView,
    HomeworkInput,
    HomeworkView,
    LessonInput,
    LessonView,
    SubjectInput,
    SubjectView,
)


class SchoolRepositoryProtocol(Protocol):
    async def upsert_subject(
        self, member_id: UUID, household_id: UUID, subject: SubjectInput
    ) -> Subject: ...

    async def replace_lessons(
        self,
        member_id: UUID,
        household_id: UUID,
        day: date,
        items: list[tuple[LessonInput, UUID]],
    ) -> list[Lesson]: ...

    async def lessons_on(self, member_id: UUID, day: date) -> list[Lesson]: ...

    async def subjects_for_member(self, member_id: UUID) -> list[Subject]: ...

    async def upsert_grade(
        self, member_id: UUID, household_id: UUID, grade: GradeInput, subject_id: UUID
    ) -> Grade: ...

    async def grades_for_member(self, member_id: UUID) -> list[Grade]: ...

    async def upsert_homework(
        self, member_id: UUID, household_id: UUID, homework: HomeworkInput, subject_id: UUID
    ) -> Homework: ...

    async def homework_for_member(self, member_id: UUID) -> list[Homework]: ...


class SchoolService:
    """The seam the gatherer lands through (apply_*) and the portal reads through (*_for)."""

    def __init__(self, repository: SchoolRepositoryProtocol) -> None:
        self.repository = repository

    async def apply_day(
        self, member_id: UUID, household_id: UUID, day: date, lessons: list[LessonInput]
    ) -> list[LessonView]:
        """Land one kid's materialized day: subjects upserted, the day's lessons replaced."""
        items: list[tuple[LessonInput, UUID]] = []
        for lesson in lessons:
            subject = await self.repository.upsert_subject(member_id, household_id, lesson.subject)
            items.append((lesson, subject.id))
        rows = await self.repository.replace_lessons(member_id, household_id, day, items)
        return [LessonView.model_validate(row) for row in rows]

    async def apply_grades(
        self, member_id: UUID, household_id: UUID, grades: list[GradeInput]
    ) -> list[GradeView]:
        views: list[GradeView] = []
        for grade in grades:
            subject = await self.repository.upsert_subject(member_id, household_id, grade.subject)
            row = await self.repository.upsert_grade(member_id, household_id, grade, subject.id)
            views.append(GradeView.model_validate(row))
        return views

    async def apply_homework(
        self, member_id: UUID, household_id: UUID, homework: list[HomeworkInput]
    ) -> list[HomeworkView]:
        views: list[HomeworkView] = []
        for item in homework:
            subject = await self.repository.upsert_subject(member_id, household_id, item.subject)
            row = await self.repository.upsert_homework(member_id, household_id, item, subject.id)
            views.append(HomeworkView.model_validate(row))
        return views

    async def lessons_on(self, member_id: UUID, day: date) -> list[LessonView]:
        return [LessonView.model_validate(l) for l in await self.repository.lessons_on(member_id, day)]

    async def subjects_for(self, member_id: UUID) -> list[SubjectView]:
        return [
            SubjectView.model_validate(s) for s in await self.repository.subjects_for_member(member_id)
        ]

    async def grades_for(self, member_id: UUID) -> list[GradeView]:
        return [
            GradeView.model_validate(g) for g in await self.repository.grades_for_member(member_id)
        ]

    async def homework_for(self, member_id: UUID) -> list[HomeworkView]:
        return [
            HomeworkView.model_validate(h)
            for h in await self.repository.homework_for_member(member_id)
        ]
