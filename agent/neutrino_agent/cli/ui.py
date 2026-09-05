"""``nagent ui``: open this machine's page as whoever ran it, and stay.

The command connects to the running agent's control socket, where the
kernel reports who is asking, mints a page token bound to that identity,
and opens the browser on a URL carrying it. The command is the session:
Ctrl-C revokes the token at once, and a closed window revokes it moments
later — the page's own polling is the token's pulse, and the agent expires
a token whose pulse stopped, which this waiting command notices.

Any account may run it; the page shows that account's own scope, and
``sudo nagent ui`` shows the privileged one. The agent refuses to mint
while it does not hold the loopback port, and this command says so.
"""

import sys
import time
import webbrowser

from neutrino_agent.constants import (
    AGENT_CONTROL_PAGE_HOST,
    AGENT_CONTROL_PAGE_PORT,
    AGENT_SERVICE_NAME,
    AGENT_UI_WATCH_INTERVAL_S,
)
from neutrino_agent.control import client
from neutrino_agent.platforms.base import PlatformUnsupportedError
from neutrino_agent.platforms.detect import detect_platform

UI_NOT_RUNNING = (
    "the agent is not running, so there is nothing to open; start it: "
    f"sudo systemctl enable --now {AGENT_SERVICE_NAME}"
)
UI_NO_PAGE = (
    "the agent is not serving its page — it was started with --no-ui, or "
    "the port is taken; no token was opened"
)
UI_WINDOW_CLOSED = "the window was closed; this session is over"
UI_REVOKED = "the agent ended this session"
UI_AGENT_GONE = "the agent stopped answering; this session is over"


def main() -> int:
    """Mint a page token, open the page, and wait for the session to end.

    Returns:
        Process exit status.
    """
    try:
        socket_path = detect_platform().control_socket_path()
    except PlatformUnsupportedError:
        print("this platform has no control socket yet", file=sys.stderr)
        return 1
    try:
        status, reply = client.request(
            socket_path=socket_path, method="POST", path="/api/token", body={}
        )
    except (OSError, ValueError):
        print(UI_NOT_RUNNING, file=sys.stderr)
        return 1
    token = str(reply.get("token", ""))
    if status != 200 or not token:
        if reply.get("code") == "control_page_not_served":
            print(UI_NO_PAGE, file=sys.stderr)
        else:
            print(f"the agent refused a page token: {reply.get('code', status)}")
        return 1
    port = int(reply.get("page_port") or AGENT_CONTROL_PAGE_PORT)
    url = f"http://{AGENT_CONTROL_PAGE_HOST}:{port}/#{token}"
    webbrowser.open(url)
    print(
        f"Please open {url} if the browser does not show up. "
        "Close the window or press Ctrl-C to stop."
    )
    try:
        return _wait(socket_path, token)
    except KeyboardInterrupt:
        _revoke(socket_path, token)
        return 0


def _wait(socket_path: str, token: str) -> int:
    """Poll the token's aliveness until its pulse stops.

    Args:
        socket_path: The agent's control socket.
        token: This session's token.

    Returns:
        Process exit status.
    """
    while True:
        time.sleep(AGENT_UI_WATCH_INTERVAL_S)
        try:
            status, reply = client.request(
                socket_path=socket_path,
                method="POST",
                path="/api/token/watch",
                body={"token": token},
            )
        except (OSError, ValueError):
            print(UI_AGENT_GONE)
            return 0
        if status != 200 or not reply.get("is_alive"):
            # A claimed pulse that stopped is a window somebody closed; a
            # token that died unclaimed was revoked or the agent restarted —
            # nobody ever saw a window to close.
            print(UI_WINDOW_CLOSED if reply.get("is_claimed") else UI_REVOKED)
            return 0


def _revoke(socket_path: str, token: str) -> None:
    """Revoke this session's token at once. Best-effort.

    Args:
        socket_path: The agent's control socket.
        token: The token to revoke.
    """
    try:
        client.request(
            socket_path=socket_path,
            method="POST",
            path="/api/token/revoke",
            body={"token": token},
        )
    except (OSError, ValueError):
        pass
