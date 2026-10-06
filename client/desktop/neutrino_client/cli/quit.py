"""``nclient quit``: stop the running client.

The client's services exist only while it runs, so quitting is what puts
this machine back: the tools restored, the shares unmounted, the forwards
and the viewers closed. The running resident does that itself; this asks it
to, over the control socket, as whoever ran the command. With no client of
this account running, it asks the client of the account that holds the
machine, which takes the ask from an elevated caller, as an installer is.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import sys

from neutrino_client.cli import wording
from neutrino_client.control import client
from neutrino_client.exceptions import PlatformUnsupportedError
from neutrino_client.platforms.detect import detect_platform


def main(*, is_upgrade: bool = False) -> int:
    """Ask the running client to quit.

    Args:
        is_upgrade: Whether an installer asks, which has the client started
            again once the install ends.

    Returns:
        Process exit status: 0 when it took the ask, 1 when nothing is
        running or it refused.
    """
    try:
        platform = detect_platform()
        socket_path = platform.control_socket_path()
    except PlatformUnsupportedError as error:
        print(wording.word_code(error.code), file=sys.stderr)
        return 1
    body = {"is_upgrade": True} if is_upgrade else None
    try:
        status, reply = _ask_quit(socket_path, body)
    except (OSError, ValueError):
        holder = wording.other_holder()
        if not holder:
            print(wording.NOT_RUNNING, file=sys.stderr)
            return 1
        try:
            status, reply = _ask_quit(platform.control_socket_path_of(holder), body)
        except (OSError, ValueError, PlatformUnsupportedError):
            print(
                wording.word_code("client_held", {"account": holder}),
                file=sys.stderr,
            )
            return 1
    if status != 200:
        print(
            wording.word_code(str(reply.get("code", "")), reply.get("params")),
            file=sys.stderr,
        )
        return 1
    print(wording.QUIT_ASKED)
    return 0


def _ask_quit(socket_path: str, body: "dict | None") -> "tuple[int, dict]":
    """One quit asked of the resident on one socket or pipe.

    Raises:
        OSError: When nothing answers there.
        ValueError: When the answer is not JSON.
    """
    return client.request(
        socket_path=socket_path, method="POST", path="/api/quit", body=body
    )
