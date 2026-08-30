from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nidaro.calendar.repository import CalendarRepository
from nidaro.calendar.service import CalendarService
from nidaro.commitments.repository import CommitmentRepository
from nidaro.commitments.service import CommitmentService
from nidaro.connectors.registry import ConnectorRegistry
from nidaro.connectors.service import ConnectorService
from nidaro.conversations.repository import ConversationRepository
from nidaro.conversations.service import ConversationService
from nidaro.household.repository import HouseholdRepository
from nidaro.household.service import HouseholdService
from nidaro.jobs.service import JobService
from nidaro.meals.repository import MealsRepository
from nidaro.meals.service import MealsService
from nidaro.memory.repository import FactRepository
from nidaro.memory.service import MemoryService
from nidaro.sources.repository import SourceRepository
from nidaro.sources.service import SourceService
from nidaro.tasks.repository import TaskRepository
from nidaro.tasks.service import TaskService


@dataclass(frozen=True)
class ApplicationServices:
    household: HouseholdService
    calendar: CalendarService
    meals: MealsService
    tasks: TaskService
    memory: MemoryService
    commitments: CommitmentService
    sources: SourceService
    conversations: ConversationService
    jobs: JobService
    connectors: ConnectorService

    @classmethod
    def build(cls, sessions: async_sessionmaker[AsyncSession]) -> "ApplicationServices":
        return cls(
            household=HouseholdService(HouseholdRepository(sessions)),
            calendar=CalendarService(CalendarRepository(sessions), HouseholdRepository(sessions)),
            meals=MealsService(MealsRepository(sessions)),
            tasks=TaskService(TaskRepository(sessions)),
            memory=MemoryService(FactRepository(sessions)),
            commitments=CommitmentService(CommitmentRepository(sessions)),
            sources=SourceService(SourceRepository(sessions)),
            conversations=ConversationService(ConversationRepository(sessions)),
            jobs=JobService(sessions),
            connectors=ConnectorService(ConnectorRegistry()),
        )
