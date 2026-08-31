"""Async Google Calendar v3 client, spoken directly over httpx.

The REST surface this integration needs is small (events list/insert/get/
update/delete plus the primary-calendar lookup) and fully documented, so the
discovery-document client libraries stay out: `google-api-python-client` is
blocking on non-thread-safe httplib2, and the token protocol is two plain
POSTs (see `oauth.py`). Everything here is async end to end; the transport is
injectable for fixture replay in tests.

Error contract:
- 410 GONE on `list_events` → `StaleCursorError`: Google invalidated the
  syncToken; the caller re-syncs that calendar in full.
- 412 → `GooglePreconditionFailedError`: the etag `If-Match` lost the race
  with a concurrent edit.
- `invalid_grant` during refresh → `InvalidGrantError`: the member must
  reconnect; nothing a retry can fix.
"""

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import BaseModel

from nidaro.connectors.base import StaleCursorError
from nidaro.connectors.google_calendar.accounts import GoogleAccountCredentials
from nidaro.connectors.google_calendar.oauth import (
    GoogleOAuthSettings,
    InvalidGrantError,
    refresh_access_token,
)
from nidaro.db.types import utc_now

API_ROOT = "https://www.googleapis.com/calendar/v3"
ACCESS_TOKEN_MARGIN = timedelta(seconds=60)
REQUEST_TIMEOUT = 30.0


class GoogleApiError(RuntimeError):
    """Google Calendar API returned an error this client does not translate."""


class GooglePreconditionFailedError(GoogleApiError):
    """412: the event changed on Google since the caller last saw it."""


class GoogleNotConfigured(GoogleApiError):
    """No OAuth client is configured, so Google cannot be called."""


class EventsPage(BaseModel):
    """One page of `events.list` — raw event JSON plus the sync bookkeeping."""

    events: list[dict[str, Any]]
    next_page_token: str | None = None
    next_sync_token: str | None = None


class _CachedToken:
    def __init__(self, token: str, expires_at: datetime) -> None:
        self.token = token
        self.expires_at = expires_at

    def valid(self, now: datetime) -> bool:
        return now < self.expires_at - ACCESS_TOKEN_MARGIN


class GoogleCalendarClient:
    def __init__(
        self,
        oauth: GoogleOAuthSettings | None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._oauth = oauth
        self._transport = transport
        self._clock = clock
        self._tokens: dict[str, _CachedToken] = {}

    async def list_events(
        self,
        account: GoogleAccountCredentials,
        *,
        sync_token: str | None = None,
        page_token: str | None = None,
        time_min: datetime | None = None,
        max_results: int = 2500,
    ) -> EventsPage:
        """One page of `events.list`, full or incremental.

        `singleEvents=True` on every call: the API requires incremental calls
        to repeat the full sync's parameters, and the mapping treats recurring
        series as per-instance rows. `timeMin` is a full-sync bound only —
        the API rejects it alongside `syncToken`.
        """
        params: dict[str, Any] = {"maxResults": max_results, "singleEvents": "true"}
        if sync_token is not None:
            params["syncToken"] = sync_token
        elif time_min is not None:
            params["timeMin"] = time_min.isoformat()
        if page_token is not None:
            params["pageToken"] = page_token
        data = await self._request(
            "GET",
            f"/calendars/{quote(account.calendar_id, safe='')}/events",
            account,
            params=params,
        )
        return EventsPage(
            events=data.get("items", []),
            next_page_token=data.get("nextPageToken"),
            next_sync_token=data.get("nextSyncToken"),
        )

    async def primary_calendar_for_token(self, refresh_token: str) -> dict[str, Any]:
        """The member's primary calendar — its id is the account email.

        Used by the OAuth callback to learn which account consented without
        asking for the userinfo scope: `calendar.events` already covers
        `calendarList.get`.
        """
        account = GoogleAccountCredentials(
            email="", calendar_id="primary", scopes=[], refresh_token=refresh_token
        )
        return await self._request("GET", "/users/me/calendarList/primary", account)

    async def insert_event(
        self,
        account: GoogleAccountCredentials,
        body: dict[str, Any],
        *,
        send_updates: str | None = None,
    ) -> dict[str, Any]:
        params = {"sendUpdates": send_updates} if send_updates else None
        return await self._insert_or_update(
            "POST",
            f"/calendars/{quote(account.calendar_id, safe='')}/events",
            account,
            body,
            params=params,
        )

    async def get_event(self, account: GoogleAccountCredentials, event_id: str) -> dict[str, Any]:
        return await self._request(
            "GET", f"/calendars/{quote(account.calendar_id, safe='')}/events/{event_id}", account
        )

    async def update_event(
        self,
        account: GoogleAccountCredentials,
        event_id: str,
        body: dict[str, Any],
        *,
        if_match: str | None = None,
    ) -> dict[str, Any]:
        """`events.update` — the full resource is replaced.

        `if_match` (the event's etag) makes the write conditional; a 412
        surfaces as `GooglePreconditionFailedError` instead of clobbering a
        concurrent edit made in the Google UI.
        """
        headers = {"If-Match": if_match} if if_match else None
        return await self._insert_or_update(
            "PUT",
            f"/calendars/{quote(account.calendar_id, safe='')}/events/{event_id}",
            account,
            body,
            headers=headers,
        )

    async def delete_event(self, account: GoogleAccountCredentials, event_id: str) -> None:
        await self._request(
            "DELETE",
            f"/calendars/{quote(account.calendar_id, safe='')}/events/{event_id}",
            account,
            expected_status=(200, 204, 410),
        )

    async def _insert_or_update(
        self,
        method: str,
        path: str,
        account: GoogleAccountCredentials,
        body: dict[str, Any],
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return await self._request(method, path, account, params=params, headers=headers, json=body)

    async def _request(
        self,
        method: str,
        path: str,
        account: GoogleAccountCredentials,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        expected_status: tuple[int, ...] = (200, 204),
    ) -> dict[str, Any]:
        token = await self._access_token(account.refresh_token)
        async with httpx.AsyncClient(transport=self._transport, timeout=REQUEST_TIMEOUT) as http:
            response = await http.request(
                method,
                f"{API_ROOT}{path}",
                params=params,
                headers={"Authorization": f"Bearer {token}", **(headers or {})},
                json=json,
            )
        if response.status_code in expected_status:
            if response.status_code == 204 or not response.content:
                return {}
            return dict(response.json())
        if response.status_code == 410:
            raise StaleCursorError(
                f"Google reset the sync token for {account.calendar_id} (410 GONE); "
                "the next sync starts from a full sync"
            )
        if response.status_code == 412:
            raise GooglePreconditionFailedError(
                f"{account.calendar_id}/{path.rsplit('/', 1)[-1]} changed on Google "
                "since it was read (412); resolve the conflict and retry"
            )
        raise GoogleApiError(
            f"Google Calendar API returned {response.status_code}: {response.text[:500]}"
        )

    async def _access_token(self, refresh_token: str) -> str:
        cached = self._tokens.get(refresh_token)
        if cached is not None and cached.valid(self._clock()):
            return cached.token
        if self._oauth is None:
            raise GoogleNotConfigured(
                "Google Calendar OAuth is not configured (NIDARO_GOOGLE_CLIENT_ID / "
                "NIDARO_GOOGLE_CLIENT_SECRET); accounts cannot call Google"
            )
        async with httpx.AsyncClient(transport=self._transport, timeout=REQUEST_TIMEOUT) as http:
            tokens = await refresh_access_token(self._oauth, refresh_token, http=http)
        self._tokens[refresh_token] = _CachedToken(
            tokens.access_token,
            self._clock() + timedelta(seconds=tokens.expires_in),
        )
        return tokens.access_token


__all__ = [
    "EventsPage",
    "GoogleApiError",
    "GoogleCalendarClient",
    "GoogleNotConfigured",
    "GooglePreconditionFailedError",
    "InvalidGrantError",
]
