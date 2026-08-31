"""Bakaláři mobile API v3 client tests: every request replays a fixture.

No live school system is ever contacted (ADR 0002): the transport is an
httpx.MockTransport that answers from tests/fixtures/bakalari — the same
payload shapes the [portal-1] research inventory documents.
"""

import json
from collections.abc import Callable
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from nidaro.connectors.bakalari_client import (
    BakalariAuthError,
    BakalariClient,
    BakalariRequestError,
)

type Route = httpx.Response | Callable[[httpx.Request, int], httpx.Response]

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "bakalari"
BASE_URL = "https://skola.example.cz"


def fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


async def _answer(request: httpx.Request) -> tuple:
    content = (await request.aread()).decode()
    return (
        request.method,
        request.url.path,
        request.headers.get("authorization"),
        dict(request.url.params),
        parse_qs(content),
    )


def replay(routes: dict[tuple[str, str], Route]):
    """MockTransport handler: routes (method, path) → status/json or callable."""
    seen: list[tuple] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(await _answer(request))
        responder = routes.get((request.method, request.url.path))
        if responder is None:
            return httpx.Response(404, json={"Message": "no fixture for this route"})
        if callable(responder):
            return responder(request, len(seen))
        return responder

    return handler, seen


def json_response(name_or_body, status: int = 200) -> httpx.Response:
    body = fixture(name_or_body) if isinstance(name_or_body, str) else name_or_body
    return httpx.Response(status, json=body)


def make_client(routes) -> tuple[BakalariClient, list]:
    handler, seen = replay(routes)
    client = BakalariClient(
        BASE_URL, "rodic@example.cz", "tajne-heslo", transport=httpx.MockTransport(handler)
    )
    return client, seen


LOGIN_OK = json_response("login.json")
USER_OK = json_response("user.json")


@pytest.mark.anyio
async def test_login_posts_andr_password_grant():
    client, seen = make_client({("POST", "/api/login"): LOGIN_OK})

    tokens = await client.login()

    assert tokens.access_token == "fixture-access-token"
    assert tokens.refresh_token == "fixture-refresh-token"
    method, path, _, _, form = seen[0]
    assert (method, path) == ("POST", "/api/login")
    assert form["client_id"] == ["ANDR"]
    assert form["grant_type"] == ["password"]
    assert form["username"] == ["rodic@example.cz"]
    assert form["password"] == ["tajne-heslo"]


@pytest.mark.anyio
async def test_module_reads_are_get_bearer_after_login():
    client, seen = make_client(
        {
            ("POST", "/api/login"): LOGIN_OK,
            ("GET", "/api/3/user"): USER_OK,
            ("GET", "/api/3/timetable/actual"): json_response("timetable_actual.json"),
            ("GET", "/api/3/substitutions"): json_response("substitutions.json"),
            ("GET", "/api/3/marks"): json_response("marks.json"),
            ("GET", "/api/3/homeworks"): json_response("homeworks.json"),
        }
    )

    await client.login()
    user = await client.user()
    timetable = await client.timetable_actual(date(2026, 5, 13))
    substitutions = await client.substitutions(date(2026, 5, 13))
    marks = await client.marks()
    homework = await client.homeworks(date(2026, 4, 29), date(2026, 5, 27))

    assert user["UserType"] == "parents"
    assert timetable["Days"][0]["Date"].startswith("2026-05-13")
    assert substitutions[0]["Hour"] == 3
    assert marks["Subjects"][0]["Subject"]["Abbrev"] == "M"
    assert homework["Homeworks"][0]["Id"] == "hw-1"

    reads = [entry for entry in seen if entry[0] == "GET"]
    assert len(reads) == 5
    for _, path, authorization, _params, _ in reads:
        assert authorization == "Bearer fixture-access-token"
        assert path.startswith("/api/3/")
    day_params = reads[1][3]
    assert day_params == {"date": "2026-05-13"}
    window = reads[4][3]
    assert window == {"from": "2026-04-29", "to": "2026-05-27"}
    assert all(entry[1] != "/api/login" or entry[0] == "POST" for entry in seen)


@pytest.mark.anyio
async def test_get_without_login_logs_in_first():
    client, seen = make_client({("POST", "/api/login"): LOGIN_OK, ("GET", "/api/3/user"): USER_OK})

    user = await client.user()

    assert user["EnabledModules"]["Marks"]["Rights"]["ShowMarks"] is True
    assert [entry[0] for entry in seen] == ["POST", "GET"]


@pytest.mark.anyio
async def test_expired_token_recovers_with_refresh_grant():
    calls = {"user": 0}

    def user_route(request, call_index):
        calls["user"] += 1
        if calls["user"] == 1:
            return httpx.Response(401, json={"Message": "Authorization has been denied"})
        return USER_OK

    refreshed = json_response({**fixture("login.json"), "access_token": "refreshed-access-token"})
    client, seen = make_client(
        {
            ("POST", "/api/login"): lambda request, _: refreshed,
            ("GET", "/api/3/user"): user_route,
        }
    )

    user = await client.login()
    await client.user()

    assert user.refresh_token == "fixture-refresh-token"
    grants = [entry[4].get("grant_type", [None])[0] for entry in seen if entry[0] == "POST"]
    assert grants == ["password", "refresh_token"]
    assert seen[-1][2] == "Bearer refreshed-access-token"
    assert calls["user"] == 2


@pytest.mark.anyio
async def test_rejected_refresh_falls_back_to_password_login():
    calls = {"user": 0}

    def user_route(request, call_index):
        calls["user"] += 1
        if calls["user"] == 1:
            return httpx.Response(401, json={"Message": "Authorization has been denied"})
        return USER_OK

    def login_route(request, _):
        grant = parse_qs(request.read().decode()).get("grant_type", [None])[0]
        if grant == "refresh_token":
            return httpx.Response(400, json={"error": "invalid_grant"})
        return LOGIN_OK

    client, seen = make_client(
        {
            ("POST", "/api/login"): login_route,
            ("GET", "/api/3/user"): user_route,
        }
    )

    await client.login()
    await client.user()

    grants = [entry[4].get("grant_type", [None])[0] for entry in seen if entry[0] == "POST"]
    assert grants == ["password", "refresh_token", "password"]
    assert seen[-1][2] == "Bearer fixture-access-token"
    assert calls["user"] == 2


@pytest.mark.anyio
async def test_still_unauthorized_after_relogin_raises_auth_error():
    denied = httpx.Response(401, json={"Message": "Authorization has been denied"})

    def login_route(request, call_index):
        if call_index == 1:
            return LOGIN_OK
        return denied

    client, _ = make_client(
        {
            ("POST", "/api/login"): login_route,
            ("GET", "/api/3/user"): lambda request, _: denied,
        }
    )

    await client.login()
    with pytest.raises(BakalariAuthError):
        await client.user()


@pytest.mark.anyio
async def test_bad_password_raises_auth_error():
    client, _ = make_client(
        {
            ("POST", "/api/login"): httpx.Response(
                400, json={"error": "invalid_grant", "error_description": "bad credentials"}
            )
        }
    )

    with pytest.raises(BakalariAuthError):
        await client.login()


@pytest.mark.anyio
async def test_server_error_raises_request_error():
    client, _ = make_client(
        {
            ("POST", "/api/login"): LOGIN_OK,
            ("GET", "/api/3/marks"): httpx.Response(500, json={"Message": "boom"}),
        }
    )

    await client.login()
    with pytest.raises(BakalariRequestError):
        await client.marks()
