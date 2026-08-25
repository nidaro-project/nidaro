from collections.abc import Callable
from typing import Any

from nidaro.commitments.schemas import CommitmentView, RecordCommitmentRequest
from nidaro.container import ApplicationServices


def build_commitment_tools(services: ApplicationServices) -> list[Callable[..., Any]]:
    async def record_commitment(request: RecordCommitmentRequest) -> CommitmentView:
        """Record a promise or commitment made by a family member."""
        return await services.commitments.record(request)

    return [record_commitment]
