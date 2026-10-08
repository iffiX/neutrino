"""One command run on this machine, over one ``exec`` stream.

The open is ``{argv, is_tty, cols, rows}``: ``argv`` runs as given with no
shell between, as the account a new shell runs as, in that account's home
with its environment. With ``is_tty`` it runs on the terminal a shell gets,
:class:`~neutrino_agent.streams.shell.ShellStream` or on Windows
:class:`~neutrino_agent.streams.windows_shell.WindowsShellStream`, never
kept. Without it, :class:`ExecStream` starts it on three pipes: stdout and
stderr are read apart and sent up, each frame headed with its ``fd``, no
faster than the hub's credit; the hub's bytes go to stdin in order, and
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
    AGENT_EXEC_FD_STDERR,
    AGENT_EXEC_FD_STDOUT,
    AGENT_SHELL_KILL_TIMEOUT_S,
    AGENT_SHELL_READ_BYTES,
    AGENT_WS_STREAM_CREDIT_BYTES,
)
from neutrino_agent.exceptions import StreamClosed, StreamRefused
from neutrino_agent.modules.terminal.config import TerminalConfig
from neutrino_agent.platforms import win32
from neutrino_agent.streams.shell import (
    ShellStream,
    check_exec_argv,
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
        args: ``{"argv", "is_tty", "cols", "rows"}``.
        terminal: Returns the Terminal module's
            :class:`~neutrino_agent.modules.terminal.config.TerminalConfig`
            the command runs with; None runs it as the agent.
        platform: The machine's platform, which steps down to an account.

    Returns:
        The handler, not yet opened.
    """
    argv = args.get("argv")
    if not bool(args.get("is_tty", False)):
        return ExecStream(channel, argv, terminal=terminal, platform=platform)
    size = {key: args[key] for key in ("cols", "rows") if key in args}
    if sys.platform == "win32":
        from neutrino_agent.streams.windows_shell import WindowsShellStream

        return WindowsShellStream(channel, size, platform=platform, argv=argv)
    return ShellStream(channel, size, argv=argv, terminal=terminal, platform=platform)


class ExecStream:
    """One command on three pipes, its two outputs sent apart."""

    def __init__(self, channel, argv, *, terminal=None, platform=None):
        """
        Args:
            channel: The stream's channel.
            argv: The command, as the open carries it.
            terminal: Returns the Terminal module's settings; None is the
                defaults.
            platform: The machine's platform, which steps down to an
                account and, on Windows, names the directory a shell starts
                in.
        """
        self._channel = channel
        self._argv = argv
        self._terminal = terminal
        self._platform = platform
        self._command: list = []
        self._process_arguments: dict = {}
        self._process: "subprocess.Popen | None" = None
        self._job = None
        self._is_done = threading.Event()
        self._wake = threading.Event()

    def open(self) -> None:
        """Settle what runs and as whom; nothing starts yet.

        Raises:
            StreamRefused: ``account_unknown {account}`` or
                ``shell_program_unusable {path}``.
        """
        if sys.platform == "win32":
            check_exec_argv(self._argv)
            self._command = list(self._argv)
            self._process_arguments = {
                "cwd": self._windows_platform().shell_start_dir()
            }
            return
        settings = self._terminal() if self._terminal else TerminalConfig()
        self._command, process, _ = exec_plan(self._argv, settings, self._platform)
        self._process_arguments = dict(process)

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
            return {"code": "shell_failed", "params": {"detail": str(error)[:200]}}
        self._process = process
        self._channel.offer_credit(AGENT_WS_STREAM_CREDIT_BYTES)
        ended = [threading.Event(), threading.Event()]
        readers = [
            self._thread(
                self._pump_output, process.stdout, AGENT_EXEC_FD_STDOUT, ended[0]
            ),
            self._thread(
                self._pump_output, process.stderr, AGENT_EXEC_FD_STDERR, ended[1]
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
            process = subprocess.Popen(
                self._command,
                **pipes,
                cwd=cwd,
                creationflags=win32.CREATE_NO_WINDOW,
                **arguments,
            )
            self._job = self._windows_job(process)
            return process
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
            if self._job is not None:
                # Closing the job ends every process still in it.
                with contextlib.suppress(OSError):
                    win32.libraries().kernel32.CloseHandle(self._job)
                self._job = None
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=AGENT_SHELL_KILL_TIMEOUT_S)
            exit_code = process.returncode if process.returncode is not None else 1
        else:
            exit_code = end_session(process)
        with contextlib.suppress(OSError, ValueError):
            process.stdin.close()
        return exit_code

    def _pump_output(self, pipe, fd: int, ended: threading.Event) -> None:
        """Send one output, each frame headed with its ``fd``, until it ends."""
        head = bytes([fd])
        try:
            while True:
                try:
                    chunk = pipe.read1(AGENT_SHELL_READ_BYTES)
                except (OSError, ValueError):
                    chunk = b""
                if not chunk:
                    return
                try:
                    self._channel.send_bytes(chunk, head=head)
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
                self._channel.offer_credit(len(item[1]))
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

    @staticmethod
    def _windows_job(process: subprocess.Popen):
        """A job holding the process, that ends everything in it when closed."""
        from neutrino_agent.streams.windows_shell import kill_on_close_job

        kernel32 = win32.libraries().kernel32
        job = kill_on_close_job(kernel32)
        kernel32.AssignProcessToJobObject(job, int(process._handle))
        return job
