from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nidaro.conversations.models import Conversation


class ConversationRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def load(self, conversation_id: UUID) -> Conversation | None:
        async with self.sessions() as session:
            return await session.get(Conversation, conversation_id)

    async def create(self, household_id: UUID, title: str | None = None) -> Conversation:
        async with self.sessions.begin() as session:
            conversation = Conversation(household_id=household_id, title=title)
            session.add(conversation)
            await session.flush()
            return conversation

    async def save_history(self, conversation_id: UUID, history: list[dict[str, Any]]) -> None:
        async with self.sessions.begin() as session:
            conversation = await session.get(Conversation, conversation_id)
            if conversation is None:
                raise ValueError(f"Conversation {conversation_id} does not exist")
            conversation.message_history = history
