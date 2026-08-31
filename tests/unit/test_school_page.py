"""School portal page tests: kid rail, module stacks, empty/failure states.

Real services over fake repositories (house pattern); the FastAPI dependency
override swaps ApplicationServices, so no PostgreSQL is touched.
"""

from dataclasses import replace
from datetime import date, time
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from nidaro.app import create_app
from nidaro.container import ApplicationServices
from nidaro.db.types import new_uuid, utc_now
from nidaro.household.models import FamilyMember, Household
from nidaro.household.repository import HouseholdRepository
from nidaro.household.service import HouseholdService
from nidaro.school.models import Lesson, Subject
from nidaro.school.repository import SchoolRepository
from nidaro.school.schemas import GradeInput, HomeworkInput, LessonInput, SubjectInput
from nidaro.school.service import SchoolService
from nidaro.web.dependencies import get_services

DAY = date.today()


class FakeHouseholdRepository(HouseholdRepository):
    def __init__(self, household=None):
        self.household = household

    async def get(self, household_id=None):
        return self.household


class FakeSchoolRepository(SchoolRepository):
    def __init__(self):
        self.subjects = {}
        self.lessons = {}
        self.grades = {}
        self.homework = {}

    async def upsert_subject(self, member_id, household_id, subject):
        key = (member_id, subject.code)
        existing = self.subjects.get(key)
        if existing is not None:
            return existing
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
            return existing
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


def _household_with_kids():
    household = Household(
        id=uuid4(),
        name="Morgan",
        timezone="Europe/Prague",
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    household.members = [
        FamilyMember(
            id=UUID("00000000-0000-0000-0000-0000000000a1"),
            household_id=household.id,
            name="Alex",
            role="parent",
            created_at=utc_now(),
            updated_at=utc_now(),
        ),
        FamilyMember(
            id=UUID("00000000-0000-0000-0000-0000000000c1"),
            household_id=household.id,
            name="Anna",
            role="child",
            created_at=utc_now(),
            updated_at=utc_now(),
        ),
        FamilyMember(
            id=UUID("00000000-0000-0000-0000-0000000000c2"),
            household_id=household.id,
            name="Tomáš",
            role="child",
            created_at=utc_now(),
            updated_at=utc_now(),
        ),
    ]
    return household


def _lesson(position, code="M", canceled=False, substitution=None):
    names = {"M": "Matematika", "TV": "Tělesná výchova", "AJ": "Anglický jazyk"}
    return LessonInput(
        subject=SubjectInput(code=code, name=names.get(code, code)),
        start=time(8 + position, 0),
        end=time(8 + position, 45),
        position=position,
        teacher="Mgr. Vávrová",
        room="204",
        canceled=canceled,
        substitution=substitution,
    )


def _services(household, school_repo):
    base = ApplicationServices.build(async_sessionmaker())
    return replace(
        base,
        household=HouseholdService(FakeHouseholdRepository(household)),
        school=SchoolService(school_repo),
    )


def _client(services):
    app = create_app()
    app.dependency_overrides[get_services] = lambda: services
    return TestClient(app)


def test_page_lists_only_children_in_the_kid_rail():
    household = _household_with_kids()
    response = _client(_services(household, FakeSchoolRepository())).get("/school")

    assert response.status_code == 200
    assert "Anna" in response.text
    assert "Tomáš" in response.text
    assert "Alex" not in response.text.split("sp-kids")[1].split("school-stacks")[0]


def test_page_renders_today_lessons_with_substitutions_and_next_up():
    household = _household_with_kids()
    anna = household.members[1]
    school_repo = FakeSchoolRepository()

    import asyncio

    async def land():
        service = SchoolService(school_repo)
        await service.apply_day(
            anna.id,
            household.id,
            DAY,
            [
                _lesson(1),
                _lesson(2, code="TV", canceled=True, substitution="Canceled today"),
                _lesson(3, code="AJ"),
            ],
        )

    asyncio.run(land())

    response = _client(_services(household, school_repo)).get(f"/school?kid={anna.id}")
    body = response.text

    assert response.status_code == 200
    assert "Canceled" in body
    assert "next up" in body
    assert body.count("sp-row--dead") == 1


def test_page_renders_grades_and_homework_with_empty_states():
    household = _household_with_kids()
    anna = household.members[1]
    school_repo = FakeSchoolRepository()

    import asyncio

    async def land():
        service = SchoolService(school_repo)
        await service.apply_grades(
            anna.id,
            household.id,
            [
                GradeInput(
                    external_id="g1",
                    subject=SubjectInput(code="M", name="Matematika"),
                    value="1",
                    weight=2,
                    graded_on=DAY,
                    confirmed=False,
                )
            ],
        )
        await service.apply_homework(
            anna.id,
            household.id,
            [
                HomeworkInput(
                    external_id="h1",
                    subject=SubjectInput(code="M", name="Matematika"),
                    text="Worksheet p. 34",
                    due_on=DAY,
                    attachments=["sheet.pdf"],
                )
            ],
        )

    asyncio.run(land())

    response = _client(_services(household, school_repo)).get(f"/school?kid={anna.id}")
    body = response.text

    assert "sp-grade" in body
    assert "not confirmed" in body
    assert "Worksheet p. 34" in body
    assert "sheet.pdf" in body


def test_empty_household_data_shows_waiting_states():
    household = _household_with_kids()
    response = _client(_services(household, FakeSchoolRepository())).get("/school")

    assert response.status_code == 200
    assert "No school data yet" in response.text
    assert "No gather yet" in response.text
    assert "Nothing due — all clear." in response.text


def test_unknown_kid_falls_back_to_first_child():
    household = _household_with_kids()
    response = _client(_services(household, FakeSchoolRepository())).get(f"/school?kid={uuid4()}")

    assert response.status_code == 200
    assert response.text.index("Anna") < response.text.index("Tomáš")


def test_page_without_seeded_household_404s():
    client = _client(_services(None, FakeSchoolRepository()))
    response = client.get("/school")

    assert response.status_code == 404
