from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nidaro.calendar.repository import CalendarRepository
from nidaro.calendar.service import CalendarService
from nidaro.commitments.repository import CommitmentRepository
from nidaro.commitments.service import CommitmentService
from nidaro.config import get_settings
from nidaro.connectors.crypto import SecretBox
from nidaro.connectors.google_calendar.accounts import (
    GoogleCalendarAccountRepository,
    GoogleCalendarAccountService,
)
from nidaro.connectors.google_calendar.client import GoogleCalendarClient
from nidaro.connectors.google_calendar.connector import GoogleCalendarConnector
from nidaro.connectors.google_calendar.oauth import GoogleOAuthSettings
from nidaro.connectors.google_calendar.writes import GoogleCalendarWriteService
from nidaro.connectors.registry import ConnectorRegistry
from nidaro.connectors.repository import (
    ConnectorConfigRepository,
    ConnectorCredentialRepository,
    ConnectorCursorRepository,
)
from nidaro.connectors.service import (
    ConnectorConfigService,
    ConnectorCredentialService,
    ConnectorService,
)
from nidaro.conversations.repository import ConversationRepository
from nidaro.conversations.service import ConversationService
from nidaro.household.repository import HouseholdRepository
from nidaro.household.service import HouseholdService
from nidaro.jobs.service import JobService
from nidaro.meals.repository import MealsRepository
from nidaro.meals.service import MealsService
from nidaro.memory.repository import FactRepository
from nidaro.memory.service import MemoryService
from nidaro.school.repository import SchoolRepository
from nidaro.school.service import SchoolService
from nidaro.sources.repository import SourceRepository
from nidaro.sources.service import SourceService
from nidaro.tasks.repository import TaskRepository
from nidaro.tasks.service import TaskService


@dataclass(frozen=True)
class ApplicationServices:
    household: HouseholdService
    calendar: CalendarService
    meals: MealsService
    school: SchoolService
    tasks: TaskService
    memory: MemoryService
    commitments: CommitmentService
    sources: SourceService
    conversations: ConversationService
    jobs: JobService
    connectors: ConnectorService
    credentials: ConnectorCredentialService
    connector_configs: ConnectorConfigService
    google_accounts: GoogleCalendarAccountService
    google_writes: GoogleCalendarWriteService

    @classmethod
    def build(cls, sessions: async_sessionmaker[AsyncSession]) -> "ApplicationServices":
        household = HouseholdService(HouseholdRepository(sessions))
        calendar = CalendarService(CalendarRepository(sessions), HouseholdRepository(sessions))
        credentials = ConnectorCredentialService(
            ConnectorCredentialRepository(sessions), SecretBox.from_settings(get_settings())
        )
        google_accounts = GoogleCalendarAccountService(
            GoogleCalendarAccountRepository(sessions), credentials
        )
        google_client = GoogleCalendarClient(GoogleOAuthSettings.from_settings(get_settings()))
        registry = ConnectorRegistry()
        registry.register(GoogleCalendarConnector(google_accounts, google_client))
        return cls(
            household=household,
            calendar=calendar,
            meals=MealsService(MealsRepository(sessions)),
            school=SchoolService(SchoolRepository(sessions)),
            tasks=TaskService(TaskRepository(sessions)),
            memory=MemoryService(FactRepository(sessions)),
            commitments=CommitmentService(CommitmentRepository(sessions)),
            sources=SourceService(SourceRepository(sessions)),
            conversations=ConversationService(ConversationRepository(sessions)),
            jobs=JobService(sessions),
            connectors=ConnectorService(
                registry,
                ConnectorCursorRepository(sessions),
                ConnectorConfigRepository(sessions),
            ),
            credentials=credentials,
            connector_configs=ConnectorConfigService(ConnectorConfigRepository(sessions)),
            google_accounts=google_accounts,
            google_writes=GoogleCalendarWriteService(
                google_accounts, google_client, calendar, household
            ),
        )
