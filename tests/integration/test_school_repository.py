"""School repository integration tests: real PostgreSQL, real flush ordering.

Covers what the fake-repository unit tests cannot: the DELETE-then-INSERT
ordering inside `replace_lessons` against the (member, day, position) unique
constraint when a day is landed twice.
"""

from datetime import date, time

import pytest
from sqlalchemy import select

from nidaro.config import get_settings
from nidaro.db.engine import create_engine, create_session_factory
from nidaro.household.models import FamilyMember, Household
from nidaro.school.repository import SchoolRepository
from nidaro.school.schemas import LessonInput, SubjectInput

pytestmark = [pytest.mark.integration]


def lesson(position: int, code: str, name: str) -> LessonInput:
    return LessonInput(
        subject=SubjectInput(code=code, name=name),
        start=time(8 + position, 0),
        end=time(8 + position, 45),
        position=position,
    )


def test_replace_lessons_lands_the_same_day_twice():
    """Second landing of one day must replace, not collide (regression: the
    same-flush insert-before-delete ordering violated the unique key)."""

    async def scenario():
        engine = create_engine(get_settings())
        sessions = create_session_factory(engine)
        repo = SchoolRepository(sessions)
        async with sessions() as session:
            member = (await session.scalars(select(FamilyMember).limit(1))).first()
            household = await session.get(Household, member.household_id)
        member_id, household_id = member.id, household.id
        day = date(2026, 1, 20)

        first = await repo.replace_lessons(
            member_id,
            household_id,
            day,
            [(lesson(1, "M", "Matematika"), None), (lesson(2, "TV", "Tělesná výchova"), None)],
        )
        second = await repo.replace_lessons(
            member_id,
            household_id,
            day,
            [(lesson(1, "M", "Matematika"), None)],
        )
        stored = await repo.lessons_on(member_id, day)
        # leave the seeded household untouched
        await repo.replace_lessons(member_id, household_id, day, [])
        await engine.dispose()
        return first, second, stored

    import asyncio

    first, second, stored = asyncio.run(scenario())
    assert len(first) == 2
    assert len(second) == 1
    assert [row.position for row in stored] == [1]
