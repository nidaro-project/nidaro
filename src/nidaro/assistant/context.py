from dataclasses import dataclass
from uuid import UUID

from nidaro.container import ApplicationServices


@dataclass(frozen=True)
class FamilyContext:
    household: object
    events: list[object]
    tasks: list[object]
    facts: list[object]
    commitments: list[object]


class FamilyContextBuilder:
    def __init__(self, services: ApplicationServices) -> None:
        self.services = services

    async def build(self, household_id: UUID) -> FamilyContext:
        household = await self.services.household.get_household(household_id)
        if household is None:
            raise ValueError(f"Household {household_id} does not exist")
        events, tasks, facts, commitments = await __import__("asyncio").gather(
            self.services.calendar.get_upcoming_events(household_id),
            self.services.tasks.get_open_tasks(household_id),
            self.services.memory.recent(household_id),
            self.services.commitments.open(household_id),
        )
        return FamilyContext(household, events, tasks, facts, commitments)
