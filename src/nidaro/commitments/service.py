from uuid import UUID

from nidaro.commitments.repository import CommitmentRepository
from nidaro.commitments.schemas import CommitmentView, RecordCommitmentRequest


class CommitmentService:
    def __init__(self, repository: CommitmentRepository) -> None:
        self.repository = repository

    async def record(self, request: RecordCommitmentRequest) -> CommitmentView:
        return CommitmentView.model_validate(await self.repository.create(request))

    async def open(self, household_id: UUID) -> list[CommitmentView]:
        return [
            CommitmentView.model_validate(item) for item in await self.repository.open(household_id)
        ]
