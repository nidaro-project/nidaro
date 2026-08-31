"""Registry of consented Google accounts and their decrypted credentials.

Account rows hold metadata (email, calendar, granted scopes) in PostgreSQL;
the OAuth refresh tokens live encrypted in the shared `connector_credentials`
store, one credential per account named by the account email. This module is
the only place that joins the two halves back together.
"""

from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nidaro.connectors.google_calendar.models import GoogleCalendarAccount
from nidaro.connectors.service import ConnectorCredentialService

CONNECTOR_NAME = "google_calendar"


class GoogleAccountCredentials(BaseModel):
    """One account ready for API calls: metadata plus a usable refresh token."""

    email: str
    calendar_id: str
    scopes: list[str]
    refresh_token: str


class GoogleCalendarAccountRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def get(self, household_id: UUID, email: str) -> GoogleCalendarAccount | None:
        async with self.sessions() as session:
            return await self._row(session, household_id, email)

    async def list_for_household(self, household_id: UUID) -> list[GoogleCalendarAccount]:
        async with self.sessions() as session:
            result = await session.scalars(
                select(GoogleCalendarAccount)
                .where(GoogleCalendarAccount.household_id == household_id)
                .order_by(GoogleCalendarAccount.google_email)
            )
            return list(result)

    async def upsert(
        self,
        household_id: UUID,
        email: str,
        *,
        calendar_id: str,
        granted_scopes: list[str],
    ) -> GoogleCalendarAccount:
        async with self.sessions.begin() as session:
            row = await self._row(session, household_id, email)
            if row is None:
                row = GoogleCalendarAccount(
                    household_id=household_id,
                    google_email=email,
                    calendar_id=calendar_id,
                    granted_scopes=granted_scopes,
                )
                session.add(row)
            else:
                row.calendar_id = calendar_id
                row.granted_scopes = granted_scopes
            await session.flush()
            return row

    async def delete(self, household_id: UUID, email: str) -> bool:
        async with self.sessions.begin() as session:
            row = await self._row(session, household_id, email)
            if row is None:
                return False
            await session.delete(row)
            await session.flush()
            return True

    @staticmethod
    async def _row(
        session: AsyncSession, household_id: UUID, email: str
    ) -> GoogleCalendarAccount | None:
        return await session.scalar(
            select(GoogleCalendarAccount).where(
                GoogleCalendarAccount.household_id == household_id,
                GoogleCalendarAccount.google_email == email,
            )
        )


class GoogleCalendarAccountService:
    """Connect (register), list, and disconnect a household's Google accounts.

    `register` is the OAuth callback's single call: it stores the refresh
    token encrypted under the account email and upserts the account row.
    `credentials_for_household` is what the connector and the write service
    run on: accounts with decrypted, ready-to-use refresh tokens.
    """

    def __init__(
        self,
        repository: GoogleCalendarAccountRepository,
        credentials: ConnectorCredentialService,
    ) -> None:
        self.repository = repository
        self.credentials = credentials

    async def register(
        self,
        household_id: UUID,
        email: str,
        refresh_token: str,
        *,
        calendar_id: str = "primary",
        granted_scopes: list[str] | None = None,
    ) -> GoogleCalendarAccount:
        """Store (or overwrite) one member's consent: token encrypted, row upserted."""
        await self.credentials.set(household_id, CONNECTOR_NAME, email, refresh_token)
        return await self.repository.upsert(
            household_id,
            email,
            calendar_id=calendar_id,
            granted_scopes=granted_scopes if granted_scopes is not None else [],
        )

    async def credentials_for_household(self, household_id: UUID) -> list[GoogleAccountCredentials]:
        """All accounts of one household with decrypted refresh tokens.

        A row whose credential went missing is broken state — it would silently
        desync that member's calendar — so it raises instead of being skipped.
        """
        combined: list[GoogleAccountCredentials] = []
        for row in await self.repository.list_for_household(household_id):
            refresh_token = await self.credentials.get(
                household_id, CONNECTOR_NAME, row.google_email
            )
            if refresh_token is None:
                raise ValueError(
                    f"Google account {row.google_email} has no stored credential for "
                    f"household {household_id}; reconnect the account"
                )
            combined.append(
                GoogleAccountCredentials(
                    email=row.google_email,
                    calendar_id=row.calendar_id,
                    scopes=list(row.granted_scopes),
                    refresh_token=refresh_token,
                )
            )
        return combined

    async def get(self, household_id: UUID, email: str) -> GoogleCalendarAccount | None:
        return await self.repository.get(household_id, email)

    async def forget(self, household_id: UUID, email: str) -> bool:
        """Disconnect one account: drop its credential and its row."""
        await self.credentials.delete(household_id, CONNECTOR_NAME, email)
        return await self.repository.delete(household_id, email)
