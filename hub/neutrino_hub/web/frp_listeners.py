"""The channel on each frp vendor's loopback listener.

frpc on the hub forwards a vendor's node to ``127.0.0.1`` at the vendor's
own port, where the panel's process serves the same channel app as on the
agent port, under the same counts. A listener is open while its way in is
on and closed when it is turned off, on the process's own loop and without
a restart. One whose port another program's socket holds is recorded as
taken, and the vendor's state says so.

Not pure: holds sockets.
"""

import asyncio
import contextlib
import logging
import threading
from typing import Callable

import uvicorn

from neutrino_hub.modules.frp.constants import (
    FRP_LOOPBACK_HOST,
    FRP_LOOPBACK_PORTS,
)
from neutrino_hub.web.agent_port import bound_socket

LOGGER = logging.getLogger(__name__)

# How long a converge waits for the loop to open or close the listeners.
FRP_LISTENERS_SETTLE_TIMEOUT_S = 30.0
# How often an opening listener is asked whether it listens yet.
FRP_LISTENERS_START_POLL_S = 0.01


class FrpLoopbackServer(uvicorn.Server):
    """uvicorn's server on one loopback socket, leaving the process's signal
    handlers to the servers it started with."""

    @contextlib.contextmanager
    def capture_signals(self):
        """Take no signal: a listener opened and closed while the process
        runs would otherwise put back handlers of servers already gone."""
        yield


class FrpLoopbackListeners:
    """The vendors' listeners, opened and closed on the serving loop."""

    def __init__(self):
        self._lock = threading.Lock()
        self._loop: "asyncio.AbstractEventLoop | None" = None
        self._config_of: "Callable[[int], uvicorn.Config] | None" = None
        self._wanted: dict = {}
        self._serving: dict = {}
        self._taken: set = set()

    def attach(self, loop, config_of: Callable[[int], uvicorn.Config]) -> None:
        """Serve on this loop from now on.

        Args:
            loop: The loop the agent port is served on.
            config_of: Builds the channel's server configuration for a port.
        """
        with self._lock:
            self._loop = loop
            self._config_of = config_of

    def follow(self, wanted: dict) -> None:
        """Open each vendor's listener that is wanted and close the others.

        Callable from any thread; a process that serves no channel, as a
        command-line run, opens nothing.

        Args:
            wanted: Vendor to whether its way in is on.
        """
        with self._lock:
            self._wanted = dict(wanted)
            loop = self._loop
        if loop is None or loop.is_closed():
            return
        future = asyncio.run_coroutine_threadsafe(self.settle(), loop)
        if _is_loop_thread(loop):
            return
        try:
            future.result(timeout=FRP_LISTENERS_SETTLE_TIMEOUT_S)
        except (TimeoutError, OSError, RuntimeError) as error:
            LOGGER.warning("frp listeners not settled: %s", error)

    def is_taken(self, vendor: str) -> bool:
        """Whether a vendor's listener could not open.

        Args:
            vendor: ``sakurafrp`` or ``openfrp``.

        Returns:
            True while its way in is on and another program holds its port.
        """
        with self._lock:
            return vendor in self._taken

    async def settle(self) -> None:
        """Make the open listeners the wanted ones, on the loop."""
        with self._lock:
            wanted = dict(self._wanted)
            config_of = self._config_of
        for vendor, port in FRP_LOOPBACK_PORTS.items():
            is_wanted = bool(wanted.get(vendor))
            if is_wanted and vendor not in self._serving and config_of is not None:
                await self._open(vendor, port, config_of)
            elif not is_wanted:
                with self._lock:
                    self._taken.discard(vendor)
                await self._close(vendor)

    async def close(self) -> None:
        """Close every listener, as the process stops."""
        with self._lock:
            self._wanted = {}
        for vendor in list(self._serving):
            await self._close(vendor)

    async def _open(self, vendor: str, port: int, config_of: Callable) -> None:
        """Bind one listener, serve the channel on it, and wait until it
        listens."""
        try:
            sock = bound_socket(FRP_LOOPBACK_HOST, port)
        except OSError as error:
            LOGGER.warning(
                "the %s listener cannot open %s:%d: %s",
                vendor,
                FRP_LOOPBACK_HOST,
                port,
                error,
            )
            with self._lock:
                self._taken.add(vendor)
            return
        with self._lock:
            self._taken.discard(vendor)
        server = FrpLoopbackServer(config_of(port))
        task = asyncio.get_running_loop().create_task(server.serve(sockets=[sock]))
        self._serving[vendor] = (server, task, sock)
        while not server.started and not task.done():
            await asyncio.sleep(FRP_LISTENERS_START_POLL_S)
        LOGGER.info("the %s listener listens on %s:%d", vendor, FRP_LOOPBACK_HOST, port)

    async def _close(self, vendor: str) -> None:
        """Stop one listener and wait for it to end."""
        held = self._serving.pop(vendor, None)
        if held is None:
            return
        server, task, sock = held
        server.should_exit = True
        with contextlib.suppress(asyncio.CancelledError, OSError, RuntimeError):
            await task
        sock.close()
        LOGGER.info("the %s listener is closed", vendor)


def _is_loop_thread(loop) -> bool:
    """Whether the calling thread runs this loop."""
    try:
        return asyncio.get_running_loop() is loop
    except RuntimeError:
        return False
