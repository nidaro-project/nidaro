"""Family-facing writes to Google Calendar, behind the service boundary.

The assistant's create/update tool calls this service instead of the Google
API directly. Every write carries nidaro's mirror-loop markers
(`extendedProperties.private`) and a client-supplied event id, so the
resulting Google event is self-identifying; the response is applied to the
local calendar mirror through `CalendarService` — the same path the sync loop
uses — so the family sees the change immediately instead of after the next
poll.

Concurrency and feedback rules (from the Calendar API docs):
- updates are get→modify→put with `If-Match: <etag>`; a 412 means someone
  edited the event in Google mid-flight and surfaces as `GoogleConflictError`
  — failed loudly, never clobbered;
- events with attendees are posted with `sendUpdates=all` so guests get
  invited; attendee-less events stay silent;
- deletes of nidaro-origin and externally-origin events are the same DELETE;
  the local mirror is removed via the same tombstone path the sync uses.

Recurring writes are refused in v1: with `singleEvents=True` sync, a locally
mirrored series master would never be echoed by the stream and its instances
would duplicate it — the master-vs-instance mirror policy is its own slice.
"""

from collections.abc import Sequence
from uuid import UUID

from nidaro.calendar.recurrence import resolve_timezone
from nidaro.calendar.schemas import CreateEventRequest, EventView
from nidaro.calendar.service import CalendarService
from nidaro.connectors.google_calendar.accounts import (
    CONNECTOR_NAME,
    GoogleCalendarAccountService,
)
from nidaro.connectors.google_calendar.client import (
    GoogleCalendarClient,
    GooglePreconditionFailedError,
)
from nidaro.connectors.google_calendar.mapping import (
    UpdateGoogleEventFields,
    build_event_body,
    merge_event_update,
    new_google_event_id,
    split_external_id,
    to_external_record,
)
from nidaro.connectors.google_calendar.models import GoogleAccountCredentials
from nidaro.connectors.models import ExternalRecord
from nidaro.db.types import utc_now
from nidaro.household.service import HouseholdService


class GoogleCalendarWriteError(RuntimeError):
    """A write to Google Calendar could not be completed."""


class GoogleConflictError(GoogleCalendarWriteError):
    """412: the event changed on Google after it was read for the update."""


class NoGoogleAccountError(GoogleCalendarWriteError):
    """The household has no connected Google account for this operation."""


class GoogleCalendarWriteService:
    def __init__(
        self,
        accounts: GoogleCalendarAccountService,
        client: GoogleCalendarClient,
        calendar: CalendarService,
        households: HouseholdService,
    ) -> None:
        self.accounts = accounts
        self.client = client
        self.calendar = calendar
        self.households = households

    async def create_event(
        self, household_id: UUID, request: CreateEventRequest, *, attendees: Sequence[str] = ()
    ) -> EventView:
        """Create on Google and land the local mirror in one service call."""
        if request.recurrence_weekdays:
            raise GoogleCalendarWriteError(
                "recurring events cannot be written to Google Calendar yet; create "
                "them in the household calendar without a Google target"
            )
        account = await self._first_account(household_id)
        tz = resolve_timezone(await self._household_timezone(household_id))
        body = build_event_body(
            event_id=new_google_event_id(),
            title=request.title,
            starts_at=request.starts_at,
            ends_at=request.ends_at,
            description=request.description,
            location=request.location,
            is_all_day=request.is_all_day,
            recurrence_weekdays=request.recurrence_weekdays,
            attendees=attendees,
            tz=tz,
        )
        google_event = await self.client.insert_event(
            account, body, send_updates="all" if attendees else None
        )
        return await self._land(household_id, account, google_event)

    async def update_event(
        self, household_id: UUID, external_id: str, fields: UpdateGoogleEventFields
    ) -> EventView:
        """Etag-checked get→modify→put against Google, then land the result."""
        account, google_event_id = await self._account_for(household_id, external_id)
        tz = resolve_timezone(await self._household_timezone(household_id))
        existing = await self.client.get_event(account, google_event_id)
        body = merge_event_update(existing, fields, tz=tz)
        try:
            updated = await self.client.update_event(
                account, google_event_id, body, if_match=existing.get("etag")
            )
        except GooglePreconditionFailedError as error:
            raise GoogleConflictError(str(error)) from error
        return await self._land(household_id, account, updated)

    async def delete_event(self, household_id: UUID, external_id: str) -> bool:
        """Delete on Google and drop the local mirror via the tombstone path.

        Returns whether a mirror existed; deleting on Google is idempotent.
        """
        account, google_event_id = await self._account_for(household_id, external_id)
        await self.client.delete_event(account, google_event_id)
        tombstone = ExternalRecord(
            connector=CONNECTOR_NAME,
            external_type="calendar_event",
            external_id=external_id,
            payload={},
            content_hash="",
            observed_at=utc_now(),
            deleted=True,
        )
        report = await self.calendar.apply_external_records(household_id, [tombstone])
        return report.removed == 1

    async def _land(
        self,
        household_id: UUID,
        account: GoogleAccountCredentials,
        google_event: dict,
    ) -> EventView:
        tz_name = await self._household_timezone(household_id)
        record = to_external_record(
            account, google_event, observed_at=utc_now(), timezone=tz_name or "UTC"
        )
        await self.calendar.apply_external_records(household_id, [record])
        mirror = await self.calendar.get_mirror(household_id, CONNECTOR_NAME, record.external_id)
        if mirror is None:
            raise GoogleCalendarWriteError(
                f"Google accepted the event ({record.external_id}) but the mirror "
                "did not land; check the calendar domain"
            )
        return mirror

    async def _first_account(self, household_id: UUID) -> GoogleAccountCredentials:
        member_accounts = await self.accounts.credentials_for_household(household_id)
        if not member_accounts:
            raise NoGoogleAccountError(
                "no Google account is connected for this household; connect one in "
                "settings before writing to Google Calendar"
            )
        return member_accounts[0]

    async def _account_for(
        self, household_id: UUID, external_id: str
    ) -> tuple[GoogleAccountCredentials, str]:
        email, calendar_id, google_event_id = split_external_id(external_id)
        for account in await self.accounts.credentials_for_household(household_id):
            if account.email == email and account.calendar_id == calendar_id:
                return account, google_event_id
        raise NoGoogleAccountError(
            f"no connected Google account matches {email} ({calendar_id}) for this household"
        )

    async def _household_timezone(self, household_id: UUID) -> str | None:
        household = await self.households.get_household(household_id)
        return household.timezone if household else None
