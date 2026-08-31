"""Chromium supervisor against fakes: attach, death detection, reconnect.

No real browser takes part — resolver and client factory are the seams the
supervisor exposes for exactly this. The deployment half of the ticket
(persistent profile, UA, Xvfb) lives in compose.yml and deploy/quadlet and
is exercised by the runbook, not by these tests.

Every scenario self-terminates: the injected sleep stops the supervisor
after a chosen number of sleeps, so ``run()`` always returns and the test
awaits it directly. The fake sleep never waits in real time.
"""

import asyncio
from contextlib import suppress

import pytest

from nidaro.chromium.supervisor import ChromiumSupervisor

pytestmark = pytest.mark.anyio

URL = "ws://127.0.0.1:9222/devtools/browser/fake"
POLL = 5.0
PING = 10.0


class FakeClient:
    def __init__(self, label: str, survive_pings: int | None = None):
        self.label = label
        self.pings = 0
        self._survive_pings = survive_pings
        self.closed = False

    async def send(self, method: str, params: dict | None = None) -> dict:
        assert method == "Browser.getVersion"
        self.pings += 1
        if self._survive_pings is not None and self.pings > self._survive_pings:
            raise ConnectionError("browser died")
        return {"product": f"FakeChrome/1 ({self.label})"}

    async def close(self) -> None:
        self.closed = True


class FakeBrowser:
    """Refuses resolves/connects until started; hands out labelled clients.

    ``refused_resolves``/``refused_connects`` simulate a browser that is
    down or mid-restart; ``script`` queues specific clients (e.g. one that
    dies after N pings) to be issued by subsequent connects.
    """

    def __init__(self) -> None:
        self.started = False
        self.refused_resolves = 0
        self.refused_connects = 0
        self.script: list[FakeClient] = []
        self.clients: list[FakeClient] = []

    async def resolve_ws_url(self) -> str:
        if not self.started or self.refused_resolves > 0:
            self.refused_resolves = max(0, self.refused_resolves - 1)
            raise ConnectionError("no browser listening on port 9222")
        return URL

    async def connect_client(self, ws_url: str) -> FakeClient:
        assert ws_url == URL
        if not self.started or self.refused_connects > 0:
            self.refused_connects = max(0, self.refused_connects - 1)
            raise ConnectionError("connection refused")
        if self.script:
            client = self.script.pop(0)
        else:
            client = FakeClient(f"client-{len(self.clients) + 1}")
        self.clients.append(client)
        return client


class Recorder:
    def __init__(self) -> None:
        self.attached: list[FakeClient] = []
        self.detached = 0

    async def on_attach(self, client) -> None:
        self.attached.append(client)

    async def on_detach(self) -> None:
        self.detached += 1


class Clock:
    """Sleep that returns immediately and can stop the supervisor."""

    def __init__(self) -> None:
        self.durations: list[float] = []
        self.stop_after: int | None = None
        self._supervisor: ChromiumSupervisor | None = None

    def stop_supervisor(self) -> None:
        assert self._supervisor is not None
        self._supervisor.stop()

    async def __call__(self, seconds: float) -> None:
        self.durations.append(seconds)
        if self.stop_after is not None and len(self.durations) >= self.stop_after:
            self.stop_supervisor()
        await asyncio.sleep(0)


def build(browser: FakeBrowser, recorder: Recorder, clock: Clock) -> ChromiumSupervisor:
    supervisor = ChromiumSupervisor(
        9222,
        recorder.on_attach,
        recorder.on_detach,
        ping_seconds=PING,
        poll_seconds=POLL,
        resolve_ws_url=browser.resolve_ws_url,
        connect_client=browser.connect_client,
        sleep=clock,
    )
    clock._supervisor = supervisor
    return supervisor


async def test_attach_hands_a_live_client_to_the_consumer():
    browser, recorder, clock = FakeBrowser(), Recorder(), Clock()
    browser.started = True
    clock.stop_after = 1  # stop during the first ping sleep
    supervisor = build(browser, recorder, clock)

    await asyncio.wait_for(supervisor.run(), timeout=1)

    assert recorder.attached == browser.clients
    assert len(recorder.attached) == 1
    assert browser.clients[0].pings == 1
    assert clock.durations == [PING]


async def test_waits_through_backoff_while_the_browser_is_down():
    browser, recorder, clock = FakeBrowser(), Recorder(), Clock()
    browser.started = True
    browser.refused_resolves = 2
    clock.stop_after = 3  # two retries plus the first ping sleep
    supervisor = build(browser, recorder, clock)

    await asyncio.wait_for(supervisor.run(), timeout=1)

    assert len(recorder.attached) == 1
    assert clock.durations[:2] == [POLL, POLL * 2]


async def test_backoff_grows_to_its_cap_while_the_browser_stays_down():
    browser, recorder, clock = FakeBrowser(), Recorder(), Clock()
    clock.stop_after = 6
    supervisor = build(browser, recorder, clock)

    await asyncio.wait_for(supervisor.run(), timeout=1)

    assert recorder.attached == []
    assert clock.durations == [5.0, 10.0, 20.0, 40.0, 60.0, 60.0]


async def test_reattaches_after_a_browser_crash():
    browser, clock = FakeBrowser(), Clock()
    browser.started = True
    browser.script.append(FakeClient("doomed", survive_pings=1))

    class StopOnSecondAttach(Recorder):
        async def on_attach(self, client) -> None:
            await super().on_attach(client)
            if len(self.attached) == 2:
                clock.stop_supervisor()

    recorder = StopOnSecondAttach()
    supervisor = build(browser, recorder, clock)

    await asyncio.wait_for(supervisor.run(), timeout=1)

    doomed, replacement = browser.clients
    assert doomed.pings == 2  # survived the first ping, died on the second
    assert recorder.attached == [doomed, replacement]
    assert recorder.detached == 1
    assert doomed.closed
    assert replacement.closed


async def test_shutdown_closes_the_session_without_firing_on_detach():
    browser, recorder, clock = FakeBrowser(), Recorder(), Clock()
    browser.started = True
    clock.stop_after = 1
    supervisor = build(browser, recorder, clock)

    await asyncio.wait_for(supervisor.run(), timeout=1)

    (client,) = browser.clients
    assert client.closed
    assert recorder.detached == 0


async def test_cancellation_closes_the_session():
    browser, recorder, clock = FakeBrowser(), Recorder(), Clock()
    browser.started = True
    supervisor = build(browser, recorder, clock)

    task = asyncio.create_task(supervisor.run())
    await asyncio.sleep(0)  # one loop turn: the supervisor attaches, then sleeps
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task

    assert recorder.attached == [browser.clients[0]]
    assert browser.clients[0].closed


async def test_restarted_supervisor_reattaches_to_the_same_browser():
    """A supervisor restart is a fresh attach to the untouched browser —
    the property that keeps the linked WhatsApp session alive."""
    browser, recorder, clock = FakeBrowser(), Recorder(), Clock()
    browser.started = True

    clock.stop_after = 1
    await asyncio.wait_for(build(browser, recorder, clock).run(), timeout=1)

    clock.stop_after = 2
    await asyncio.wait_for(build(browser, recorder, clock).run(), timeout=1)

    assert len(recorder.attached) == 2
    assert recorder.attached[1] is not recorder.attached[0]
    assert all(client.closed for client in browser.clients)


@pytest.mark.parametrize("failure", ["resolve", "connect"])
async def test_failure_either_side_of_the_socket_counts_as_downtime(failure):
    browser, recorder, clock = FakeBrowser(), Recorder(), Clock()
    browser.started = True
    if failure == "resolve":
        browser.refused_resolves = 1
    else:
        browser.refused_connects = 1
    clock.stop_after = 2  # one retry sleep plus the first ping sleep
    supervisor = build(browser, recorder, clock)

    await asyncio.wait_for(supervisor.run(), timeout=1)

    assert len(recorder.attached) == 1
    assert clock.durations[0] == POLL
