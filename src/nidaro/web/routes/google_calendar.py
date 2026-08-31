"""OAuth web flow for connecting family members' Google accounts.

Two routes: `/connect` bounces the member to Google's consent screen
(state cookie guards CSRF), `/callback` exchanges the code and stores the
refresh token encrypted via `GoogleCalendarAccountService.complete_connection`.
The redirect URI registered in Google Cloud Console must match
`NIDARO_GOOGLE_REDIRECT_URI` exactly (default: this callback route on the
LAN address the API is published on — see docs/deployment.md).
"""

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from nidaro.config import get_settings
from nidaro.connectors.google_calendar.accounts import GoogleConnectionError
from nidaro.connectors.google_calendar.oauth import GoogleOAuthSettings, authorization_url
from nidaro.container import ApplicationServices
from nidaro.web.dependencies import get_services

router = APIRouter(prefix="/api/v1/connectors/google-calendar", tags=["connectors"])

_STATE_COOKIE = "nidaro_gcal_oauth_state"
_STATE_MAX_AGE_SECONDS = 600


@router.get("/connect")
async def connect(services: ApplicationServices = Depends(get_services)) -> RedirectResponse:  # noqa: B008
    """Start one member's consent flow: bounce to Google's consent screen."""
    oauth = _require_oauth()
    household = await services.household.get_household()
    if household is None:
        raise HTTPException(status_code=404, detail="Household not seeded")
    state = secrets.token_urlsafe(32)
    response = RedirectResponse(authorization_url(oauth, state=state))
    response.set_cookie(
        _STATE_COOKIE, state, max_age=_STATE_MAX_AGE_SECONDS, httponly=True, samesite="lax"
    )
    return response


@router.get("/callback")
async def callback(
    request: Request,
    code: str,
    state: str,
    error: str | None = None,
    services: ApplicationServices = Depends(get_services),  # noqa: B008
) -> RedirectResponse:
    """Finish the consent flow: exchange the code, store the token encrypted."""
    oauth = _require_oauth()
    if error:
        raise HTTPException(status_code=400, detail=f"Connection not completed: {error}")
    if not state or request.cookies.get(_STATE_COOKIE) != state:
        raise HTTPException(
            status_code=400, detail="OAuth state mismatch — start the connection again"
        )
    household = await services.household.get_household()
    if household is None:
        raise HTTPException(status_code=404, detail="Household not seeded")
    try:
        await services.google_accounts.complete_connection(household.id, code, oauth=oauth)
    except GoogleConnectionError as connection_error:
        raise HTTPException(status_code=502, detail=str(connection_error)) from connection_error
    response = RedirectResponse("/settings?connected=google-calendar")
    response.delete_cookie(_STATE_COOKIE)
    return response


def _require_oauth() -> GoogleOAuthSettings:
    oauth = GoogleOAuthSettings.from_settings(get_settings())
    if oauth is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Google Calendar is not configured — set NIDARO_GOOGLE_CLIENT_ID and "
                "NIDARO_GOOGLE_CLIENT_SECRET (see docs/deployment.md)"
            ),
        )
    return oauth
