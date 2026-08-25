from typing import Any
from uuid import UUID

from nidaro.sources.models import Source
from nidaro.sources.repository import SourceRepository


class SourceService:
    def __init__(self, repository: SourceRepository) -> None:
        self.repository = repository

    async def record(
        self, household_id: UUID, source_type: str, content: str | None = None, **metadata: Any
    ) -> Source:
        return await self.repository.create(
            Source(household_id=household_id, type=source_type, content=content, metadata_=metadata)
        )
