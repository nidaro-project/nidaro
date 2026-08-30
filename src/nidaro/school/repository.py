from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import joinedload

from nidaro.school.models import Grade, Homework, Lesson, Subject
from nidaro.school.schemas import GradeInput, HomeworkInput, LessonInput, SubjectInput


class SchoolRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def upsert_subject(
        self, member_id: UUID, household_id: UUID, subject: SubjectInput
    ) -> Subject:
        async with self.sessions.begin() as session:
            row = await session.scalar(
                select(Subject).where(Subject.member_id == member_id, Subject.code == subject.code)
            )
            if row is None:
                row = Subject(
                    household_id=household_id,
                    member_id=member_id,
                    code=subject.code,
                    name=subject.name,
                    teacher=subject.teacher,
                )
                session.add(row)
                await session.flush()
            else:
                row.name = subject.name
                row.teacher = subject.teacher
                await session.flush()
            return row

    async def replace_lessons(
        self,
        member_id: UUID,
        household_id: UUID,
        day: date,
        items: list[tuple[LessonInput, UUID]],
    ) -> list[Lesson]:
        async with self.sessions.begin() as session:
            existing = await session.scalars(
                select(Lesson).where(Lesson.member_id == member_id, Lesson.day == day)
            )
            for row in existing:
                await session.delete(row)
            rows = [
                Lesson(
                    household_id=household_id,
                    member_id=member_id,
                    day=day,
                    subject_id=subject_id,
                    start=lesson.start,
                    end=lesson.end,
                    position=lesson.position,
                    teacher=lesson.teacher,
                    room=lesson.room,
                    canceled=lesson.canceled,
                    substitution=lesson.substitution,
                )
                for lesson, subject_id in items
            ]
            session.add_all(rows)
            await session.flush()
            for row in rows:
                await session.refresh(row, ["subject"])
            return rows

    async def lessons_on(self, member_id: UUID, day: date) -> list[Lesson]:
        async with self.sessions() as session:
            result = await session.scalars(
                select(Lesson)
                .options(joinedload(Lesson.subject))
                .where(Lesson.member_id == member_id, Lesson.day == day)
                .order_by(Lesson.position)
            )
            return list(result)

    async def subjects_for_member(self, member_id: UUID) -> list[Subject]:
        async with self.sessions() as session:
            result = await session.scalars(
                select(Subject).where(Subject.member_id == member_id).order_by(Subject.code)
            )
            return list(result)

    async def upsert_grade(
        self, member_id: UUID, household_id: UUID, grade: GradeInput, subject_id: UUID
    ) -> Grade:
        async with self.sessions.begin() as session:
            row = await session.scalar(
                select(Grade).where(
                    Grade.member_id == member_id, Grade.external_id == grade.external_id
                )
            )
            if row is None:
                row = Grade(
                    household_id=household_id,
                    member_id=member_id,
                    subject_id=subject_id,
                    external_id=grade.external_id,
                    value=grade.value,
                    weight=grade.weight,
                    graded_on=grade.graded_on,
                    teacher=grade.teacher,
                    confirmed=grade.confirmed,
                )
                session.add(row)
            else:
                row.subject_id = subject_id
                row.value = grade.value
                row.weight = grade.weight
                row.graded_on = grade.graded_on
                row.teacher = grade.teacher
                row.confirmed = grade.confirmed
            await session.flush()
            await session.refresh(row, ["subject"])
            return row

    async def grades_for_member(self, member_id: UUID) -> list[Grade]:
        async with self.sessions() as session:
            result = await session.scalars(
                select(Grade)
                .options(joinedload(Grade.subject))
                .where(Grade.member_id == member_id)
                .order_by(Grade.graded_on.desc(), Grade.created_at.desc())
            )
            return list(result)

    async def upsert_homework(
        self, member_id: UUID, household_id: UUID, homework: HomeworkInput, subject_id: UUID
    ) -> Homework:
        async with self.sessions.begin() as session:
            row = await session.scalar(
                select(Homework).where(
                    Homework.member_id == member_id,
                    Homework.external_id == homework.external_id,
                )
            )
            if row is None:
                row = Homework(
                    household_id=household_id,
                    member_id=member_id,
                    subject_id=subject_id,
                    external_id=homework.external_id,
                    text=homework.text,
                    due_on=homework.due_on,
                    attachments=homework.attachments,
                )
                session.add(row)
            else:
                row.subject_id = subject_id
                row.text = homework.text
                row.due_on = homework.due_on
                row.attachments = homework.attachments
            await session.flush()
            await session.refresh(row, ["subject"])
            return row

    async def homework_for_member(self, member_id: UUID) -> list[Homework]:
        async with self.sessions() as session:
            result = await session.scalars(
                select(Homework)
                .options(joinedload(Homework.subject))
                .where(Homework.member_id == member_id)
                .order_by(Homework.due_on.asc().nulls_last(), Homework.created_at.desc())
            )
            return list(result)
