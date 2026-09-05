"""``nagent ui``: open this machine's page as whoever ran it.

The command connects to the running agent's control socket, where the
kernel reports who is asking, mints a page token bound to that identity,
and opens the browser on a URL carrying it. Any account may run it; the
page shows that account's own scope, and ``sudo nagent ui`` shows the
privileged one.
"""

import shutil
import subprocess
import sys

from neutrino_agent.constants import (
    AGENT_CONTROL_PAGE_HOST,
    AGENT_CONTROL_PAGE_PORT,
    AGENT_SERVICE_NAME,
)
from neutrino_agent.control import client
from neutrino_agent.platforms.base import PlatformUnsupportedError
from neutrino_agent.platforms.detect import detect_platform

UI_NOT_RUNNING = (
    "the agent is not running, so there is nothing to open; start it: "
    f"sudo systemctl enable --now {AGENT_SERVICE_NAME}"
)


def main() -> int:
    """Mint a page token over the control socket and open the page.

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
        print(f"the agent refused a page token: {reply.get('code', status)}")
        return 1
    url = f"http://{AGENT_CONTROL_PAGE_HOST}:{AGENT_CONTROL_PAGE_PORT}/#{token}"
    print(url)
    opener = shutil.which("xdg-open")
    if opener:
        subprocess.Popen(
            [opener, url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    return 0
