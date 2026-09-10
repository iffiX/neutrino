"""``nclient quit``: stop the running client.

The client's services exist only while it runs, so quitting is what puts
this machine back: the tools restored, the shares unmounted, the forwards
and the viewers closed. The running resident does that itself; this asks it
to, over the control socket, as whoever ran the command.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import sys

from neutrino_client.cli import wording
from neutrino_client.control import client
from neutrino_client.exceptions import PlatformUnsupportedError
from neutrino_client.platforms.detect import detect_platform


def main() -> int:
    """Ask the running client to quit.

    Returns:
        Process exit status: 0 when it took the ask, 1 when nothing is
        running or it refused.
    """
    try:
        socket_path = detect_platform().control_socket_path()
    except PlatformUnsupportedError as error:
        print(wording.word_code(error.code), file=sys.stderr)
        return 1
    try:
        status, reply = client.request(
            socket_path=socket_path, method="POST", path="/api/quit"
        )
    except (OSError, ValueError):
        print(wording.NOT_RUNNING, file=sys.stderr)
        return 1
    if status != 200:
        print(
            wording.word_code(str(reply.get("code", "")), reply.get("params")),
            file=sys.stderr,
        )
        return 1
    print(wording.QUIT_ASKED)
    return 0
