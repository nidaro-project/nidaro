from typing import Any
from uuid import UUID

from nidaro.conversations.models import Conversation
from nidaro.conversations.repository import ConversationRepository


class ConversationService:
    def __init__(self, repository: ConversationRepository) -> None:
        self.repository = repository

    async def load(self, conversation_id: UUID) -> Conversation | None:
        return await self.repository.load(conversation_id)

    async def create(self, household_id: UUID, title: str | None = None) -> Conversation:
        return await self.repository.create(household_id, title)

    async def save_history(self, conversation_id: UUID, history: list[dict[str, Any]]) -> None:
        await self.repository.save_history(conversation_id, history)
