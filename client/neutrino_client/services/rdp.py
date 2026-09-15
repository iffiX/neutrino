"""The rdp service type: connecting to a desktop another machine shares.

Connect opens a ``service`` stream to the hub for the share's address and
access password, then starts the carried RustDesk viewer at it. The password
travels in the one close and the one argument vector and lands in no log
and no state. The viewer processes are tracked by service key so a shutdown,
or a hub letting go, closes them.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import os
import subprocess
import sys
import threading

from neutrino_client import bundled
from neutrino_client.services.base import (
    ServiceTypeHandler,
    channel_refusal,
    find_entry,
    hub_of_key,
    service_key,
)
from neutrino_client.services.worker import ServiceWorker

RDP_ACTION_CONNECT = "connect"
RUSTDESK_DIRECT_PORT = 21118
RDP_CLOSE_TIMEOUT_S = 5


def connect_peer(host: str, port: int) -> str:
    """What the viewer is told to connect to.

    RustDesk dials a bare address at its own default direct port, so a share
    on that port is named by address alone; any other port is spelled out.

    Args:
        host: The address the sharing machine is reached at.
        port: The port its direct server answers on.

    Returns:
        The peer string, empty when there is no address to dial.
    """
    if not host:
        return ""
    if port == RUSTDESK_DIRECT_PORT:
        return host
    return f"{host}:{port}"


def client_invocation(binary: str, peer: str, password: str) -> list:
    """How to start the viewer at one shared desktop.

    Args:
        binary: The RustDesk binary.
        peer: What to dial.
        password: The share's access password.

    Returns:
        The argument vector.

    Raises:
        LookupError: When this process owns no display, so a spawn would
            open a window nobody sees. Only Linux names its display in the
            environment; Windows and macOS hand every process of a session
            its screen.
    """
    if sys.platform.startswith("linux") and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    ):
        raise LookupError("no display to open a window on")
    return [binary, "--connect", peer, "--password", password]


# The one step the desktop lane runs, in the page's vocabulary.
RDP_STEP_CONNECTING = "connecting"


def _nobody() -> None:
    """Nobody listening for changes."""


class RdpViewerHandler(ServiceTypeHandler):
    """Opens the carried RustDesk viewer at desktops the fleet shares."""

    service_type = "rdp"

    def __init__(
        self, *, platform, open_service, log=print, on_change=None, start_thread=None
    ):
        """
        Args:
            platform: The machine's platform, behind the contract.
            open_service: Callable ``(hub_id, entry_id) -> dict`` opening
                the entry's ``service`` stream on that hub and returning its
                close's params; raises the channel's exceptions.
            log: Callable used for progress messages.
            on_change: Called after every change of standing; None for
                nobody listening.
            start_thread: The lane's thread starter; None uses a daemon
                thread.
        """
        self._platform = platform
        self._open_service = open_service
        self._log = log
        self._lock = threading.Lock()
        # The viewer processes, by service key.
        self._viewers: dict = {}
        self._on_change = on_change if on_change is not None else _nobody
        self._worker = ServiceWorker(
            name="rdp", on_change=self._on_change, log=log, start_thread=start_thread
        )

    def act(self, *, entries: list, body: dict):
        """Connect to one shared desktop.

        Args:
            entries: The merged service list.
            body: ``{"action": "connect", "hub_id", "id"}``.

        Returns:
            Empty on success, ``{"code", "params"}`` on a refusal.
        """
        if str(body.get("action", "")) != RDP_ACTION_CONNECT:
            return {"code": "unknown_request", "params": {}}
        entry = find_entry(
            entries,
            self.service_type,
            str(body.get("hub_id", "")),
            str(body.get("id", "")),
        )
        if entry is None:
            return {"code": "unknown_request", "params": {}}
        key = service_key(str(entry.get("hub_id", "")), str(entry.get("id", "")))

        def open_viewer() -> dict:
            return self._open(entry, key)

        return self._worker.submit(f"{RDP_STEP_CONNECTING}:{key}", open_viewer)

    def _open(self, entry: dict, key: str) -> dict:
        """Take the seat's material from the hub and start the viewer at it.

        Args:
            entry: The desktop's service entry.
            key: The entry's service key.

        Returns:
            Empty when the viewer started, ``{"code", "params"}`` otherwise.
        """
        binary = bundled.rustdesk_path()
        if not binary:
            return bundled.bundle_missing("rustdesk")
        try:
            reply = self._open_service(
                str(entry.get("hub_id", "")), str(entry.get("id", ""))
            )
        except Exception as error:  # noqa: BLE001 - a refusal, never a crash
            return channel_refusal(error)
        try:
            port = int(reply.get("port") or RUSTDESK_DIRECT_PORT)
        except (TypeError, ValueError):
            port = RUSTDESK_DIRECT_PORT
        peer = connect_peer(str(reply.get("host", "")), port)
        if not peer:
            return {"code": "rdp_no_address", "params": {}}
        try:
            invocation = client_invocation(binary, peer, str(reply.get("password", "")))
        except LookupError:
            return {"code": "rdp_no_desktop", "params": {}}
        try:
            process = self._platform.start_on_screen(invocation)
        except (OSError, subprocess.SubprocessError) as error:
            return {"code": "rdp_launch_failed", "params": {"detail": str(error)}}
        with self._lock:
            self._viewers[key] = process
        self._log(f"opened the desktop viewer for {key}")
        return {}

    def state(self) -> dict:
        """Which desktops a viewer is open on.

        Returns:
            ``{"viewers": {service_key: {"is_running"}}}``.
        """
        with self._lock:
            self._prune()
            viewers = {key: {"is_running": True} for key in self._viewers}
        return {"viewers": viewers, "rdp_work": self._worker.status()}

    def release(self) -> int:
        """Close every viewer this resident opened.

        Returns:
            How many viewers were closed.
        """
        return self.close_all()

    def release_hub(self, hub_id: str) -> int:
        """Close every viewer open on one hub's desktops.

        Args:
            hub_id: The hub whose viewers are closed.

        Returns:
            How many were still running and were ended.
        """
        with self._lock:
            viewers = {
                key: process
                for key, process in self._viewers.items()
                if hub_of_key(key) == hub_id
            }
            for key in viewers:
                self._viewers.pop(key, None)
        return self._terminate(viewers)

    def close_all(self) -> int:
        """Terminate every viewer process still running.

        Returns:
            How many were still running and were ended.
        """
        with self._lock:
            viewers = dict(self._viewers)
            self._viewers = {}
        return self._terminate(viewers)

    @staticmethod
    def _terminate(viewers: dict) -> int:
        closed = 0
        for process in viewers.values():
            if process.poll() is not None:
                continue
            closed += 1
            try:
                process.terminate()
                process.wait(timeout=RDP_CLOSE_TIMEOUT_S)
            except (OSError, subprocess.SubprocessError):
                try:
                    process.kill()
                except OSError:
                    pass
        return closed

    def _prune(self) -> None:
        """Forget viewers the person already closed. Call under the lock."""
        for key in list(self._viewers):
            if self._viewers[key].poll() is not None:
                self._viewers.pop(key, None)
