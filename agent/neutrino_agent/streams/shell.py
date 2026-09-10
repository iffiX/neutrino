"""A shell on this machine, behind a pseudo-terminal, over one stream.

The hub's bytes go to the shell's terminal; whatever the terminal produces
goes up as binary frames, no faster than the hub's credit allows; a resize
sets the terminal's window. The stream ends when the shell exits or the
hub closes it, and closes with the shell's exit status.

The shell runs as the agent runs, which is root. Closing the stream kills
the shell's whole terminal session, background jobs included, so a closed
tab leaves nothing behind.

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
import threading

from neutrino_agent.constants import (
    AGENT_SHELL_FALLBACKS,
    AGENT_SHELL_KILL_TIMEOUT_S,
    AGENT_SHELL_READ_BYTES,
    AGENT_WS_STREAM_CREDIT_BYTES,
)
from neutrino_agent.exceptions import StreamClosed, StreamRefused
from neutrino_agent.modules.podman.applier import PodmanStatusReader
from neutrino_agent.modules.podman.constants import PODMAN_BINARY

try:
    import fcntl
    import pty
    import pwd
    import termios
except ImportError:  # Windows carries none of these.
    fcntl = pty = pwd = termios = None

# What a container shell runs: its own bash where it has one, else sh.
CONTAINER_SHELL_COMMAND = "command -v bash >/dev/null 2>&1 && exec bash || exec sh"

DEFAULT_COLUMNS = 80
DEFAULT_ROWS = 24
# How long the output loop waits on the terminal before looking again.
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


def listed_containers() -> list:
    """The names of every container podman knows, running or not."""
    reader = PodmanStatusReader()
    return [state.name for state in reader.survey(declared_names=[])]


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


class ShellStream:
    """One shell process on a pseudo-terminal, served over one stream."""

    def __init__(self, channel, args: dict, *, command: "list | None" = None):
        """
        Args:
            channel: The stream's channel.
            args: ``{"cols", "rows"}``, the terminal's first size.
            command: What to run on the terminal. None is this account's
                login shell.
        """
        self._channel = channel
        self._columns = max(1, int(args.get("cols", DEFAULT_COLUMNS) or 0))
        self._rows = max(1, int(args.get("rows", DEFAULT_ROWS) or 0))
        self._command = list(command) if command else None
        self._master_fd: "int | None" = None
        self._process: "subprocess.Popen | None" = None
        self._is_done = threading.Event()

    def open(self) -> None:
        """Check the stream can be served here.

        Raises:
            StreamRefused: On a platform with no pseudo-terminals.
        """
        if pty is None:
            raise StreamRefused("unsupported_platform")

    def run(self) -> dict:
        """Serve the shell until it exits or the hub closes the stream.

        Returns:
            ``{"exit_code", "code", "params"}``.
        """
        master_fd, slave_fd = pty.openpty()
        self._master_fd = master_fd
        self._apply_size()
        try:
            self._process = subprocess.Popen(
                self._command or [login_shell(), "-i"],
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                start_new_session=True,
                cwd=login_home(),
                env=shell_environment(),
            )
        except OSError as error:
            os.close(master_fd)
            self._master_fd = None
            return {
                "exit_code": 1,
                "code": "shell_failed",
                "params": {"detail": str(error)[:200]},
            }
        finally:
            # The child holds the slave end now; a copy here would keep the
            # master from ever reading end-of-file.
            os.close(slave_fd)
        self._channel.offer_credit(AGENT_WS_STREAM_CREDIT_BYTES)
        feeder = threading.Thread(
            target=self._feed_input, name=f"agent_shell_input_{self._channel.id}"
        )
        feeder.start()
        try:
            self._pump_output()
        finally:
            self._is_done.set()
            exit_code = self._close()
            feeder.join(timeout=AGENT_SHELL_KILL_TIMEOUT_S)
        return {"exit_code": exit_code, "code": "", "params": {}}

    def _pump_output(self) -> None:
        """Send the terminal's output until it ends or the hub is gone."""
        while not self._is_done.is_set():
            readable, _, _ = select.select([self._master_fd], [], [], SELECT_TIMEOUT_S)
            if not readable:
                if self._process.poll() is not None:
                    return
                continue
            try:
                chunk = os.read(self._master_fd, AGENT_SHELL_READ_BYTES)
            except OSError:
                # The shell exited and took the terminal with it.
                return
            if not chunk:
                return
            try:
                self._channel.send_bytes(chunk)
            except StreamClosed:
                return

    def _feed_input(self) -> None:
        """Write the hub's bytes to the terminal and apply its resizes."""
        while not self._is_done.is_set():
            item = self._channel.recv(timeout=SELECT_TIMEOUT_S)
            if item is None:
                continue
            if item[0] == "data":
                self._write(item[1])
                self._channel.offer_credit(len(item[1]))
            elif item[0] == "resize":
                self._columns = max(1, int(item[1]))
                self._rows = max(1, int(item[2]))
                self._apply_size()
            elif item[0] == "close":
                self._is_done.set()
                self._signal_group(signal.SIGHUP)
                return

    def _write(self, data: bytes) -> None:
        view = memoryview(data)
        while view and self._master_fd is not None:
            try:
                written = os.write(self._master_fd, view)
            except OSError:
                return
            view = view[written:]

    def _apply_size(self) -> None:
        if self._master_fd is None:
            return
        size = struct.pack("HHHH", self._rows, self._columns, 0, 0)
        with contextlib.suppress(OSError):
            fcntl.ioctl(self._master_fd, termios.TIOCSWINSZ, size)

    def _signal_group(self, sig: int) -> None:
        if self._process is None:
            return
        with contextlib.suppress(OSError):
            os.killpg(self._process.pid, sig)

    def _close(self) -> int:
        """Stop the shell and everything it started, release the terminal.

        Returns:
            The shell's exit status; a signal death reads as 128 plus it.
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


class ContainerShellStream(ShellStream):
    """A shell inside one podman container, on the same terminal."""

    def __init__(self, channel, args: dict):
        """
        Args:
            channel: The stream's channel.
            args: ``{"name"}``, the container.
        """
        self._name = str(args.get("name", ""))
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
