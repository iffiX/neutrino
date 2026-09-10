"""``nclient gui``: the resident, its tray icon, and its window.

One process is the whole client: it binds this person's control socket,
holds the socket to the hub, keeps the service handlers, and runs the window
on the main thread. Closing the window hides it; the tray's Quit is what
stops the resident. A second invocation finds the socket held, asks the
running one to show its window, and exits.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import datetime
import os
import sys
import threading

from neutrino_client.cli import wording
from neutrino_client.constants import (
    CLIENT_GUI_WINDOW_TITLE,
    CLIENT_LOG_FILE_NAME,
    CLIENT_LOG_KEEP_BYTES,
)
from neutrino_client.control import client, routes
from neutrino_client.control.page import control_page_html, window_icon_path
from neutrino_client.control.server import ControlServer
from neutrino_client.core.session import ClientSession
from neutrino_client.gui.bridge import GuiBridge
from neutrino_client.gui.channel import InProcessChannel
from neutrino_client.exceptions import (
    GuiShellUnavailableError,
    PlatformUnsupportedError,
)
from neutrino_client.gui.shell import open_shell_window
from neutrino_client.platforms.detect import detect_platform


def main(*, is_hidden: bool = False) -> int:
    """Run the resident, or hand the ask to the one already running.

    Args:
        is_hidden: Whether to start in the tray with no window shown.

    Returns:
        Process exit status.
    """
    try:
        platform = detect_platform()
        socket_path = platform.control_socket_path()
    except PlatformUnsupportedError as error:
        print(wording.word_code(error.code), file=sys.stderr)
        return 1
    log = ResidentLog(path=os.path.join(platform.config_dir(), CLIENT_LOG_FILE_NAME))
    session = ClientSession(platform=platform, log=log)
    server = ControlServer(
        session=session, platform=platform, log=log, socket_path=socket_path
    )
    if not server.bind():
        return _show_running(socket_path)
    session.start()
    server.start()
    try:
        status = _open(platform.os_name, session, is_hidden=is_hidden)
    finally:
        session.shutdown()
        server.stop()
    return _end(status)


def _end(status: int) -> int:
    """End the process, whatever the window's runtime left running.

    The shutdown above is what restores the machine, and it has already run
    by the time this is called. What can still be standing is the window
    runtime's own: on Windows the embedded browser's helper processes and
    the threads .NET holds, none of which answer to this interpreter. A
    resident that lingers there holds this person's socket and hands the
    next install a file it cannot replace.

    Args:
        status: What the window's own run came to.

    Returns:
        The status, on a platform where the plain return is enough.
    """
    if os.name != "nt":
        return status
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(status)


class ResidentLog:
    """The resident's lines: to stderr where there is one, and to a file.

    The file is kept to ``CLIENT_LOG_KEEP_BYTES``; past that it is moved
    aside as ``.1`` and a new one started.
    """

    def __init__(self, *, path: str):
        """
        Args:
            path: The log file.
        """
        self._path = path
        self._lock = threading.Lock()

    def __call__(self, message: str) -> None:
        line = f"{datetime.datetime.now().isoformat(timespec='seconds')} {message}"
        print(message, file=sys.stderr)
        with self._lock:
            try:
                os.makedirs(os.path.dirname(self._path), exist_ok=True)
                self._turn()
                with open(self._path, "a", encoding="utf-8") as stream:
                    stream.write(line + "\n")
            except OSError:
                pass

    def _turn(self) -> None:
        try:
            if os.path.getsize(self._path) < CLIENT_LOG_KEEP_BYTES:
                return
        except OSError:
            return
        os.replace(self._path, self._path + ".1")


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


def _open(os_name: str, session, *, is_hidden: bool) -> int:
    """Open the platform's shell over the in-process channel.

    Args:
        os_name: The platform's ``os_name``.
        session: The running session.
        is_hidden: Whether to start in the tray with no window shown.

    Returns:
        Process exit status.
    """

    def register_show(show) -> None:
        session.on_show = show

    def register_push(push) -> None:
        session.subscribe(lambda: push(routes.state_payload(session)))

    try:
        open_shell_window(
            os_name=os_name,
            title=CLIENT_GUI_WINDOW_TITLE,
            html=control_page_html(),
            bridge=GuiBridge(channel=InProcessChannel(session=session)),
            icon_path=window_icon_path(),
            is_hidden=is_hidden,
            on_quit=session.shutdown,
            on_show_ready=register_show,
            on_push_ready=register_push,
        )
    except GuiShellUnavailableError as error:
        print(wording.word_code(error.code, error.params), file=sys.stderr)
        return 1
    return 0
