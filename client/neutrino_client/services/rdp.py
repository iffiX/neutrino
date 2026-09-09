"""The rdp service type: connecting to a desktop another machine shares.

Connect asks the hub for the share's address and access password, then
starts the carried RustDesk viewer at it. The password travels in the one
reply and the one argument vector and lands in no log and no state. The
viewer processes are tracked so a shutdown closes them.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import os
import subprocess
import threading

from neutrino_client import bundled
from neutrino_client.constants import CLIENT_RDP_CONNECT_PATH
from neutrino_client.core.channel import (
    GatewayRefusedDetail,
    GatewayUnreachable,
    GatewayUntrusted,
)
from neutrino_client.services.base import ServiceTypeHandler, find_entry

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
            open a window nobody sees.
    """
    if os.name != "nt" and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    ):
        raise LookupError("no display to open a window on")
    return [binary, "--connect", peer, "--password", password]


class RdpViewerHandler(ServiceTypeHandler):
    """Opens the carried RustDesk viewer at desktops the fleet shares."""

    service_type = "rdp"

    def __init__(self, *, platform, post, log=print):
        """
        Args:
            platform: The machine's platform, behind the contract.
            post: Callable ``(path, payload) -> dict`` posting to the hub
                over the pinned channel; raises the channel's exceptions.
            log: Callable used for progress messages.
        """
        self._platform = platform
        self._post = post
        self._log = log
        self._lock = threading.Lock()
        self._viewers: dict = {}

    def act(self, *, entries: list, body: dict):
        """Connect to one shared desktop.

        Args:
            entries: The catalog's service list.
            body: ``{"action": "connect", "id"}``.

        Returns:
            Empty on success, ``{"code", "params"}`` on a refusal.
        """
        if str(body.get("action", "")) != RDP_ACTION_CONNECT:
            return {"code": "unknown_request", "params": {}}
        entry = find_entry(entries, self.service_type, str(body.get("id", "")))
        if entry is None:
            return {"code": "unknown_request", "params": {}}
        binary = bundled.rustdesk_path()
        if not binary:
            return bundled.bundle_missing("rustdesk")
        try:
            reply = self._post(CLIENT_RDP_CONNECT_PATH, {"id": entry.get("id")})
        except GatewayRefusedDetail as error:
            return {"code": error.code, "params": dict(error.params)}
        except GatewayUntrusted:
            return {"code": "hub_untrusted", "params": {}}
        except GatewayUnreachable as error:
            return {"code": "hub_unreachable", "params": {"detail": str(error)}}
        except Exception as error:  # noqa: BLE001 - a refusal, never a crash
            return {"code": "hub_refused", "params": {"detail": type(error).__name__}}
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
            self._viewers[str(entry.get("id"))] = process
        self._log(f"opened the desktop viewer for {entry.get('id')}")
        return {}

    def state(self) -> dict:
        """Which desktops a viewer is open on.

        Returns:
            ``{"viewers": {entry_id: {"is_running"}}}``.
        """
        with self._lock:
            self._prune()
            return {
                "viewers": {
                    entry_id: {"is_running": True} for entry_id in self._viewers
                }
            }

    def release(self) -> None:
        """Close every viewer this resident opened."""
        self.close_all()

    def close_all(self) -> None:
        """Terminate every viewer process still running."""
        with self._lock:
            viewers = dict(self._viewers)
            self._viewers = {}
        for process in viewers.values():
            if process.poll() is not None:
                continue
            try:
                process.terminate()
                process.wait(timeout=RDP_CLOSE_TIMEOUT_S)
            except (OSError, subprocess.SubprocessError):
                try:
                    process.kill()
                except OSError:
                    pass

    def _prune(self) -> None:
        """Forget viewers the person already closed. Call under the lock."""
        for entry_id in list(self._viewers):
            if self._viewers[entry_id].poll() is not None:
                self._viewers.pop(entry_id, None)
