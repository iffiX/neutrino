"""``nagent gui``: open this machine's window as whoever ran it.

The command connects to the running agent's control socket — the kernel
reads who opened that connection, and that identity is the window's whole
scope — then hands the connected descriptor to a window process running as
the desktop user: ``SUDO_USER`` when invoked under sudo, the invoker
otherwise. No privileged GUI process exists, nothing is printed for a
person to copy, and no browser is launched for the agent's own page.

On Windows the elevated invocation hosts the window itself and opens the
control pipe per request; the kernel reads the same identity on each one.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
import socket
import subprocess
import sys

from neutrino_agent.cli import wording
from neutrino_agent.constants import (
    AGENT_CONTROL_PIPE_PREFIX,
    AGENT_GUI_WINDOW_TITLE,
    AGENT_SERVICE_NAME,
)
from neutrino_agent.control.page import control_page_html, window_icon_path
from neutrino_agent.gui.bridge import GuiBridge
from neutrino_agent.gui.channel import GuiFdChannel, GuiPipeChannel
from neutrino_agent.gui.shell import GuiShellUnavailableError, open_shell_window
from neutrino_agent.platforms.base import PlatformUnsupportedError
from neutrino_agent.platforms.detect import detect_platform

GUI_NOT_RUNNING = (
    "the agent is not running, so there is nothing to open; start it: "
    f"sudo systemctl enable --now {AGENT_SERVICE_NAME}"
)


def main(*, window_fd: "int | None" = None) -> int:
    """Open the window, or serve as the handed-over window process.

    Args:
        window_fd: The inherited control connection's descriptor when this
            process is the window half of the handover; None to invoke.

    Returns:
        Process exit status.
    """
    try:
        platform = detect_platform()
        socket_path = platform.control_socket_path()
    except PlatformUnsupportedError:
        print(wording.NO_CONTROL_SOCKET, file=sys.stderr)
        return 1
    if window_fd is not None:
        return _window(platform.os_name, window_fd)
    if socket_path.startswith(AGENT_CONTROL_PIPE_PREFIX):
        return _host_here(platform.os_name, socket_path)
    return _hand_over(socket_path)


def _hand_over(socket_path: str) -> int:
    """Connect as the invoker and hand the connection to the window process.

    Args:
        socket_path: The agent's control socket.

    Returns:
        The window process's exit status.
    """
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        connection.connect(socket_path)
    except OSError:
        connection.close()
        print(GUI_NOT_RUNNING, file=sys.stderr)
        return 1
    command = [
        sys.executable,
        "-m",
        "neutrino_agent.cli.entry",
        "gui",
        "--window-fd",
        str(connection.fileno()),
    ]
    window = subprocess.Popen(
        command, pass_fds=(connection.fileno(),), **window_process_keywords()
    )
    connection.close()
    try:
        return window.wait()
    except KeyboardInterrupt:
        window.terminate()
        return 0


def _host_here(os_name: str, pipe_name: str) -> int:
    """Host the window in this process, on the per-request pipe channel.

    Args:
        os_name: The platform's ``os_name``.
        pipe_name: The agent's control pipe.

    Returns:
        Process exit status.
    """
    channel = GuiPipeChannel(pipe_name=pipe_name)
    try:
        channel.request(method="GET", path="/api/state")
    except (OSError, ValueError):
        print(GUI_NOT_RUNNING, file=sys.stderr)
        return 1
    return _open(os_name, channel)


def _window(os_name: str, window_fd: int) -> int:
    """The window process: speak the inherited connection, show the page.

    Args:
        os_name: The platform's ``os_name``.
        window_fd: The inherited control connection's descriptor.

    Returns:
        Process exit status.
    """
    channel = GuiFdChannel(sock=socket.socket(fileno=window_fd))
    return _open(os_name, channel)


def _open(os_name: str, channel) -> int:
    """Open the platform's shell over one channel.

    Args:
        os_name: The platform's ``os_name``.
        channel: The window's control connection.

    Returns:
        Process exit status.
    """
    try:
        open_shell_window(
            os_name=os_name,
            title=AGENT_GUI_WINDOW_TITLE,
            html=control_page_html(),
            bridge=GuiBridge(channel=channel),
            icon_path=window_icon_path(),
        )
    except GuiShellUnavailableError as error:
        print(wording.word_code(error.code, error.params), file=sys.stderr)
        return 1
    return 0


def window_process_keywords() -> dict:
    """The Popen keywords that run the window as the desktop user.

    Under sudo the window steps down to ``SUDO_USER`` — uid, gid, the
    account's groups, and a home of its own; anything else runs the window
    as the invoker unchanged.

    Returns:
        Keyword arguments for ``subprocess.Popen``.
    """
    sudo_user = os.environ.get("SUDO_USER", "")
    if os.geteuid() != 0 or not sudo_user or sudo_user == "root":
        return {}
    import pwd

    entry = pwd.getpwnam(sudo_user)
    env = dict(os.environ)
    env["HOME"] = entry.pw_dir
    env["USER"] = entry.pw_name
    env["LOGNAME"] = entry.pw_name
    runtime_dir = f"/run/user/{entry.pw_uid}"
    if os.path.isdir(runtime_dir):
        env["XDG_RUNTIME_DIR"] = runtime_dir
    else:
        env.pop("XDG_RUNTIME_DIR", None)
    return {
        "user": entry.pw_uid,
        "group": entry.pw_gid,
        "extra_groups": os.getgrouplist(entry.pw_name, entry.pw_gid),
        "env": env,
    }
