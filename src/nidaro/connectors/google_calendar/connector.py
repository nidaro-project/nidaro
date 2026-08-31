"""The Google Calendar connector: syncToken incremental sync per account.

The connector is a pure producer: it turns `events.list` pages into
`ExternalRecord`s and never touches domain tables — the worker applies them
through `CalendarService`. The syncToken is the cursor, multiplexed per
account as JSON (`{"<email>": {"calendar_id": ..., "sync_token": ...}}`),
stored by `ConnectorService` after a successful run.

A 410 GONE (expired/invalidated token) is handled inside the run: the
affected account re-syncs in full immediately, so a reset costs one extra
full pass instead of a failed run. A dead refresh token (`invalid_grant`)
cannot be fixed by anyone but the member — the account is skipped with a
warning while its siblings keep syncing, and its cursor entry simply drops
out (its next successful pass starts full again).
"""

import logging
from datetime import timedelta
from uuid import UUID

from pydantic import BaseModel, ValidationError

from nidaro.calendar.recurrence import resolve_timezone
from nidaro.connectors.base import StaleCursorError
from nidaro.connectors.google_calendar.accounts import (
    CONNECTOR_NAME,
    GoogleCalendarAccountService,
)
from nidaro.connectors.google_calendar.client import GoogleApiError, GoogleCalendarClient
from nidaro.connectors.google_calendar.mapping import FULL_SYNC_DAYS, to_external_record
from nidaro.connectors.google_calendar.models import GoogleAccountCredentials
from nidaro.connectors.google_calendar.oauth import InvalidGrantError
from nidaro.connectors.models import ConnectorContext, SyncResult
from nidaro.db.types import utc_now

logger = logging.getLogger(__name__)


class GoogleCursorEntry(BaseModel):
    calendar_id: str
    sync_token: str


class GoogleSyncCursor(BaseModel):
    accounts: dict[str, GoogleCursorEntry] = {}


def parse_cursor(cursor: str | None) -> GoogleSyncCursor:
    """Decode the stored cursor; anything unreadable means full re-sync."""
    if cursor is None:
        return GoogleSyncCursor()
    try:
        return GoogleSyncCursor.model_validate_json(cursor)
    except ValidationError:
        return GoogleSyncCursor()


class GoogleCalendarConnector:
    name = CONNECTOR_NAME

    def __init__(
        self, accounts: GoogleCalendarAccountService, client: GoogleCalendarClient
    ) -> None:
        self.accounts = accounts
        self.client = client

    async def sync(self, context: ConnectorContext, cursor: str | None) -> SyncResult:
        household_id = UUID(context.household_id)
        state = parse_cursor(cursor)
        member_accounts = await self.accounts.credentials_for_household(household_id)
        records = []
        entries = {}
        observed_at = utc_now()
        for account in member_accounts:
            stored = state.accounts.get(account.email)
            sync_token = (
                stored.sync_token
                if stored is not None and stored.calendar_id == account.calendar_id
                else None
            )
            try:
                account_records, next_token = await self._sync_account_resetting_stale_token(
                    context, account, sync_token, observed_at
                )
            except InvalidGrantError:
                logger.warning(
                    "google_calendar: %s must reconnect their account (invalid_grant); "
                    "skipping it this sync",
                    account.email,
                )
                continue
            entries[account.email] = GoogleCursorEntry(
                calendar_id=account.calendar_id, sync_token=next_token
            )
            records.extend(account_records)
        return SyncResult(
            records=records,
            next_cursor=GoogleSyncCursor(accounts=entries).model_dump_json() if entries else None,
        )

    async def _sync_account_resetting_stale_token(
        self,
        context: ConnectorContext,
        account: GoogleAccountCredentials,
        sync_token: str | None,
        observed_at,
    ) -> tuple[list, str]:
        """Sync one account; a 410 GONE restarts it in full within this run."""
        try:
            return await self._sync_account(context, account, sync_token, observed_at)
        except StaleCursorError:
            return await self._sync_account(context, account, None, observed_at)

    async def _sync_account(
        self,
        context: ConnectorContext,
        account: GoogleAccountCredentials,
        sync_token: str | None,
        observed_at,
    ) -> tuple[list, str]:
        """One account's full or incremental sync, paginated to the end.

        Returns the account's records plus the `nextSyncToken` every account
        must end up with — a missing one means nidaro would lose the sync
        position, which is refused rather than silently re-synced next run.
        """
        records = []
        page_token = None
        time_min = None
        if sync_token is None:
            tz = resolve_timezone(context.timezone)
            time_min = utc_now().astimezone(tz) - timedelta(days=FULL_SYNC_DAYS)
        while True:
            page = await self.client.list_events(
                account, sync_token=sync_token, page_token=page_token, time_min=time_min
            )
            records.extend(
                to_external_record(
                    account, event, observed_at=observed_at, timezone=context.timezone
                )
                for event in page.events
            )
            if page.next_page_token is not None:
                page_token = page.next_page_token
                continue
            if page.next_sync_token is None:
                raise GoogleApiError(
                    f"Google returned no sync token for {account.email}/{account.calendar_id}; "
                    "refusing to lose the sync position"
                )
            return records, page.next_sync_token
