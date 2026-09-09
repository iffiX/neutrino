"""``nclient gui``: the resident, and its window.

One process is the whole client: it binds this person's control socket,
polls the hub, keeps the service handlers, and shows the window on the main
thread. A second invocation finds the socket held, asks the running one to
show its window, and exits.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import sys

from neutrino_client.cli import wording
from neutrino_client.constants import CLIENT_GUI_WINDOW_TITLE
from neutrino_client.control import client
from neutrino_client.control.page import control_page_html, window_icon_path
from neutrino_client.control.server import ControlServer
from neutrino_client.core.session import ClientSession
from neutrino_client.gui.bridge import GuiBridge
from neutrino_client.gui.channel import InProcessChannel
from neutrino_client.gui.shell import GuiShellUnavailableError, open_shell_window
from neutrino_client.platforms.base import PlatformUnsupportedError
from neutrino_client.platforms.detect import detect_platform


def main(*, is_hidden: bool = False) -> int:
    """Run the resident, or hand the ask to the one already running.

    Args:
        is_hidden: Accepted for the launcher's autostart entry; the window
            opens either way until the tray lands.

    Returns:
        Process exit status.
    """
    try:
        platform = detect_platform()
        socket_path = platform.control_socket_path()
    except PlatformUnsupportedError as error:
        print(wording.word_code(error.code), file=sys.stderr)
        return 1
    session = ClientSession(platform=platform, log=_log)
    server = ControlServer(
        session=session, platform=platform, log=_log, socket_path=socket_path
    )
    if not server.bind():
        return _show_running(socket_path)
    session.start()
    server.start()
    try:
        return _open(platform.os_name, session)
    finally:
        session.shutdown()
        server.stop()


def _log(message: str) -> None:
    """The resident's own lines go to stderr; stdout stays empty."""
    print(message, file=sys.stderr)


def _show_running(socket_path: str) -> int:
    """Ask the resident already holding the socket to show its window.

    Args:
        socket_path: The socket it holds.

    Returns:
        0 when it answered, 1 when nothing did.
    """
    try:
        status, _state = client.request(
            socket_path=socket_path, method="GET", path="/api/state", timeout_s=2
        )
        if status == 200:
            client.request(socket_path=socket_path, method="POST", path="/api/show")
            return 0
    except (OSError, ValueError):
        pass
    print(wording.word_code("control_socket_unavailable"), file=sys.stderr)
    return 1


def _open(os_name: str, session) -> int:
    """Open the platform's shell over the in-process channel.

    Args:
        os_name: The platform's ``os_name``.
        session: The running session.

    Returns:
        Process exit status.
    """
    try:
        open_shell_window(
            os_name=os_name,
            title=CLIENT_GUI_WINDOW_TITLE,
            html=control_page_html(),
            bridge=GuiBridge(channel=InProcessChannel(session=session)),
            icon_path=window_icon_path(),
        )
    except GuiShellUnavailableError as error:
        print(wording.word_code(error.code, error.params), file=sys.stderr)
        return 1
    return 0
