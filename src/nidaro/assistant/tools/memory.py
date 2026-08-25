from collections.abc import Callable
from typing import Any

from nidaro.container import ApplicationServices
from nidaro.memory.schemas import FactView, MemorySearchRequest, RememberFactRequest


def build_memory_tools(services: ApplicationServices) -> list[Callable[..., Any]]:
    async def remember_fact(request: RememberFactRequest) -> FactView:
        """Save a structured fact about the family."""
        return await services.memory.remember_fact(request)

    async def search_family_memory(request: MemorySearchRequest) -> list[FactView]:
        """Search structured family facts by text."""
        return await services.memory.search(request.household_id, request.query, request.limit)

    return [remember_fact, search_family_memory]
