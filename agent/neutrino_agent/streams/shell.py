"""A shell on this machine, behind a pseudo-terminal, over one stream.

The hub's bytes go to the shell's terminal; whatever the terminal produces
goes up as binary frames, no faster than the hub's credit allows; a resize,
which arrives as a command naming the stream, sets the terminal's window.
The stream closes with the shell's exit status in its params once the shell
exits. A stream opened with a ``session_id`` attaches to a shell the agent
keeps by that id, :mod:`neutrino_agent.streams.shell_session`, and a
persistent one keeps running when its stream closes. A ``shell`` opened with
``{module: podman, container}`` runs inside that container instead. On
Windows the shell is PowerShell on a pseudo console, served by
:class:`~neutrino_agent.streams.windows_shell.WindowsShellStream`.

The shell runs as the agent runs, which is root. Ending a shell kills its
whole terminal session, background jobs included, so a closed tab leaves
nothing behind.

Not pure: starts processes and owns file descriptors.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import os
import select
import signal
import struct
import subprocess
import sys
import threading

from neutrino_agent.constants import (
    AGENT_SHELL_COMMANDS,
    AGENT_SHELL_FALLBACKS,
    AGENT_SHELL_KILL_TIMEOUT_S,
    AGENT_SHELL_READ_BYTES,
    AGENT_SHELL_WINDOWS_ACCOUNT,
)
from neutrino_agent.exceptions import StreamRefused
from neutrino_agent.modules.podman.applier import PodmanStatusReader
from neutrino_agent.modules.podman.constants import PODMAN_BINARY
from neutrino_agent.streams.shell_session import SessionShellStream, ShellSession

try:
    import fcntl
    import pty
    import pwd
    import termios
except ImportError:  # Windows carries none of these.
    fcntl = pty = pwd = termios = None

# What a container shell runs: its own bash where it has one, else sh.
CONTAINER_SHELL_COMMAND = "command -v bash >/dev/null 2>&1 && exec bash || exec sh"
# The one module whose shells are served: a container's own.
CONTAINER_MODULE = "podman"

# How long a read waits on the terminal before looking again.
SELECT_TIMEOUT_S = 0.5
PROC_DIR = "/proc"


def login_home() -> str:
    """Where a shell here starts.

    Returns:
        The agent account's home directory, or ``/`` if it has none.
    """
    try:
        home = pwd.getpwuid(os.getuid()).pw_dir
    except (KeyError, AttributeError):
        home = ""
    return home if home and os.path.isdir(home) else "/"


def login_shell() -> str:
    """The shell to start.

    Returns:
        The agent account's own shell where it can run one, else the first
        usable fallback.
    """
    try:
        shell = pwd.getpwuid(os.getuid()).pw_shell
    except (KeyError, AttributeError):
        shell = ""
    if shell and os.access(shell, os.X_OK) and "nologin" not in shell:
        return shell
    for candidate in AGENT_SHELL_FALLBACKS:
        if os.access(candidate, os.X_OK):
            return candidate
    return AGENT_SHELL_FALLBACKS[-1]


def shell_command() -> list:
    """What a shell stream runs on this machine.

    Returns:
        The platform's own shell where it names one, else the login shell
        run interactively.
    """
    named = AGENT_SHELL_COMMANDS.get(sys.platform)
    if named is not None:
        return list(named)
    return [login_shell(), "-i"]


def shell_account() -> str:
    """The account a shell here runs as.

    Returns:
        The agent's own account's name; ``SYSTEM`` on Windows.
    """
    if sys.platform == "win32" or pwd is None:
        return AGENT_SHELL_WINDOWS_ACCOUNT
    try:
        return pwd.getpwuid(os.getuid()).pw_name
    except KeyError:
        return str(os.getuid())


def listed_containers() -> list:
    """The names of every container podman knows, running or not."""
    reader = PodmanStatusReader()
    return [state.name for state in reader.survey(declared_names=[])]


def open_shell_stream(channel, args: dict, *, sessions=None):
    """The handler for one ``shell`` stream: this machine's, or a container's.

    Args:
        channel: The stream's channel.
        args: ``{"cols", "rows"}``, with ``session_id`` and ``is_resumed``
            for a kept shell, or ``{"module", "container"}`` for a shell
            inside a container.
        sessions: The agent's shell registry; None keeps no shell past its
            stream.

    Returns:
        The handler, not yet opened.

    Raises:
        StreamRefused: ``verb_unknown`` naming a module other than the
            container engine's.
    """
    module = str(args.get("module", "") or "")
    if not module:
        if sys.platform == "win32":
            from neutrino_agent.streams.windows_shell import WindowsShellStream

            return WindowsShellStream(channel, args, sessions=sessions)
        return ShellStream(channel, args, sessions=sessions)
    if module != CONTAINER_MODULE:
        raise StreamRefused("verb_unknown", {"module": module})
    return ContainerShellStream(channel, args)


def shell_environment() -> dict:
    """The environment the shell starts with."""
    environment = dict(os.environ)
    environment["TERM"] = "xterm-256color"
    environment["HOME"] = login_home()
    environment.setdefault("LANG", "C.UTF-8")
    return environment


def _session_members(session_id: int) -> list:
    """Every pid in one terminal session, read from ``/proc``."""
    members = []
    try:
        entries = os.listdir(PROC_DIR)
    except OSError:
        return members
    for entry in entries:
        if not entry.isdigit():
            continue
        try:
            with open(os.path.join(PROC_DIR, entry, "stat"), encoding="utf-8") as f:
                stat = f.read()
            # The command name sits in parentheses and may hold spaces; the
            # fields after it start from the last ") ": state, ppid, pgrp,
            # session.
            fields = stat.rsplit(") ", 1)[1].split()
            if int(fields[3]) == session_id:
                members.append(int(entry))
        except (OSError, IndexError, ValueError):
            continue
    return members


def _sweep_session(session_id: int) -> None:
    """Kill every process still in a terminal session."""
    for pid in _session_members(session_id):
        if pid == os.getpid():
            continue
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGKILL)


class PtyTerminal:
    """One process on a pseudo-terminal, as a shell session drives it."""

    def __init__(self, command: list, *, cols: int, rows: int):
        """
        Args:
            command: What runs on the terminal.
            cols: The terminal's first width.
            rows: The terminal's first height.
        """
        self._command = list(command)
        self._columns = cols
        self._rows = rows
        self._master_fd: "int | None" = None
        self._process: "subprocess.Popen | None" = None
        self._is_terminating = threading.Event()

    def start(self) -> None:
        """Open the terminal and start the process on it.

        Raises:
            OSError: When the process cannot start.
        """
        master_fd, slave_fd = pty.openpty()
        self._master_fd = master_fd
        self.resize(self._columns, self._rows)
        try:
            self._process = subprocess.Popen(
                self._command,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                start_new_session=True,
                cwd=login_home(),
                env=shell_environment(),
            )
        except OSError:
            os.close(master_fd)
            self._master_fd = None
            raise
        finally:
            # The child holds the slave end now; a copy here would keep the
            # master from ever reading end-of-file.
            os.close(slave_fd)

    def read(self) -> bytes:
        """The terminal's next output.

        Returns:
            The bytes; empty once the process ended or is being ended.
        """
        while not self._is_terminating.is_set():
            readable, _, _ = select.select([self._master_fd], [], [], SELECT_TIMEOUT_S)
            if not readable:
                if self._process.poll() is not None:
                    return b""
                continue
            try:
                return os.read(self._master_fd, AGENT_SHELL_READ_BYTES)
            except OSError:
                # The shell exited and took the terminal with it.
                return b""
        return b""

    def write(self, data: bytes) -> None:
        """Type into the terminal.

        Args:
            data: The bytes.
        """
        view = memoryview(data)
        while view and self._master_fd is not None:
            try:
                written = os.write(self._master_fd, view)
            except OSError:
                return
            view = view[written:]

    def resize(self, cols: int, rows: int) -> None:
        """Set the terminal's window.

        Args:
            cols: The width.
            rows: The height.
        """
        self._columns = max(1, int(cols))
        self._rows = max(1, int(rows))
        if self._master_fd is None:
            return
        size = struct.pack("HHHH", self._rows, self._columns, 0, 0)
        with contextlib.suppress(OSError):
            fcntl.ioctl(self._master_fd, termios.TIOCSWINSZ, size)

    def terminate(self) -> None:
        """Hang up on the process group; the read that waits returns."""
        self._is_terminating.set()
        self._signal_group(signal.SIGHUP)

    def finish(self) -> int:
        """Stop the process and everything it started, release the terminal.

        Returns:
            The process's exit status; a signal death reads as 128 plus it.
        """
        process = self._process
        exit_code = 1
        if process is not None:
            if process.poll() is None:
                for sig in (signal.SIGHUP, signal.SIGKILL):
                    self._signal_group(sig)
                    try:
                        process.wait(timeout=AGENT_SHELL_KILL_TIMEOUT_S)
                        break
                    except subprocess.TimeoutExpired:
                        continue
            _sweep_session(process.pid)
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=AGENT_SHELL_KILL_TIMEOUT_S)
            if process.returncode is not None:
                code = process.returncode
                exit_code = code if code >= 0 else 128 - code
        if self._master_fd is not None:
            with contextlib.suppress(OSError):
                os.close(self._master_fd)
            self._master_fd = None
        return exit_code

    def _signal_group(self, sig: int) -> None:
        if self._process is None:
            return
        with contextlib.suppress(OSError):
            os.killpg(self._process.pid, sig)


class ShellStream(SessionShellStream):
    """A shell on a pseudo-terminal, kept by id when the open names one."""

    def __init__(
        self, channel, args: dict, *, command: "list | None" = None, sessions=None
    ):
        """
        Args:
            channel: The stream's channel.
            args: ``{"cols", "rows"}``, the terminal's first size, with
                ``session_id`` and ``is_resumed`` for a kept shell.
            command: What to run on the terminal. None is the platform's
                shell.
            sessions: The agent's shell registry; None keeps no shell past
                its stream.
        """
        super().__init__(channel, args, sessions=sessions)
        self._command = list(command) if command else None

    def _check_platform(self) -> None:
        """Refuse a platform with no pseudo-terminals."""
        if pty is None:
            raise StreamRefused("unsupported_platform")

    def _make_session(self, *, on_change=None, on_end=None) -> ShellSession:
        command = self._command or shell_command()
        return ShellSession(
            session_id=self._session_id,
            terminal=PtyTerminal(command, cols=self._columns, rows=self._rows),
            account=shell_account(),
            title=os.path.basename(command[0]),
            on_change=on_change,
            on_end=on_end,
        )


class ContainerShellStream(ShellStream):
    """A shell inside one podman container, on the same terminal.

    It ends with its stream: a container's shell is never kept.
    """

    def __init__(self, channel, args: dict):
        """
        Args:
            channel: The stream's channel.
            args: ``{"container", "cols", "rows"}``, the container and the
                terminal's first size.
        """
        self._name = str(args.get("container", ""))
        super().__init__(
            channel,
            args,
            command=[
                PODMAN_BINARY,
                "exec",
                "-it",
                self._name,
                "sh",
                "-c",
                CONTAINER_SHELL_COMMAND,
            ],
        )

    def open(self) -> None:
        """Check the container is one podman lists.

        Raises:
            StreamRefused: ``container_unknown`` when it is not, or on a
                platform with no pseudo-terminals.
        """
        super().open()
        if not self._name or self._name not in listed_containers():
            raise StreamRefused("container_unknown", {"name": self._name})
