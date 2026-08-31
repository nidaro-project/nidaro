from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nidaro.connectors.models import ConnectorCredential, ConnectorCursor


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


class ConnectorCredentialRepository:
    """Stores only ciphertext; encryption lives in SecretBox behind the service."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def get_ciphertext(self, household_id: UUID, connector: str, name: str) -> str | None:
        async with self.sessions() as session:
            row = await self._row(session, household_id, connector, name)
            return row.secret if row else None

    async def save_ciphertext(
        self, household_id: UUID, connector: str, name: str, ciphertext: str
    ) -> ConnectorCredential:
        async with self.sessions.begin() as session:
            row = await self._row(session, household_id, connector, name)
            if row is None:
                row = ConnectorCredential(
                    household_id=household_id, connector=connector, name=name, secret=ciphertext
                )
                session.add(row)
            else:
                row.secret = ciphertext
            await session.flush()
            return row

    async def delete(self, household_id: UUID, connector: str, name: str) -> bool:
        async with self.sessions.begin() as session:
            row = await self._row(session, household_id, connector, name)
            if row is None:
                return False
            await session.delete(row)
            await session.flush()
            return True

    async def names(self, household_id: UUID, connector: str) -> list[str]:
        """Stored credential names — metadata only, no secret material."""
        async with self.sessions() as session:
            result = await session.scalars(
                select(ConnectorCredential.name)
                .where(
                    ConnectorCredential.household_id == household_id,
                    ConnectorCredential.connector == connector,
                )
                .order_by(ConnectorCredential.name)
            )
            return list(result)

    async def all(self) -> list[ConnectorCredential]:
        async with self.sessions() as session:
            result = await session.scalars(
                select(ConnectorCredential).order_by(
                    ConnectorCredential.connector, ConnectorCredential.name
                )
            )
            return list(result)

    @staticmethod
    async def _row(
        session: AsyncSession, household_id: UUID, connector: str, name: str
    ) -> ConnectorCredential | None:
        return await session.scalar(
            select(ConnectorCredential).where(
                ConnectorCredential.household_id == household_id,
                ConnectorCredential.connector == connector,
                ConnectorCredential.name == name,
            )
        )
