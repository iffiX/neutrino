"""``nclient status``: what this person is bound to, and whether it works.

Three things break independently: the person never joined, the resident is
not running, or a hub cannot be reached from here. This says which: one
line per hub, then the resident's.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

from neutrino_client import CLIENT_VERSION
from neutrino_client.cli import wording
from neutrino_client.control import client
from neutrino_client.core import enrollment
from neutrino_client.core.session import CONNECTION_CONNECTED, CONNECTION_REPLACED
from neutrino_client.exceptions import PlatformUnsupportedError
from neutrino_client.platforms.detect import detect_platform

RESIDENT_RUNNING = "running"
RESIDENT_NOT_RUNNING = "not running; open it: nclient gui"


def main() -> int:
    """Report the three things that break independently.

    Returns:
        Process exit status: 0 when bound, running and every hub connected,
        1 otherwise.
    """
    print(f"neutrino-client {CLIENT_VERSION}")
    state = _local_state()
    if state is not None:
        return _status_from_resident(state)
    held = enrollment.bindings()
    if not held:
        print(f"hub        {wording.NOT_JOINED}")
    for binding in held:
        print(f"hub        {binding['gateway_url']}")
    print(f"resident   {RESIDENT_NOT_RUNNING}")
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
        Process exit status: 0 when bound and every hub connected, 1
        otherwise.
    """
    hubs = [hub for hub in state.get("hubs") or [] if isinstance(hub, dict)]
    if not hubs:
        print(f"hub        {wording.NOT_JOINED}")
        print(f"resident   {RESIDENT_RUNNING}")
        return 1
    is_clean = True
    for hub in hubs:
        connection = str(hub.get("connection_state", ""))
        print(f"hub        {hub.get('gateway_url', '')}   {connection}{_why(hub)}")
        is_clean = is_clean and connection == CONNECTION_CONNECTED
    print(f"resident   {RESIDENT_RUNNING}")
    return 0 if is_clean else 1


def _why(hub: dict) -> str:
    """What the resident last had to say about one hub's socket, if anything.

    Args:
        hub: The hub's row of the state payload.

    Returns:
        The wording after a colon, empty when there is nothing to add.
    """
    if hub.get("connection_state") == CONNECTION_REPLACED:
        return f": {wording.word_state(CONNECTION_REPLACED)}"
    error = hub.get("last_error")
    if not isinstance(error, dict) or not error.get("code"):
        return ""
    return f": {wording.word_code(str(error['code']), error.get('params'))}"
