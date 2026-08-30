"""School domain seam tests: SchoolService over a fake repository.

The seam was fixed by [portal-2]/[portal-4]: the gatherer lands fetched data
through apply_* methods; the portal page reads through *_for methods. School
rows carry member_id only — account/linkage mechanics stay in the connector
config (see [portal-3]).
"""

from datetime import date, time
from uuid import uuid4

import pytest

from nidaro.school.schemas import GradeInput, HomeworkInput, LessonInput, SubjectInput
from nidaro.school.service import SchoolService

DAY = date(2026, 5, 13)


def lesson_input(position: int, code: str = "M", canceled: bool = False) -> LessonInput:
    return LessonInput(
        subject=SubjectInput(code=code, name="Matematika", teacher="Mgr. Vávrová"),
        start=time(8, 0),
        end=time(8, 45),
        position=position,
        teacher="Mgr. Vávrová",
        room="204",
        canceled=canceled,
        substitution="Canceled today" if canceled else None,
    )


def grade_input(external_id: str = "g1", value: str = "1", graded_on: date = DAY) -> GradeInput:
    return GradeInput(
        external_id=external_id,
        subject=SubjectInput(code="M", name="Matematika"),
        value=value,
        weight=2,
        graded_on=graded_on,
        teacher="Mgr. Vávrová",
        confirmed=True,
    )


def homework_input(external_id: str = "h1", due: date | None = None) -> HomeworkInput:
    return HomeworkInput(
        external_id=external_id,
        subject=SubjectInput(code="AJ", name="Anglický jazyk"),
        text="Vocabulary unit 12",
        due_on=due,
        attachments=["list.pdf"],
    )


class FakeSchoolRepository:
    """In-memory stand-in with the same shape as SchoolRepository."""

    def __init__(self):
        self.subjects: dict[tuple, object] = {}
        self.lessons: dict[tuple, list] = {}
        self.grades: dict[tuple, object] = {}
        self.homework: dict[tuple, object] = {}

    async def upsert_subject(self, member_id, household_id, subject):
        key = (member_id, subject.code)
        existing = self.subjects.get(key)
        if existing is not None:
            existing.name = subject.name
            existing.teacher = subject.teacher
            return existing
        from nidaro.db.types import new_uuid, utc_now
        from nidaro.school.models import Subject

        row = Subject(
            id=new_uuid(),
            household_id=household_id,
            member_id=member_id,
            code=subject.code,
            name=subject.name,
            teacher=subject.teacher,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self.subjects[key] = row
        return row

    async def replace_lessons(self, member_id, household_id, day, items):
        from nidaro.db.types import new_uuid, utc_now
        from nidaro.school.models import Lesson

        rows = []
        for lesson_input, subject_id in items:
            row = Lesson(
                id=new_uuid(),
                household_id=household_id,
                member_id=member_id,
                day=day,
                subject_id=subject_id,
                start=lesson_input.start,
                end=lesson_input.end,
                position=lesson_input.position,
                teacher=lesson_input.teacher,
                room=lesson_input.room,
                canceled=lesson_input.canceled,
                substitution=lesson_input.substitution,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            row.subject = self.subjects[(member_id, lesson_input.subject.code)]
            rows.append(row)
        self.lessons[(member_id, day)] = rows
        return rows

    async def lessons_on(self, member_id, day):
        return sorted(self.lessons.get((member_id, day), []), key=lambda r: r.position)

    async def subjects_for_member(self, member_id):
        return [s for (m, _), s in sorted(self.subjects.items()) if m == member_id]

    async def upsert_grade(self, member_id, household_id, grade, subject_id):
        key = (member_id, grade.external_id)
        existing = self.grades.get(key)
        if existing is not None:
            existing.value = grade.value
            existing.weight = grade.weight
            existing.confirmed = grade.confirmed
            return existing
        from nidaro.db.types import new_uuid, utc_now
        from nidaro.school.models import Grade

        row = Grade(
            id=new_uuid(),
            household_id=household_id,
            member_id=member_id,
            subject_id=subject_id,
            external_id=grade.external_id,
            value=grade.value,
            weight=grade.weight,
            graded_on=grade.graded_on,
            teacher=grade.teacher,
            confirmed=grade.confirmed,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        row.subject = self.subjects[(member_id, grade.subject.code)]
        self.grades[key] = row
        return row

    async def grades_for_member(self, member_id):
        return sorted(
            (g for (m, _), g in self.grades.items() if m == member_id),
            key=lambda r: (r.graded_on, r.created_at),
            reverse=True,
        )

    async def upsert_homework(self, member_id, household_id, homework, subject_id):
        key = (member_id, homework.external_id)
        if key in self.homework:
            return self.homework[key]
        from nidaro.db.types import new_uuid, utc_now
        from nidaro.school.models import Homework

        row = Homework(
            id=new_uuid(),
            household_id=household_id,
            member_id=member_id,
            subject_id=subject_id,
            external_id=homework.external_id,
            text=homework.text,
            due_on=homework.due_on,
            attachments=homework.attachments,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        row.subject = self.subjects[(member_id, homework.subject.code)]
        self.homework[key] = row
        return row

    async def homework_for_member(self, member_id):
        return sorted(
            (h for (m, _), h in self.homework.items() if m == member_id),
            key=lambda r: (r.due_on is None, r.due_on or date.max, r.created_at),
        )


@pytest.fixture
def service():
    return SchoolService(FakeSchoolRepository())


@pytest.fixture
def member_id():
    return uuid4()


@pytest.fixture
def household_id():
    return uuid4()


@pytest.mark.anyio
async def test_apply_day_lands_materialized_lessons(service, member_id, household_id):
    lessons = await service.apply_day(
        member_id, household_id, DAY, [lesson_input(1), lesson_input(2, code="ČJ")]
    )

    assert [row.position for row in lessons] == [1, 2]
    assert lessons[0].subject.code == "M"
    assert lessons[1].subject.code == "ČJ"
    assert lessons[0].canceled is False


@pytest.mark.anyio
async def test_apply_day_replaces_the_day_instead_of_duplicating(service, member_id, household_id):
    await service.apply_day(member_id, household_id, DAY, [lesson_input(1)])
    lessons = await service.apply_day(
        member_id, household_id, DAY, [lesson_input(1), lesson_input(2)]
    )

    stored = await service.lessons_on(member_id, DAY)
    assert len(stored) == 2
    assert [row.id for row in stored] == [row.id for row in lessons]


@pytest.mark.anyio
async def test_lessons_keep_cancellation(service, member_id, household_id):
    lessons = await service.apply_day(
        member_id, household_id, DAY, [lesson_input(1, canceled=True)]
    )

    stored = await service.lessons_on(member_id, DAY)
    assert stored[0].canceled is True
    assert stored[0].substitution == "Canceled today"
    assert lessons[0].canceled is True


@pytest.mark.anyio
async def test_apply_day_shares_one_subject_row_per_code(service, member_id, household_id):
    await service.apply_day(member_id, household_id, DAY, [lesson_input(1), lesson_input(2)])

    subjects = await service.subjects_for(member_id)
    assert [s.code for s in subjects] == ["M"]


@pytest.mark.anyio
async def test_apply_grades_upserts_by_external_id(service, member_id, household_id):
    first = await service.apply_grades(member_id, household_id, [grade_input(value="1")])
    second = await service.apply_grades(member_id, household_id, [grade_input(value="2")])

    stored = await service.grades_for(member_id)
    assert len(stored) == 1
    assert stored[0].value == "2"
    assert first[0].id == second[0].id == stored[0].id


@pytest.mark.anyio
async def test_grades_read_newest_first(service, member_id, household_id):
    older = grade_input("g1", graded_on=date(2026, 5, 6))
    newer = grade_input("g2")
    await service.apply_grades(member_id, household_id, [older, newer])

    stored = await service.grades_for(member_id)
    assert [g.external_id for g in stored] == ["g2", "g1"]


@pytest.mark.anyio
async def test_apply_homework_upserts_and_reads_by_due_date(service, member_id, household_id):
    await service.apply_homework(
        member_id,
        household_id,
        [homework_input("h2", due=date(2026, 5, 19)), homework_input("h1", due=date(2026, 5, 15))],
    )
    await service.apply_homework(member_id, household_id, [homework_input("h1")])

    stored = await service.homework_for(member_id)
    assert [h.external_id for h in stored] == ["h1", "h2"]
    assert stored[0].attachments == ["list.pdf"]


@pytest.mark.anyio
async def test_homework_without_due_date_sorts_last(service, member_id, household_id):
    await service.apply_homework(
        member_id,
        household_id,
        [homework_input("h-late", due=None), homework_input("h-soon", due=date(2026, 5, 15))],
    )

    stored = await service.homework_for(member_id)
    assert [h.external_id for h in stored] == ["h-soon", "h-late"]


@pytest.mark.anyio
async def test_subject_updates_flow_to_existing_row(service, member_id, household_id):
    await service.apply_day(member_id, household_id, DAY, [lesson_input(1)])
    renamed = lesson_input(2)
    renamed.subject = SubjectInput(code="M", name="Matematika a seminář", teacher="Mgr. Nová")

    await service.apply_day(member_id, household_id, DAY, [lesson_input(1), renamed])

    subjects = await service.subjects_for(member_id)
    assert len(subjects) == 1
    assert subjects[0].name == "Matematika a seminář"
    assert subjects[0].teacher == "Mgr. Nová"
