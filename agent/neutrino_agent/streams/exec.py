"""One command run on this machine, over one ``exec`` stream.

The open is ``{argv, is_tty, cols, rows}``: ``argv`` runs as given with no
shell between, as the account a new shell runs as, in that account's home
with its environment. With ``is_tty`` it runs on the terminal a shell gets,
:class:`~neutrino_agent.streams.shell.ShellStream` or on Windows
:class:`~neutrino_agent.streams.windows_shell.WindowsShellStream`, never
kept. Without it, :class:`ExecStream` starts it on three pipes: stdout and
stderr are read apart and sent up, stdout as ``data`` records and stderr
as ``stderr`` records; the hub's ``data`` goes to stdin in order, and
``eof`` closes stdin. The stream closes with the exit code once the process
ended and both outputs reached end of file. A stream the hub closes first
ends the process and everything it started.

Not pure: starts processes and owns their pipes.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import threading

from neutrino_agent.constants import (
    AGENT_SHELL_KILL_TIMEOUT_S,
    AGENT_SHELL_READ_BYTES,
)
from neutrino_agent.exceptions import StreamClosed
from neutrino_agent.modules.terminal.config import TerminalConfig
from neutrino_agent.streams.shell import (
    ShellStream,
    check_exec_argv,
    chosen_account,
    end_session,
    exec_plan,
    login_home,
    shell_environment,
)

# How long the wait for the outputs' end, or for the process, sleeps before
# looking at the stream again.
EXEC_POLL_S = 0.5


def open_exec_stream(channel, args: dict, *, terminal=None, platform=None):
    """The handler for one ``exec`` stream.

    Args:
        channel: The stream's channel.
        args: ``{"argv", "is_tty", "cols", "rows", "account"}``.
        terminal: Returns the Terminal module's
            :class:`~neutrino_agent.modules.terminal.config.TerminalConfig`
            whose enabled account the command runs as; None enables no
            account.
        platform: The machine's platform, which steps down to an account.

    Returns:
        The handler, not yet opened.
    """
    argv = args.get("argv")
    account = str(args.get("account", "") or "")
    if not bool(args.get("is_tty", False)):
        return ExecStream(
            channel, argv, account=account, terminal=terminal, platform=platform
        )
    opened = {key: args[key] for key in ("cols", "rows") if key in args}
    opened["account"] = account
    if sys.platform == "win32":
        from neutrino_agent.streams.windows_shell import WindowsShellStream

        return WindowsShellStream(
            channel, opened, platform=platform, terminal=terminal, argv=argv
        )
    return ShellStream(channel, opened, argv=argv, terminal=terminal, platform=platform)


class ExecStream:
    """One command on three pipes, its two outputs sent apart."""

    def __init__(
        self,
        channel,
        argv,
        *,
        account: str = "",
        terminal=None,
        platform=None,
        logon_class=None,
    ):
        """
        Args:
            channel: The stream's channel.
            argv: The command, as the open carries it.
            account: The enabled account the command runs as; empty is the
                first one.
            terminal: Returns the Terminal module's settings; None enables
                no account.
            platform: The machine's platform, which steps down to an
                account and, on Windows, names the account's profile.
            logon_class: Windows: logs an account on, called with
                ``(account, password)``; None is
                :class:`~neutrino_agent.platforms.windows_logon.WindowsAccountLogon`.
        """
        self._channel = channel
        self._argv = argv
        self._account = account
        self._terminal = terminal
        self._platform = platform
        self._logon_class = logon_class
        self._logon = None
        self._command: list = []
        self._process_arguments: dict = {}
        self._process = None
        self._is_done = threading.Event()
        self._wake = threading.Event()

    def open(self) -> None:
        """Settle what runs and as whom; nothing starts yet.

        Raises:
            StreamRefused: ``terminal_account_missing``,
                ``account_not_enabled {account}``, ``account_unknown
                {account}`` or ``shell_program_unusable {path}``, and on
                Windows ``credential_missing {account}`` and
                ``credential_invalid {account}``.
        """
        settings = self._terminal() if self._terminal else TerminalConfig()
        held = chosen_account(settings, self._account)
        if sys.platform == "win32":
            self._open_windows(held)
            return
        self._command, process, _ = exec_plan(self._argv, held, self._platform)
        self._process_arguments = dict(process)

    def _open_windows(self, held) -> None:
        """Check the command and log the account on.

        Raises:
            StreamRefused: as :meth:`open`.
        """
        from neutrino_agent.streams.windows_shell import account_logon

        check_exec_argv(self._argv)
        self._command = list(self._argv)
        self._logon = account_logon(held, logon_class=self._windows_logon_class())
        try:
            cwd = self._windows_platform().account_home(held.account)
        except (KeyError, OSError):
            cwd = self._windows_platform().shell_start_dir()
        self._process_arguments = {"cwd": cwd}

    def run(self) -> dict:
        """Run the command until it ended or the stream closed.

        Returns:
            ``{"code", "params"}``: ``exit_code`` once the process ended and
            both outputs reached end of file, empty params when the stream
            closed first, and ``shell_failed`` with ``detail`` when it
            could not start.
        """
        try:
            process = self._start()
        except OSError as error:
            self._close_logon()
            return {"code": "shell_failed", "params": {"detail": str(error)[:200]}}
        self._process = process
        ended = [threading.Event(), threading.Event()]
        readers = [
            self._thread(
                self._pump_output, process.stdout, self._channel.send_bytes, ended[0]
            ),
            self._thread(
                self._pump_output, process.stderr, self._channel.send_stderr, ended[1]
            ),
        ]
        self._thread(self._feed_input, process.stdin)
        while not self._is_stopped():
            self._wake.clear()
            if all(each.is_set() for each in ended):
                break
            self._wake.wait(EXEC_POLL_S)
        while not self._is_stopped():
            try:
                process.wait(timeout=EXEC_POLL_S)
                break
            except subprocess.TimeoutExpired:
                continue
        is_closed_first = self._is_stopped()
        exit_code = self._end()
        self._is_done.set()
        for reader, pipe in zip(readers, (process.stdout, process.stderr)):
            reader.join(timeout=AGENT_SHELL_KILL_TIMEOUT_S)
            if not reader.is_alive():
                with contextlib.suppress(OSError, ValueError):
                    pipe.close()
        if is_closed_first:
            return {"code": "", "params": {}}
        return {"code": "", "params": {"exit_code": exit_code}}

    def _start(self) -> subprocess.Popen:
        """Start the command on its three pipes.

        Raises:
            OSError: When it cannot start.
        """
        arguments = dict(self._process_arguments)
        arguments.pop("owner", None)
        base = arguments.pop("env", None)
        cwd = arguments.pop("cwd", "") or None
        if cwd is not None and not os.path.isdir(cwd):
            cwd = None
        pipes = {
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
        }
        if sys.platform == "win32":
            from neutrino_agent.platforms.windows_logon import (
                WindowsAccountPipeProcess,
            )

            return WindowsAccountPipeProcess(
                self._logon, self._command, start_dir=cwd or ""
            )
        if cwd is None:
            cwd = login_home()
        return subprocess.Popen(
            self._command,
            **pipes,
            start_new_session=True,
            cwd=cwd,
            env=shell_environment(base),
            **arguments,
        )

    def _end(self) -> int:
        """Stop the process and everything it started, close its stdin.

        Returns:
            The exit code; a signal death reads as 128 plus the signal's
            number.
        """
        process = self._process
        if sys.platform == "win32":
            exit_code = process.end()
            self._close_logon()
        else:
            exit_code = end_session(process)
        with contextlib.suppress(OSError, ValueError):
            process.stdin.close()
        return exit_code

    def _pump_output(self, pipe, send, ended: threading.Event) -> None:
        """Send one output as its own records until it ends.

        Args:
            pipe: The process's stdout or stderr.
            send: The channel's ``send_bytes`` for stdout, ``send_stderr``
                for stderr.
            ended: Set once the output reached end of file.
        """
        try:
            while True:
                try:
                    chunk = pipe.read1(AGENT_SHELL_READ_BYTES)
                except (OSError, ValueError):
                    chunk = b""
                if not chunk:
                    return
                try:
                    send(chunk)
                except StreamClosed:
                    return
        finally:
            ended.set()
            self._wake.set()

    def _feed_input(self, pipe) -> None:
        """Write the hub's bytes to stdin in order; close it on ``eof``."""
        is_ended = False
        while not self._is_done.is_set():
            item = self._channel.recv(timeout=EXEC_POLL_S)
            if item is None or self._is_done.is_set():
                continue
            if item[0] == "data":
                if not is_ended:
                    with contextlib.suppress(OSError, ValueError):
                        pipe.write(item[1])
                        pipe.flush()
            elif item[0] == "eof" and not is_ended:
                is_ended = True
                with contextlib.suppress(OSError, ValueError):
                    pipe.close()
            elif item[0] == "close":
                self._is_done.set()
                self._wake.set()
                return

    def _is_stopped(self) -> bool:
        """Whether the stream closed before the command ended."""
        return self._is_done.is_set() or bool(self._channel.is_closed)

    def _thread(self, target, *args) -> threading.Thread:
        thread = threading.Thread(
            target=target,
            args=args,
            name=f"agent_exec_{self._channel.id}",
            daemon=True,
        )
        thread.start()
        return thread

    def _windows_platform(self):
        """The Windows platform, made on first use."""
        if self._platform is None:
            from neutrino_agent.platforms.windows import WindowsPlatform

            self._platform = WindowsPlatform()
        return self._platform

    def _close_logon(self) -> None:
        """Release the Windows logon the command ran under."""
        logon, self._logon = self._logon, None
        if logon is not None:
            logon.close()

    def _windows_logon_class(self):
        """What logs an account on, the real one unless a test stands in."""
        if self._logon_class is None:
            from neutrino_agent.platforms.windows_logon import WindowsAccountLogon

            self._logon_class = WindowsAccountLogon
        return self._logon_class
