from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from nidaro.assistant.runtime import AssistantRuntime
from nidaro.web.dependencies import get_runtime

router = APIRouter(prefix="/api/v1/assistant", tags=["assistant"])


class ChatRequest(BaseModel):
    conversation_id: UUID | None = None
    message: str


class ChatResponse(BaseModel):
    conversation_id: UUID
    message: str


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    runtime: AssistantRuntime = Depends(get_runtime),  # noqa: B008
) -> ChatResponse:
    household = await runtime.services.household.get_household()
    if household is None:
        raise ValueError("Household not seeded")
    conversation_id, output = await runtime.run(
        household.id, request.message, request.conversation_id
    )
    return ChatResponse(conversation_id=conversation_id, message=output)
