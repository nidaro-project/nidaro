import asyncio

from nidaro.config import get_settings
from nidaro.db.engine import create_engine, create_session_factory
from nidaro.household.repository import HouseholdRepository
from nidaro.household.schemas import CreateHouseholdRequest


async def seed() -> None:
    settings = get_settings()
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    repository = HouseholdRepository(sessions)
    household = await repository.get()
    if household is None:
        household = await repository.create(CreateHouseholdRequest(timezone=settings.timezone))
    existing = {member.name for member in household.members}
    for name, role in (("Alex", "parent"), ("Emma", "child")):
        if name not in existing:
            await repository.add_member(household.id, name, role)
    await engine.dispose()


def main() -> None:
    asyncio.run(seed())
