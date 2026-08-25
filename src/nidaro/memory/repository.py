from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nidaro.memory.models import Fact
from nidaro.memory.schemas import RememberFactRequest


class FactRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def create(self, request: RememberFactRequest) -> Fact:
        async with self.sessions.begin() as session:
            fact = Fact(**request.model_dump())
            session.add(fact)
            await session.flush()
            return fact

    async def search(self, household_id: UUID, query: str, limit: int) -> list[Fact]:
        async with self.sessions() as session:
            statement = (
                select(Fact)
                .where(Fact.household_id == household_id)
                .where(or_(Fact.content.ilike(f"%{query}%"), Fact.fact_type.ilike(f"%{query}%")))
                .order_by(Fact.created_at.desc())
                .limit(limit)
            )
            return list(await session.scalars(statement))

    async def recent(self, household_id: UUID, limit: int = 10) -> list[Fact]:
        async with self.sessions() as session:
            return list(
                await session.scalars(
                    select(Fact)
                    .where(Fact.household_id == household_id)
                    .order_by(Fact.created_at.desc())
                    .limit(limit)
                )
            )
