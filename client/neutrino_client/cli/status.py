"""``nclient status``: what this person is bound to, and whether it works.

Three things break independently: the person never joined, the resident is
not running, or the hub cannot be reached from here. This says which, on
three lines: hub, resident, poll.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

from neutrino_client import CLIENT_VERSION
from neutrino_client.cli import wording
from neutrino_client.control import client
from neutrino_client.core import enrollment
from neutrino_client.platforms.base import PlatformUnsupportedError
from neutrino_client.platforms.detect import detect_platform

RESIDENT_RUNNING = "running"
RESIDENT_NOT_RUNNING = "not running; open it: nclient gui"
POLL_OK = "ok. The client polls every few seconds"
POLL_NOT_POLLED = "not polled while the client is not running"


def main() -> int:
    """Report the three things that break independently.

    Returns:
        Process exit status: 0 when bound, running and polling cleanly, 1
        otherwise.
    """
    print(f"neutrino-client {CLIENT_VERSION}")
    state = _local_state()
    if state is not None:
        return _status_from_resident(state)
    gateway_url = enrollment.load_config().get("gateway_url", "")
    if not gateway_url:
        print(f"hub        {wording.NOT_JOINED}")
        print(f"resident   {RESIDENT_NOT_RUNNING}")
        return 1
    print(f"hub        {gateway_url}   connected")
    print(f"resident   {RESIDENT_NOT_RUNNING}")
    print(f"poll       {POLL_NOT_POLLED}")
    return 1


def _local_state() -> "dict | None":
    """What the running resident says about itself, asked over its socket.

    Returns:
        The resident's own state, or None when nothing answers.
    """
    try:
        socket_path = detect_platform().control_socket_path()
    except PlatformUnsupportedError:
        return None
    try:
        status, state = client.request(
            socket_path=socket_path, method="GET", path="/api/state", timeout_s=2
        )
    except (OSError, ValueError):
        return None
    return state if status == 200 else None


def _status_from_resident(state: dict) -> int:
    """Report from the running resident's own account of itself.

    Args:
        state: The page's state payload.

    Returns:
        Process exit status: 0 when bound and polling cleanly, 1 otherwise.
    """
    if not state.get("is_connected"):
        print(f"hub        {wording.NOT_JOINED}")
        print(f"resident   {RESIDENT_RUNNING}")
        return 1
    print(f"hub        {state.get('gateway_url', '')}   connected")
    print(f"resident   {RESIDENT_RUNNING}")
    error = state.get("last_error")
    if isinstance(error, dict) and error.get("code"):
        print(f"poll       {wording.word_code(error['code'], error.get('params'))}")
        return 1
    print(f"poll       {POLL_OK}")
    return 0
