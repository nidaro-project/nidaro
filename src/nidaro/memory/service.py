from uuid import UUID

from nidaro.memory.repository import FactRepository
from nidaro.memory.schemas import FactView, RememberFactRequest


class MemoryService:
    def __init__(self, repository: FactRepository) -> None:
        self.repository = repository

    async def remember_fact(self, request: RememberFactRequest) -> FactView:
        return FactView.model_validate(await self.repository.create(request))

    async def search(self, household_id: UUID, query: str, limit: int = 10) -> list[FactView]:
        facts = await self.repository.search(household_id, query, limit)
        return [FactView.model_validate(fact) for fact in facts]

    async def recent(self, household_id: UUID, limit: int = 10) -> list[FactView]:
        return [
            FactView.model_validate(fact)
            for fact in await self.repository.recent(household_id, limit)
        ]
