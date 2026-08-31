"""Google OAuth 2.0 web-server flow, spoken directly over httpx.

Three-legged OAuth only — service accounts cannot reach personal @gmail.com
calendars without Workspace domain-wide delegation. One consent per family
member yields a refresh token (`access_type=offline`); the token protocol is
two plain POSTs, so `google-auth` and the blocking `google-api-python-client`
stay out of the dependency tree.

`refresh_token is None` on an exchange means Google still holds the token it
issued on the member's first consent — re-consent forces a fresh one via
`prompt=consent`, which `authorization_url` always sets.
"""

from typing import Any
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel

from nidaro.config import Settings

AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"

# calendar.events covers incremental sync AND writes (insert/update/delete)
# on all calendars the member can reach, including calendars shared with
# them — the household use case. Read-only households can narrow this later.
CALENDAR_EVENTS_SCOPE = "https://www.googleapis.com/auth/calendar.events"
SCOPES = [CALENDAR_EVENTS_SCOPE]


class GoogleOAuthError(RuntimeError):
    """Google's token endpoint rejected the request."""


class InvalidGrantError(GoogleOAuthError):
    """`invalid_grant`: the refresh token is dead (revoked, expired, or the
    7-day Testing-mode expiry). The only recovery is a fresh consent — the
    account must be reconnected."""


class GoogleOAuthSettings(BaseModel):
    client_id: str
    client_secret: str
    redirect_uri: str

    @classmethod
    def from_settings(cls, settings: Settings) -> "GoogleOAuthSettings | None":
        """Configured OAuth client, or None when the connector stays dormant."""
        if not settings.google_client_id or not settings.google_client_secret:
            return None
        return cls(
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            redirect_uri=settings.google_redirect_uri,
        )


class GoogleTokenResponse(BaseModel):
    access_token: str
    expires_in: int = 3600
    refresh_token: str | None = None
    scope: str = ""


def authorization_url(oauth: GoogleOAuthSettings, *, state: str) -> str:
    """The consent screen URL for one member's connect flow.

    `access_type=offline` requests the refresh token; `prompt=consent`
    guarantees Google re-issues it even when the member had consented before
    (Google otherwise returns `refresh_token` only on first authorization).
    """
    params = {
        "client_id": oauth.client_id,
        "redirect_uri": oauth.redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"{AUTHORIZATION_ENDPOINT}?{urlencode(params)}"


async def exchange_code(
    oauth: GoogleOAuthSettings, code: str, *, http: httpx.AsyncClient
) -> GoogleTokenResponse:
    """Swap the authorization code from the callback for tokens."""
    return await _token_request(
        http,
        {
            "code": code,
            "client_id": oauth.client_id,
            "client_secret": oauth.client_secret,
            "redirect_uri": oauth.redirect_uri,
            "grant_type": "authorization_code",
        },
    )


async def refresh_access_token(
    oauth: GoogleOAuthSettings, refresh_token: str, *, http: httpx.AsyncClient
) -> GoogleTokenResponse:
    """Exchange a refresh token for a fresh access token (~1 hour)."""
    return await _token_request(
        http,
        {
            "refresh_token": refresh_token,
            "client_id": oauth.client_id,
            "client_secret": oauth.client_secret,
            "grant_type": "refresh_token",
        },
    )


async def _token_request(http: httpx.AsyncClient, form: dict[str, Any]) -> GoogleTokenResponse:
    response = await http.post("https://oauth2.googleapis.com/token", data=form)
    if response.status_code != 200:
        detail = _error_detail(response)
        if detail == "invalid_grant":
            raise InvalidGrantError(
                "Google rejected the grant (invalid_grant): the refresh token was "
                "revoked, expired, or exceeded Google's live-token budget — the "
                "account must be reconnected"
            )
        raise GoogleOAuthError(f"Google token endpoint returned {response.status_code}: {detail}")
    return GoogleTokenResponse.model_validate(response.json())


def _error_detail(response: httpx.Response) -> str:
    try:
        return str(response.json().get("error", response.text))
    except ValueError:
        return response.text
