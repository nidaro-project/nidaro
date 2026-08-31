"""CDP supervision for the persistent Chromium.

The WhatsApp bridge drives a real Chromium that is *not* managed by this
process: it runs as its own service (a compose service in development, a
Quadlet unit in the prod pod) with a persistent ``--user-data-dir`` on a
volume, headed under Xvfb with a normal-Chrome user agent. That is what
keeps a linked WhatsApp session alive across restarts — chrome-agent's
``launch``/``stop`` registry wipes instance session directories, logging
the device out (the §3.4 PoC gotcha in docs/research/whatsapp-integration.md).
This module therefore never launches a browser and never touches the
registry; it only attaches to the running one.

:class:`ChromiumSupervisor` resolves the browser-level WebSocket URL with
chrome-agent's ``get_ws_url`` (the endpoint its attach mode uses — stable
across tab navigation, unlike per-page URLs), attaches a
:class:`chrome_agent.cdp_client.CDPClient`, and hands it to the consumer
through ``on_attach``. While attached it pings ``Browser.getVersion``;
when a ping fails — browser crashed, port gone — the consumer is told via
``on_detach`` and the supervisor retries with capped backoff until the
browser service comes back, then reattaches.
"""

import asyncio
import logging

from chrome_agent.cdp_client import CDPClient, get_ws_url

logger = logging.getLogger(__name__)

POLL_SECONDS = 5.0
PING_SECONDS = 10.0
MAX_BACKOFF_SECONDS = 60.0


class ChromiumSupervisor:
    """Keep one CDP client attached to the persistent Chromium.

    ``on_attach`` receives every newly connected client; ``on_detach`` fires
    when that client's connection was lost while the supervisor keeps running
    (browser death). Neither fires when the supervisor itself shuts down —
    the consumer lives in the same process and is shutting down with it;
    :meth:`run` closes the client on its way out.

    ``resolve_ws_url``, ``connect_client``, and ``sleep`` are seams for
    tests; the defaults talk to the real browser over CDP.
    """

    def __init__(
        self,
        port: int,
        on_attach,
        on_detach=None,
        *,
        ping_seconds: float = PING_SECONDS,
        poll_seconds: float = POLL_SECONDS,
        max_backoff_seconds: float = MAX_BACKOFF_SECONDS,
        resolve_ws_url=None,
        connect_client=None,
        sleep=asyncio.sleep,
    ):
        self.port = port
        self._on_attach = on_attach
        self._on_detach = on_detach
        self._ping_seconds = ping_seconds
        self._poll_seconds = poll_seconds
        self._max_backoff_seconds = max_backoff_seconds
        self._resolve_ws_url = resolve_ws_url or self._resolve_ws_url_default
        self._connect_client = connect_client or self._connect_client_default
        self._sleep = sleep
        self._running = False
        self._client: CDPClient | None = None

    async def run(self) -> None:
        """Attach, watch, and reattach until :meth:`stop` or cancellation."""
        self._running = True
        backoff = self._poll_seconds
        try:
            while self._running:
                client = await self._attach(backoff)
                if client is None:  # stop() landed while the browser was down
                    break
                backoff = self._poll_seconds
                await self._watch(client)
        finally:
            self._running = False
            if self._client is not None:
                client, self._client = self._client, None
                logger.info("Detaching from Chromium on port %s (supervisor stopping)", self.port)
                await _best_effort_close(client)

    def stop(self) -> None:
        """Ask :meth:`run` to return; it stops within one loop iteration."""
        self._running = False

    async def _attach(self, backoff: float):
        while self._running:
            try:
                ws_url = await self._resolve_ws_url()
                client = await self._connect_client(ws_url)
            except Exception as exc:
                logger.warning(
                    "Chromium not reachable on port %s (%s); retrying in %.0fs",
                    self.port,
                    exc,
                    backoff,
                )
                await self._sleep(backoff)
                backoff = min(backoff * 2, self._max_backoff_seconds)
                continue
            self._client = client
            logger.info("Attached to Chromium on port %s", self.port)
            try:
                await self._on_attach(client)
            except Exception:
                logger.exception("on_attach consumer failed; supervising anyway")
            return client
        return None

    async def _watch(self, client) -> None:
        while self._running:
            await self._sleep(self._ping_seconds)
            try:
                await client.send("Browser.getVersion")
            except Exception as exc:
                await self._lose(client, exc)
                return

    async def _lose(self, client, reason: Exception) -> None:
        logger.warning("Lost Chromium on port %s (%s); will reattach", self.port, reason)
        self._client = None
        await _best_effort_close(client)
        if self._on_detach is not None:
            try:
                await self._on_detach()
            except Exception:
                logger.exception("on_detach consumer failed")

    async def _resolve_ws_url_default(self) -> str:
        # get_ws_url probes the HTTP endpoint with a blocking urllib call and
        # raises ConnectionError while the browser service is down.
        return await asyncio.to_thread(get_ws_url, self.port, "browser")

    async def _connect_client_default(self, ws_url: str) -> CDPClient:
        client = CDPClient(ws_url)
        await client.connect()
        return client


async def _best_effort_close(client) -> None:
    try:
        await client.close()
    except Exception:
        logger.debug("closing a dead CDP client failed", exc_info=True)
