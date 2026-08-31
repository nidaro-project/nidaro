"""School repository integration tests: real PostgreSQL, real flush ordering.

Covers what the fake-repository unit tests cannot: the DELETE-then-INSERT
ordering inside `replace_lessons` against the (member, day, position) unique
constraint when a day is landed twice.

Follows the house integration-test convention (see test_database.py): the test
skips itself wherever the infrastructure is not there — no reachable
PostgreSQL, schema not migrated, or no seeded household — and runs fully where
it is (local development with `podman compose up` + `alembic upgrade` + seed).
"""

from datetime import date, time

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError, ProgrammingError

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
        try:
            try:
                async with engine.connect() as conn:
                    migrated = (
                        await conn.execute(text("select to_regclass('family_members')"))
                    ).scalar()
            except (OperationalError, ProgrammingError) as exc:
                pytest.skip(f"PostgreSQL not reachable or not migrated: {exc}")
            if migrated is None:
                pytest.skip("Database schema not migrated — run alembic upgrade head")
            sessions = create_session_factory(engine)
            async with sessions() as session:
                member = (await session.scalars(select(FamilyMember).limit(1))).first()
                if member is None:
                    pytest.skip("No seeded household member — run nidaro-seed")
                household = await session.get(Household, member.household_id)

            repo = SchoolRepository(sessions)
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
            return first, second, stored
        finally:
            await engine.dispose()

    import asyncio

    first, second, stored = asyncio.run(scenario())
    assert len(first) == 2
    assert len(second) == 1
    assert [row.position for row in stored] == [1]
