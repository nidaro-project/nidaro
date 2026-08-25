from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nidaro.sources.models import Source


class SourceRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def create(self, source: Source) -> Source:
        async with self.sessions.begin() as session:
            session.add(source)
            await session.flush()
            return source
