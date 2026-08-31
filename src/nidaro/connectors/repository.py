from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nidaro.connectors.models import ConnectorCursor


class ConnectorCursorRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def get(self, household_id: UUID, connector: str) -> str | None:
        async with self.sessions() as session:
            row = await self._row(session, household_id, connector)
            return row.cursor if row else None

    async def save(self, household_id: UUID, connector: str, cursor: str) -> ConnectorCursor:
        async with self.sessions.begin() as session:
            row = await self._row(session, household_id, connector)
            if row is None:
                row = ConnectorCursor(household_id=household_id, connector=connector, cursor=cursor)
                session.add(row)
            else:
                row.cursor = cursor
            await session.flush()
            return row

    async def clear(self, household_id: UUID, connector: str) -> bool:
        async with self.sessions.begin() as session:
            row = await self._row(session, household_id, connector)
            if row is None:
                return False
            await session.delete(row)
            await session.flush()
            return True

    @staticmethod
    async def _row(
        session: AsyncSession, household_id: UUID, connector: str
    ) -> ConnectorCursor | None:
        return await session.scalar(
            select(ConnectorCursor).where(
                ConnectorCursor.household_id == household_id,
                ConnectorCursor.connector == connector,
            )
        )
