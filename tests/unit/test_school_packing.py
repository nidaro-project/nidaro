"""What-to-pack: service packing logic + page/config surface.

The packing overview is derived, never stored: lessons already materialized in
the school domain + a per-kid, per-subject equipment list (household-maintained)
yield what a kid needs for today and tomorrow. Canceled lessons never pack.
"""

from datetime import date, time
from uuid import UUID, uuid4

import pytest

from nidaro.school.schemas import LessonInput, SubjectInput
from nidaro.school.service import SchoolService

TODAY = date(2026, 5, 13)
TOMORROW = date(2026, 5, 14)


def lesson(position: int, code: str, canceled: bool = False, start_hour: int = 8) -> LessonInput:
    names = {
        "M": "Matematika",
        "TV": "Tělesná výchova",
        "PČ": "Pracovní činnosti",
        "ČJ": "Český jazyk",
    }
    return LessonInput(
        subject=SubjectInput(code=code, name=names.get(code, code)),
        start=time(start_hour, 0),
        end=time(start_hour, 45),
        position=position,
        canceled=canceled,
    )


class FakeSchoolRepository:
    """Same shape as SchoolRepository, in-memory; lessons stored per (member, day)."""

    def __init__(self):
        self.subjects: dict[UUID, dict] = {}
        self.lessons: dict[tuple, list] = {}

    def _subject_row(self, member_id, household_id, subject_input):
        from nidaro.db.types import new_uuid, utc_now
        from nidaro.school.models import Subject

        row = Subject(
            id=new_uuid(),
            household_id=household_id,
            member_id=member_id,
            code=subject_input.code,
            name=subject_input.name,
            teacher=subject_input.teacher,
            equipment=[],
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self.subjects[row.id] = {
            "row": row,
            "member_id": member_id,
            "input": subject_input,
        }
        return row

    async def upsert_subject(self, member_id, household_id, subject):
        for stored in self.subjects.values():
            if stored["member_id"] == member_id and stored["input"].code == subject.code:
                stored["input"] = subject
                return stored["row"]
        return self._subject_row(member_id, household_id, subject)

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
            row.subject = self.subjects[subject_id]["row"]
            rows.append(row)
        self.lessons[(member_id, day)] = rows
        return rows

    async def lessons_on(self, member_id, day):
        return sorted(self.lessons.get((member_id, day), []), key=lambda r: r.position)

    async def subjects_for_member(self, member_id):
        return [
            s["row"]
            for s in sorted(self.subjects.values(), key=lambda s: s["input"].code)
            if s["member_id"] == member_id
        ]

    async def update_equipment(self, member_id, subject_id, equipment):
        stored = self.subjects.get(subject_id)
        if stored is None or stored["member_id"] != member_id:
            return None
        stored["row"].equipment = list(equipment)
        return stored["row"]


@pytest.fixture
def service():
    return SchoolService(FakeSchoolRepository())


@pytest.fixture
def member_id():
    return uuid4()


@pytest.fixture
def household_id():
    return uuid4()


async def _land(service, member_id, household_id, day, lessons):
    await service.apply_day(member_id, household_id, day, lessons)


@pytest.mark.anyio
async def test_pack_list_collects_equipment_for_both_days(service, member_id, household_id):
    await _land(service, member_id, household_id, TODAY, [lesson(1, "M"), lesson(2, "TV")])
    await _land(service, member_id, household_id, TOMORROW, [lesson(1, "PČ")])
    tv = next(s for s in await service.subjects_for(member_id) if s.code == "TV")
    await service.set_equipment(member_id, tv.id, ["Gym kit"])

    packing = await service.pack_list(member_id, [TODAY, TOMORROW])

    assert [p.day for p in packing] == [TODAY, TOMORROW]
    assert [i.subject_code for i in packing[0].entries] == ["M", "TV"]
    assert packing[0].entries[1].items == ["Gym kit"]
    assert packing[1].entries[0].items == []


@pytest.mark.anyio
async def test_pack_list_skips_canceled_lessons(service, member_id, household_id):
    await _land(
        service,
        member_id,
        household_id,
        TODAY,
        [lesson(1, "M"), lesson(2, "TV", canceled=True)],
    )
    tv = next(s for s in await service.subjects_for(member_id) if s.code == "TV")
    await service.set_equipment(member_id, tv.id, ["Gym kit"])

    packing = await service.pack_list(member_id, [TODAY])

    assert [i.subject_code for i in packing[0].entries] == ["M"]


@pytest.mark.anyio
async def test_pack_list_dedupes_repeated_subjects(service, member_id, household_id):
    await _land(
        service,
        member_id,
        household_id,
        TODAY,
        [lesson(1, "M"), lesson(2, "M", start_hour=10)],
    )

    packing = await service.pack_list(member_id, [TODAY])

    assert [i.subject_code for i in packing[0].entries] == ["M"]


@pytest.mark.anyio
async def test_pack_list_on_empty_day_has_no_entries(service, member_id, household_id):
    packing = await service.pack_list(member_id, [TODAY])

    assert packing[0].entries == []


@pytest.mark.anyio
async def test_set_equipment_updates_only_that_subject(service, member_id, household_id):
    await _land(service, member_id, household_id, TODAY, [lesson(1, "M"), lesson(2, "TV")])
    subjects = await service.subjects_for(member_id)

    updated = await service.set_equipment(member_id, subjects[0].id, ["Worksheet", "Compass"])

    assert updated is not None
    assert updated.equipment == ["Worksheet", "Compass"]
    still = await service.subjects_for(member_id)
    assert still[1].equipment == []


@pytest.mark.anyio
async def test_set_equipment_on_foreign_subject_is_none(service, member_id, household_id):
    await _land(service, member_id, household_id, TODAY, [lesson(1, "M")])

    assert await service.set_equipment(member_id, uuid4(), ["Gym kit"]) is None
