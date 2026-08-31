"""Standalone Chromium supervisor.

Runs :class:`nidaro.chromium.ChromiumSupervisor` on its own: attaches to the
persistent browser on the configured CDP port, logs every attach/detach, and
shuts down on SIGINT/SIGTERM. The WhatsApp observer embeds the supervisor
directly; this entry point exists so supervision can run — and be verified —
on its own. Restarting it never touches the browser or its profile.
"""

import asyncio
import contextlib
import logging
import signal
import sys

from nidaro.chromium.supervisor import ChromiumSupervisor
from nidaro.config import get_settings

logger = logging.getLogger("nidaro.chromium")


async def _report_version(client) -> None:
    info = await client.send("Browser.getVersion")
    logger.info("browser reports itself as %s", info.get("product", info))


def _on_attach(client):
    return _report_version(client)


async def supervise() -> None:
    supervisor = ChromiumSupervisor(get_settings().chromium_cdp_port, _on_attach)
    task = asyncio.create_task(supervisor.run())
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, task.cancel)
    with contextlib.suppress(asyncio.CancelledError):
        await task


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )
    asyncio.run(supervise())
