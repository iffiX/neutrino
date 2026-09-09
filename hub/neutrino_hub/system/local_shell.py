"""A shell running on the gateway itself, behind a pseudo-terminal.

The Devices tab already has terminals, but those reach *other* machines over
SSH. This is the box itself, and connecting to itself over SSH to get a prompt
would be a strange way round — so the shell is started directly on a pty.

The shell runs as whatever the panel runs as, which is root. That is not an
escalation: the panel already reconfigures interfaces, loads firewall rules and
restarts services, so anyone holding a session can do all of that anyway. It is
worth being clear about rather than quiet, which is why it says so on the page.

Not pure: this starts processes and owns file descriptors.
"""

import asyncio
import contextlib
import fcntl
import os
import pathlib
import pty
import pwd
import signal
import struct
import termios

# Read in chunks rather than lines. A shell prompt has no newline after it, and
# waiting for one is what makes a terminal appear to swallow everything typed
# until Enter — the same mistake the SSH terminal made once already.
READ_CHUNK_BYTES = 4096

# Shells to fall back through when the account names one that is not usable.
# An appliance should still hand out a prompt on a box whose root shell is
# /usr/sbin/nologin.
FALLBACK_SHELLS = ("/bin/bash", "/bin/sh")

DEFAULT_ROWS = 24
DEFAULT_COLUMNS = 80


def _sweep_session(session_id: int) -> None:
    """Kill every process still in a terminal session.

    Read from ``/proc`` rather than tracked as processes are started, because
    the shell starts them and never tells anyone. A session is the one grouping
    a process cannot escape by forking or by starting a job of its own, so it
    is what makes "close the tab, leave nothing behind" true.

    Args:
        session_id: The session leader's pid, which is also the session id.
    """
    for pid in _session_members(session_id):
        if pid == os.getpid():
            continue
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGKILL)


def _session_members(session_id: int) -> list[int]:
    members = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            stat = pathlib.Path(f"/proc/{entry}/stat").read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            # The command name sits in parentheses and may contain spaces, so
            # the fields after it are found from the last ") " rather than by
            # splitting the whole line. Then: state, ppid, pgrp, session.
            fields = stat.rsplit(") ", 1)[1].split()
            if int(fields[3]) == session_id:
                members.append(int(entry))
        except (IndexError, ValueError):
            continue
    return members


def login_home() -> str:
    """Where a shell here should start.

    The panel is started from the checkout, so a shell inheriting its directory
    opens in the install tree — an odd place to land, and one where a stray
    command edits the gateway's own source. Home is the neutral place.

    Returns:
        The account's home directory, or ``/`` if it has none.
    """
    try:
        home = pwd.getpwuid(os.getuid()).pw_dir
    except KeyError:
        home = ""
    return home if home and os.path.isdir(home) else "/"


def login_shell() -> str:
    """The shell to start.

    Returns:
        The account's own shell where it can actually run one, else the first
        usable fallback.
    """
    try:
        shell = pwd.getpwuid(os.getuid()).pw_shell
    except KeyError:
        shell = ""
    if shell and os.access(shell, os.X_OK) and "nologin" not in shell:
        return shell
    for candidate in FALLBACK_SHELLS:
        if os.access(candidate, os.X_OK):
            return candidate
    return FALLBACK_SHELLS[-1]


class LocalShellSession:
    """One shell process and the pseudo-terminal it is attached to."""

    def __init__(
        self,
        *,
        rows: int = DEFAULT_ROWS,
        columns: int = DEFAULT_COLUMNS,
        command: list[str] | None = None,
    ):
        """
        Args:
            rows: Initial terminal height.
            columns: Initial terminal width.
            command: What to run on the terminal. None is the box's own login
                shell; any other command gets the same pty and the same
                sweep on close.
        """
        self._rows = rows
        self._columns = columns
        self._command = command
        self._master_fd: int | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._output: asyncio.Queue[bytes] = asyncio.Queue()

    @property
    def is_running(self) -> bool:
        """Whether the shell is still alive."""
        return self._process is not None and self._process.returncode is None

    async def exit_code(self) -> "int | None":
        """The shell's exit status, waited for.

        Returns:
            The code, or None when nothing was ever started.
        """
        if self._process is None:
            return None
        return await self._process.wait()

    async def start(self) -> None:
        """Start the shell on a new pseudo-terminal.

        Raises:
            OSError: If the pty cannot be allocated or the shell cannot run.
        """
        master_fd, slave_fd = pty.openpty()
        self._master_fd = master_fd
        # Watched by the event loop rather than read from a thread. A blocking
        # read in a worker cannot be cancelled: a timed-out wait would leave the
        # thread stuck on it forever, and shutdown would then hang waiting for
        # the executor to drain.
        os.set_blocking(master_fd, False)
        asyncio.get_running_loop().add_reader(master_fd, self._on_readable)
        self.resize(self._columns, self._rows)
        command = self._command or [login_shell(), "-i"]
        try:
            self._process = await asyncio.create_subprocess_exec(
                *command,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                # Its own session and controlling terminal, so job control works
                # and killing the session cannot reach back into the panel.
                start_new_session=True,
                cwd=login_home(),
                env=self._environment(),
            )
        finally:
            # The child holds the slave end now. Keeping a copy here would mean
            # reads never see end-of-file when the shell exits, and the terminal
            # would hang open after `exit`.
            os.close(slave_fd)

    async def read(self) -> bytes:
        """Wait for the next output from the shell.

        Returns:
            Whatever the shell wrote, or empty once the terminal is finished.
        """
        return await self._output.get()

    def write(self, data: str) -> None:
        """Send keystrokes to the shell.

        Args:
            data: Text as typed, already decoded.
        """
        if self._master_fd is None:
            return
        try:
            os.write(self._master_fd, data.encode("utf-8"))
        except OSError:
            pass

    def resize(self, columns: int, rows: int) -> None:
        """Tell the shell how big its window is.

        Without this everything is drawn for 80x24, so full-screen programs —
        htop, less, an editor — paint into the wrong shape and look broken.

        Columns first, matching the SSH sessions the same websocket helper
        drives. The two orderings are easy to transpose and the result is a
        terminal that is subtly the wrong shape rather than obviously broken.

        Args:
            columns: Terminal width in characters.
            rows: Terminal height in characters.
        """
        self._rows = max(1, rows)
        self._columns = max(1, columns)
        if self._master_fd is None:
            return
        size = struct.pack("HHHH", self._rows, self._columns, 0, 0)
        try:
            fcntl.ioctl(self._master_fd, termios.TIOCSWINSZ, size)
        except OSError:
            pass

    async def close(self) -> None:
        """Stop the shell and everything it started, then release the terminal.

        The process group is not enough. Under job control a background job —
        ``sleep 300 &`` — gets a group of its own, so signalling the shell's
        group leaves it running, and on an appliance with no other window into
        itself those accumulate invisibly with every tab closed. What they do
        share is the session, which nothing can leave, so the session is what
        gets swept.

        This does mean closing a tab ends its background jobs, where a plain
        exiting shell would leave them. That is the right way round here: the
        tab is the only handle anyone has on them. Anything meant to outlive it
        should be started under tmux or nohup, which detach from the session on
        purpose.
        """
        session_id = self._process.pid if self._process is not None else None
        if self._process is not None and self._process.returncode is None:
            # killpg takes a positive group id, unlike kill(-pid) which takes
            # the negated one. start_new_session made the shell its own group
            # leader, so its pid is that group's id.
            group_id = self._process.pid
            for sig in (signal.SIGHUP, signal.SIGKILL):
                try:
                    os.killpg(group_id, sig)
                except OSError:
                    # Already gone, or never a group of its own. Either way
                    # there is nothing left here to signal.
                    break
                try:
                    await asyncio.wait_for(self._process.wait(), timeout=2)
                    break
                except asyncio.TimeoutError:
                    continue
        if session_id is not None:
            _sweep_session(session_id)
        self._stop_watching()
        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._master_fd = None
        # Anything still waiting in read() is released rather than left hanging.
        self._output.put_nowait(b"")

    def _on_readable(self) -> None:
        """Drain what the terminal has ready, on the event loop's prompting."""
        if self._master_fd is None:
            return
        try:
            chunk = os.read(self._master_fd, READ_CHUNK_BYTES)
        except BlockingIOError:
            return
        except OSError:
            # The shell exited and took the terminal with it.
            chunk = b""
        if not chunk:
            self._stop_watching()
        self._output.put_nowait(chunk)

    def _stop_watching(self) -> None:
        if self._master_fd is None:
            return
        with contextlib.suppress(RuntimeError, ValueError):
            asyncio.get_running_loop().remove_reader(self._master_fd)

    def _environment(self) -> dict[str, str]:
        environment = dict(os.environ)
        environment["TERM"] = "xterm-256color"
        # Matching the directory the shell starts in, so ``~`` and ``cd`` agree
        # with where the prompt actually is.
        environment["HOME"] = login_home()
        # The panel is not a login shell and does not inherit one, so a prompt
        # here would otherwise have no idea what it is talking to.
        environment.setdefault("LANG", "C.UTF-8")
        environment["NEUTRINO_PANEL"] = "1"
        return environment
