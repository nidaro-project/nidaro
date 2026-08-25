from collections.abc import Callable
from typing import Any
from uuid import UUID

from nidaro.container import ApplicationServices
from nidaro.household.schemas import HouseholdView


def build_family_tools(services: ApplicationServices) -> list[Callable[..., Any]]:
    async def get_family_overview(household_id: UUID) -> HouseholdView:
        """Get the household and its family members."""
        result = await services.household.get_household(household_id)
        if result is None:
            raise ValueError("Household not found")
        return result

    return [get_family_overview]
