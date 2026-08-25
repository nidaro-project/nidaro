from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from nidaro.household.models import FamilyMember, Household
from nidaro.household.schemas import CreateHouseholdRequest


class HouseholdRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def get(self, household_id: UUID | None = None) -> Household | None:
        async with self.sessions() as session:
            query = (
                select(Household)
                .options(selectinload(Household.members))
                .order_by(Household.created_at)
            )
            if household_id:
                query = query.where(Household.id == household_id)
            return (await session.scalars(query)).first()

    async def create(self, request: CreateHouseholdRequest) -> Household:
        async with self.sessions.begin() as session:
            household = Household(name=request.name, timezone=request.timezone)
            session.add(household)
            await session.flush()
            return household

    async def add_member(self, household_id: UUID, name: str, role: str) -> FamilyMember:
        async with self.sessions.begin() as session:
            member = FamilyMember(household_id=household_id, name=name, role=role)
            session.add(member)
            await session.flush()
            return member
