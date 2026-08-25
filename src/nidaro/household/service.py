from uuid import UUID

from nidaro.household.repository import HouseholdRepository
from nidaro.household.schemas import CreateHouseholdRequest, HouseholdView


class HouseholdService:
    def __init__(self, repository: HouseholdRepository) -> None:
        self.repository = repository

    async def get_household(self, household_id: UUID | None = None) -> HouseholdView | None:
        household = await self.repository.get(household_id)
        return HouseholdView.model_validate(household) if household else None

    async def ensure_household(self, request: CreateHouseholdRequest) -> HouseholdView:
        household = await self.repository.get()
        if household is None:
            household = await self.repository.create(request)
        return HouseholdView.model_validate(household)
