from typing import Any, cast
from uuid import UUID

from nidaro.assistant.agent import create_agent
from nidaro.assistant.context import FamilyContextBuilder
from nidaro.config import Settings
from nidaro.container import ApplicationServices


class AssistantRuntime:
    def __init__(
        self, settings: Settings, services: ApplicationServices, model: Any = None
    ) -> None:
        self.settings = settings
        self.services = services
        self.model = model

    async def run(
        self, household_id: UUID, message: str, conversation_id: UUID | None = None
    ) -> tuple[UUID, str]:
        conversation = (
            await self.services.conversations.load(conversation_id)
            if conversation_id is not None
            else await self.services.conversations.create(household_id)
        )
        if conversation is None:
            raise ValueError("Conversation not found")
        context = await FamilyContextBuilder(self.services).build(household_id)
        agent = create_agent(self.settings, self.services, self.model)
        prompt = f"Family context: {context}\n\nUser message: {message}"
        result = await agent.run(prompt, message_history=conversation.message_history)
        output = getattr(result, "output", str(result))
        history = cast(
            list[dict[str, Any]],
            result.all_messages_json() if hasattr(result, "all_messages_json") else [],
        )
        await self.services.conversations.save_history(conversation.id, history)
        return conversation.id, str(output)
