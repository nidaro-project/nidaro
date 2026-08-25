from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nidaro.commitments.models import Commitment
from nidaro.commitments.schemas import RecordCommitmentRequest


class CommitmentRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def create(self, request: RecordCommitmentRequest) -> Commitment:
        async with self.sessions.begin() as session:
            commitment = Commitment(**request.model_dump())
            session.add(commitment)
            await session.flush()
            return commitment

    async def open(self, household_id: UUID) -> list[Commitment]:
        async with self.sessions() as session:
            return list(
                await session.scalars(
                    select(Commitment)
                    .where(Commitment.household_id == household_id, Commitment.status == "open")
                    .order_by(Commitment.due_at)
                )
            )
