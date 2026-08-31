"""Bakaláři mobile API v3 client — the gatherer's read path.

One login (`POST /api/login`, `client_id=ANDR`) yields a ~1h Bearer token;
every module answers GETs with JSON under `/api/3/`. Module reads are
GET-only by construction (ADR 0002: the school portal is passive — no
mark-as-read, no replies, no writes of any kind). The login and token-refresh
POSTs are the only POSTs this client can issue. A 401 mid-run is recovered
with the refresh token first and a fresh password login second, per the
[portal-3] resolution; tokens live in memory for one sync run and are never
persisted or logged.
"""

from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

LOGIN_PATH = "/api/login"
CLIENT_ID = "ANDR"
DEFAULT_TIMEOUT = 10.0


class BakalariAuthError(Exception):
    """The school server rejected the credentials or every issued token."""


class BakalariRequestError(Exception):
    """A module GET failed on the school server's side."""


@dataclass
class BakalariTokens:
    access_token: str
    refresh_token: str | None = None


class BakalariClient:
    """Authenticated GET access to one school's Bakaláři server.

    Tests inject an `httpx.MockTransport` as `transport`; production runs
    against the school server named by the account's base URL.
    """

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._username = username
        self._password = password
        self._tokens: BakalariTokens | None = None
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            transport=transport,
        )

    async def login(self) -> BakalariTokens:
        """Password-grant login; the only call that sends the password."""
        self._tokens = await self._token_request(
            {"grant_type": "password", "username": self._username, "password": self._password}
        )
        return self._tokens

    async def refresh(self) -> BakalariTokens | None:
        """Redeem the stored refresh token; None when none is held."""
        if self._tokens is None or not self._tokens.refresh_token:
            return None
        self._tokens = await self._token_request(
            {"grant_type": "refresh_token", "refresh_token": self._tokens.refresh_token}
        )
        return self._tokens

    async def user(self) -> Any:
        """Profile and EnabledModules — the account's own visibility."""
        return await self.get_json("/api/3/user")

    async def timetable_actual(self, day: date) -> Any:
        return await self.get_json("/api/3/timetable/actual", params={"date": day.isoformat()})

    async def substitutions(self, day: date) -> Any:
        return await self.get_json("/api/3/substitutions", params={"from": day.isoformat()})

    async def marks(self) -> Any:
        return await self.get_json("/api/3/marks")

    async def homeworks(self, start: date, end: date) -> Any:
        return await self.get_json(
            "/api/3/homeworks", params={"from": start.isoformat(), "to": end.isoformat()}
        )

    async def get_json(self, path: str, params: dict[str, str] | None = None) -> Any:
        """GET one module endpoint; re-authenticates once on a 401."""
        if self._tokens is None:
            await self.login()
        response = await self._http.get(path, params=params, headers=self._bearer())
        if response.status_code == 401:
            await self._recover()
            response = await self._http.get(path, params=params, headers=self._bearer())
        if response.status_code == 401:
            raise BakalariAuthError(f"{path} still unauthorized after re-login")
        if response.status_code != 200:
            raise BakalariRequestError(f"GET {path} failed with HTTP {response.status_code}")
        return response.json()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "BakalariClient":
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.aclose()

    async def _token_request(self, form: dict[str, str]) -> BakalariTokens:
        response = await self._http.post(LOGIN_PATH, data={"client_id": CLIENT_ID, **form})
        if response.status_code != 200:
            raise BakalariAuthError(f"token request failed with HTTP {response.status_code}")
        body = response.json()
        access = body.get("access_token")
        if not access:
            raise BakalariAuthError("token response carried no access_token")
        return BakalariTokens(access_token=access, refresh_token=body.get("refresh_token"))

    async def _recover(self) -> None:
        """Refresh first; a rejected refresh falls back to a password login."""
        try:
            refreshed = await self.refresh()
        except BakalariAuthError:
            refreshed = None
        if refreshed is None:
            await self.login()

    def _bearer(self) -> dict[str, str]:
        if self._tokens is None:
            raise BakalariAuthError("no token held — call login() first")
        return {"Authorization": f"Bearer {self._tokens.access_token}"}
