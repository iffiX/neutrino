"""A shell on this machine, behind a pseudo-terminal, over one stream.

The hub's bytes go to the shell's terminal; whatever the terminal produces
goes up as binary frames, no faster than the hub's credit allows; a resize,
which arrives as a command naming the stream, sets the stream's window.
The stream closes with the shell's exit status in its params once the shell
exits. A stream opened with a ``session_id`` attaches to a shell the agent
keeps by that id, :mod:`neutrino_agent.streams.shell_session`, beside any
other stream attached to it, and the terminal takes the smallest window
of them. A ``shell`` opened with
``{module: podman, container}`` runs inside that container instead. On
Windows the shell is PowerShell on a pseudo console, served by
:class:`~neutrino_agent.streams.windows_shell.WindowsShellStream`.

A new shell runs as the Terminal module says: as the agent runs, which is
root, with the shell picked here while its settings are empty; as the
account it names, through the platform's step-down, in that account's home
with its environment; with the shell program it names. A named account the
machine does not have, or a shell program that cannot be run, refuses the
open with no fallback. A shell already running keeps what it runs, and a
container's shell reads none of it. Ending a shell kills its whole terminal
session, background jobs included, so a closed tab leaves nothing behind.

An ``exec`` stream opened with ``is_tty`` runs its ``argv`` here in place
of the shell, as the same account, never kept, every frame down headed
with stdout's ``fd``; :mod:`neutrino_agent.streams.exec` serves the rest.

Not pure: starts processes and owns file descriptors.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import os
import select
import shutil
import signal
import struct
import subprocess
import sys
import threading

from neutrino_agent.constants import (
    AGENT_EXEC_FD_STDOUT,
    AGENT_SHELL_COMMANDS,
    AGENT_SHELL_FALLBACKS,
    AGENT_SHELL_KILL_TIMEOUT_S,
    AGENT_SHELL_READ_BYTES,
    AGENT_SHELL_WINDOWS_ACCOUNT,
)
from neutrino_agent.exceptions import (
    ModuleApplyError,
    PlatformUnsupportedError,
    StreamRefused,
)
from neutrino_agent.modules.podman.applier import PodmanStatusReader
from neutrino_agent.modules.podman.constants import PODMAN_BINARY
from neutrino_agent.modules.terminal.config import (
    TerminalConfig,
    account_entry,
    check_shell_program,
)
from neutrino_agent.modules.terminal.constants import (
    TERMINAL_CODE_ACCOUNT_UNKNOWN,
    TERMINAL_CODE_SHELL_UNUSABLE,
    TERMINAL_LOGIN_ARGUMENTS,
    TERMINAL_NOLOGIN_MARK,
)
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


def login_shell(shell: str = "") -> str:
    """The shell to start.

    Args:
        shell: An account's own login shell; empty reads the agent's.

    Returns:
        That shell where it can run one, else the first usable fallback.
    """
    if not shell:
        try:
            shell = pwd.getpwuid(os.getuid()).pw_shell
        except (KeyError, AttributeError):
            shell = ""
    if shell and os.access(shell, os.X_OK) and TERMINAL_NOLOGIN_MARK not in shell:
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


def open_shell_stream(
    channel, args: dict, *, sessions=None, terminal=None, platform=None
):
    """The handler for one ``shell`` stream: this machine's, or a container's.

    Args:
        channel: The stream's channel.
        args: ``{"cols", "rows"}``, with ``session_id`` and ``is_resumed``
            for a kept shell, or ``{"module", "container"}`` for a shell
            inside a container.
        sessions: The agent's shell registry; None keeps no shell past its
            stream.
        terminal: Returns the Terminal module's
            :class:`~neutrino_agent.modules.terminal.config.TerminalConfig`
            a new shell runs with; None runs every shell as the agent.
        platform: The machine's platform, which steps down to an account.

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

            return WindowsShellStream(
                channel, args, sessions=sessions, terminal=terminal, platform=platform
            )
        return ShellStream(
            channel, args, sessions=sessions, terminal=terminal, platform=platform
        )
    if module != CONTAINER_MODULE:
        raise StreamRefused("verb_unknown", {"module": module})
    return ContainerShellStream(channel, args)


def shell_environment(base: "dict | None" = None) -> dict:
    """The environment the shell starts with.

    Args:
        base: An account's environment as the platform steps down to it;
            None is the agent's own, with its home.
    """
    if base is None:
        environment = dict(os.environ)
        environment["HOME"] = login_home()
    else:
        environment = dict(base)
    environment["TERM"] = "xterm-256color"
    environment.setdefault("LANG", "C.UTF-8")
    return environment


def refusal(error: ModuleApplyError) -> StreamRefused:
    """A Terminal module refusal as the stream's."""
    return StreamRefused(error.code, dict(error.params))


def shell_plan(settings: TerminalConfig, platform) -> tuple:
    """What a new shell runs, as whom, and how it starts, by the Terminal module's settings.

    Args:
        settings: The module's settings.
        platform: The machine's platform, which steps down to an account.

    Returns:
        ``(command, process, account, title)``: the argument vector, what
        :class:`subprocess.Popen` takes beside it (``cwd``, ``env``, and
        ``owner``, the uid the terminal is handed to; empty for the agent's
        own), the account the shell runs as, and the shell's name.

    Raises:
        StreamRefused: ``account_unknown {account}`` for an account the
            machine does not have, ``shell_program_unusable {path}`` for a
            shell program that cannot be run.
    """
    try:
        if settings.shell_path:
            check_shell_program(settings.shell_path)
        if not settings.account:
            if settings.shell_path:
                command = [settings.shell_path, *TERMINAL_LOGIN_ARGUMENTS]
            else:
                command = shell_command()
            return command, {}, shell_account(), os.path.basename(command[0])
        entry = account_entry(settings.account)
    except ModuleApplyError as error:
        raise refusal(error) from None
    shell = settings.shell_path or login_shell(entry.pw_shell)
    try:
        if platform is None:
            raise PlatformUnsupportedError("no platform to step down with")
        command, process = platform.account_process(
            settings.account, [shell, *TERMINAL_LOGIN_ARGUMENTS]
        )
    except KeyError:
        raise StreamRefused(
            TERMINAL_CODE_ACCOUNT_UNKNOWN, {"account": settings.account}
        ) from None
    except PlatformUnsupportedError:
        raise StreamRefused("unsupported_platform") from None
    process = dict(process)
    process["env"] = dict(process.get("env") or os.environ)
    process["env"]["SHELL"] = shell
    process["owner"] = entry.pw_uid
    return command, process, settings.account, os.path.basename(shell)


def check_exec_argv(argv, environment: "dict | None" = None) -> None:
    """Refuse an ``exec`` stream's ``argv`` that cannot run.

    Args:
        argv: The open's ``argv``.
        environment: The environment the process gets, whose ``PATH`` the
            program is looked up on; None is the agent's own.

    Raises:
        StreamRefused: ``shell_program_unusable {path}``: ``path`` empty for
            an ``argv`` that is empty or not a list of strings, else its
            first member when that is not found on the ``PATH`` or cannot
            be run.
    """
    if (
        not isinstance(argv, list)
        or not argv
        or not all(isinstance(each, str) for each in argv)
        or not argv[0]
    ):
        raise StreamRefused(TERMINAL_CODE_SHELL_UNUSABLE, {"path": ""})
    path = (environment if environment is not None else os.environ).get(
        "PATH", os.defpath
    )
    if shutil.which(argv[0], path=path) is None:
        raise StreamRefused(TERMINAL_CODE_SHELL_UNUSABLE, {"path": argv[0]})


def exec_plan(argv, settings: TerminalConfig, platform) -> tuple:
    """What an ``exec`` stream runs here, and as whom, by the Terminal module's settings.

    Args:
        argv: The open's ``argv``, run as given with no shell between.
        settings: The module's settings; its shell program is not read.
        platform: The machine's platform, which steps down to an account.

    Returns:
        ``(command, process, account)``: the argument vector, what
        :class:`subprocess.Popen` takes beside it (``cwd``, ``env``, and
        ``owner``, the uid a terminal is handed to; empty for the agent's
        own), and the account the command runs as.

    Raises:
        StreamRefused: ``account_unknown {account}`` for an account the
            machine does not have; ``shell_program_unusable {path}`` for an
            ``argv`` :func:`check_exec_argv` refuses.
    """
    if not settings.account:
        check_exec_argv(argv)
        return list(argv), {}, shell_account()
    try:
        entry = account_entry(settings.account)
    except ModuleApplyError as error:
        raise refusal(error) from None
    try:
        if platform is None:
            raise PlatformUnsupportedError("no platform to step down with")
        command, process = platform.account_process(
            settings.account, list(argv) if isinstance(argv, list) else []
        )
    except KeyError:
        raise StreamRefused(
            TERMINAL_CODE_ACCOUNT_UNKNOWN, {"account": settings.account}
        ) from None
    except PlatformUnsupportedError:
        raise StreamRefused("unsupported_platform") from None
    process = dict(process)
    process["env"] = dict(process.get("env") or os.environ)
    process["env"]["SHELL"] = login_shell(entry.pw_shell)
    process["owner"] = entry.pw_uid
    check_exec_argv(argv, process["env"])
    return command, process, settings.account


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


def end_session(process: subprocess.Popen) -> int:
    """Stop a process that leads its own session, and everything in that session.

    Args:
        process: The process, started with ``start_new_session``.

    Returns:
        Its exit status; a signal death reads as 128 plus the signal's
        number, and one that never ended as 1.
    """
    if process.poll() is None:
        for sig in (signal.SIGHUP, signal.SIGKILL):
            with contextlib.suppress(OSError):
                os.killpg(process.pid, sig)
            try:
                process.wait(timeout=AGENT_SHELL_KILL_TIMEOUT_S)
                break
            except subprocess.TimeoutExpired:
                continue
    _sweep_session(process.pid)
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(timeout=AGENT_SHELL_KILL_TIMEOUT_S)
    code = process.returncode
    if code is None:
        return 1
    return code if code >= 0 else 128 - code


def _take_controlling_terminal() -> None:
    """Make the shell's own terminal its controlling terminal.

    Runs in the child between ``setsid`` and ``exec``. Without it the shell
    has no controlling terminal, so the kernel has no process group to send
    ``SIGWINCH`` to when the hub resizes the terminal, and the shell keeps
    the width it started with.
    """
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)


class PtyTerminal:
    """One process on a pseudo-terminal, as a shell session drives it."""

    def __init__(
        self, command: list, *, cols: int, rows: int, process: "dict | None" = None
    ):
        """
        Args:
            command: What runs on the terminal.
            cols: The terminal's first width.
            rows: The terminal's first height.
            process: What :class:`subprocess.Popen` takes beside the
                command for a shell that runs as an account: ``cwd``,
                ``env``, the identity, and ``owner``, the uid the terminal
                is handed to. None starts it as the agent, in its home.
        """
        self._command = list(command)
        self._process_arguments = dict(process or {})
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
        arguments = dict(self._process_arguments)
        owner = arguments.pop("owner", None)
        base = arguments.pop("env", None)
        cwd = arguments.pop("cwd", "") or login_home()
        if not os.path.isdir(cwd):
            cwd = "/"
        try:
            if owner is not None:
                os.fchown(slave_fd, int(owner), -1)
            self._process = subprocess.Popen(
                self._command,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                start_new_session=True,
                preexec_fn=_take_controlling_terminal,
                cwd=cwd,
                env=shell_environment(base),
                **arguments,
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
        exit_code = 1
        if self._process is not None:
            exit_code = end_session(self._process)
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
        self,
        channel,
        args: dict,
        *,
        command: "list | None" = None,
        argv: "list | None" = None,
        sessions=None,
        terminal=None,
        platform=None,
    ):
        """
        Args:
            channel: The stream's channel.
            args: ``{"cols", "rows"}``, the terminal's first size, with
                ``session_id`` and ``is_resumed`` for a kept shell.
            command: What to run on the terminal, as the agent and with no
                Terminal module settings read. None is the shell the
                settings say.
            argv: An ``exec`` stream's command, run in place of the shell
                as the settings' account, its output headed with stdout's
                ``fd``. None is a shell.
            sessions: The agent's shell registry; None keeps no shell past
                its stream.
            terminal: Returns the Terminal module's settings; None is the
                defaults.
            platform: The machine's platform, which steps down to an
                account.
        """
        super().__init__(
            channel,
            args,
            sessions=sessions,
            frame_head=bytes([AGENT_EXEC_FD_STDOUT]) if argv is not None else b"",
        )
        self._command = list(command) if command else None
        self._argv = argv
        self._terminal = terminal
        self._platform = platform

    def _check_platform(self) -> None:
        """Refuse a platform with no pseudo-terminals."""
        if pty is None:
            raise StreamRefused("unsupported_platform")

    def _make_session(self, *, on_change=None, on_end=None) -> ShellSession:
        """A new shell, as the Terminal module's settings say.

        Raises:
            StreamRefused: ``account_unknown {account}`` or
                ``shell_program_unusable {path}``.
        """
        if self._command:
            command, process = self._command, {}
            account, title = shell_account(), os.path.basename(self._command[0])
        else:
            settings = self._terminal() if self._terminal else TerminalConfig()
            if self._argv is not None:
                command, process, account = exec_plan(
                    self._argv, settings, self._platform
                )
                title = os.path.basename(self._argv[0])
            else:
                command, process, account, title = shell_plan(settings, self._platform)
        return ShellSession(
            session_id=self._session_id,
            terminal=PtyTerminal(
                command, cols=self._columns, rows=self._rows, process=process
            ),
            account=account,
            title=title,
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
