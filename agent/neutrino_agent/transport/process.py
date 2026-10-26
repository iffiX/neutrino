"""The agent's transport, started as its child.

The agent starts ``neutrino_transport agent --listen <listener>`` and writes
a secret made afresh for this start as the first line of the child's
standard input, which stays open: the transport exits when it ends, so it
never outlives the agent. Every local connection then opens with that
secret. The transport's own log lines go to the agent's log.

Not pure: starts a process.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import functools
import ntpath
import os
import secrets
import subprocess
import sys
import threading
import time

from neutrino_agent.constants import AGENT_TRANSPORT_BIN_VARIABLE
from neutrino_agent.transport.connection import open_local
from neutrino_agent.transport.control import TransportControlClient
from neutrino_agent.transport.constants import (
    TRANSPORT_LISTEN_OPTION,
    TRANSPORT_ONE_SHOT_SUFFIX,
    TRANSPORT_PIPE_NAME,
    TRANSPORT_PIPE_PREFIX,
    TRANSPORT_PROGRAM_NAME,
    TRANSPORT_PROGRAM_NAME_WINDOWS,
    TRANSPORT_ROLE_ARGUMENT,
    TRANSPORT_SECRET_BYTES,
    TRANSPORT_SOCKET_PATH,
    TRANSPORT_SOCKET_PATH_DARWIN,
    TRANSPORT_SOCKET_SUFFIX,
    TRANSPORT_START_POLL_S,
    TRANSPORT_START_TIMEOUT_S,
    TRANSPORT_STOP_TIMEOUT_S,
)

# Windows starts the child with no console window of its own.
CREATE_NO_WINDOW = 0x08000000


def listen_path(os_name: str, *, is_one_shot: bool = False) -> str:
    """Where a transport the agent starts listens.

    Args:
        os_name: ``linux``, ``darwin`` or ``windows``.
        is_one_shot: A ``nagent join``, ``leave`` or ``status`` process's
            own transport, named after its process beside the service's.

    Returns:
        The socket's path, or the pipe's name on Windows.
    """
    if os_name == "windows":
        base = TRANSPORT_PIPE_NAME
        suffix = ""
    else:
        path = (
            TRANSPORT_SOCKET_PATH_DARWIN
            if os_name == "darwin"
            else (TRANSPORT_SOCKET_PATH)
        )
        base, suffix = path[: -len(TRANSPORT_SOCKET_SUFFIX)], TRANSPORT_SOCKET_SUFFIX
    if is_one_shot:
        base += TRANSPORT_ONE_SHOT_SUFFIX.format(pid=os.getpid())
    return base + suffix


def program_path(platform) -> str:
    """The transport program the agent starts.

    Args:
        platform: The machine's platform, which names ``agent_bin_dir``.

    Returns:
        ``NEUTRINO_TRANSPORT_BIN`` when it is set, else
        ``neutrino_transport`` in the agent's ``bin`` directory.
    """
    named = os.environ.get(AGENT_TRANSPORT_BIN_VARIABLE, "")
    if named:
        return named
    if platform.os_name == "windows":
        return ntpath.join(platform.agent_bin_dir(), TRANSPORT_PROGRAM_NAME_WINDOWS)
    return os.path.join(platform.agent_bin_dir(), TRANSPORT_PROGRAM_NAME)


class TransportProcess:
    """One transport child: started, reached, and stopped.

    Attributes:
        listen: Where it listens.
        secret: The secret every local connection opens with, 64 hex
            characters; empty until it starts.
    """

    def __init__(self, *, program: str, listen: str, log=print):
        """
        Args:
            program: The transport program.
            listen: The socket's path or the pipe's name.
            log: Callable used for the transport's own lines and the
                agent's lines about it.
        """
        self._program = program
        self.listen = listen
        self._log = log
        self.secret = ""
        self._process: "subprocess.Popen | None" = None

    def is_running(self) -> bool:
        """Whether the child runs."""
        return self._process is not None and self._process.poll() is None

    def start(self) -> None:
        """Start the child and wait until its listener answers.

        Raises:
            OSError: When the program cannot start, ends before its
                listener answers, or the listener does not answer within
                ``TRANSPORT_START_TIMEOUT_S``.
        """
        self.stop()
        self._prepare_listener()
        self.secret = secrets.token_hex(TRANSPORT_SECRET_BYTES)
        keywords = {}
        if sys.platform == "win32":
            keywords["creationflags"] = CREATE_NO_WINDOW
        process = subprocess.Popen(
            [
                self._program,
                TRANSPORT_ROLE_ARGUMENT,
                TRANSPORT_LISTEN_OPTION,
                self.listen,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            **keywords,
        )
        self._process = process
        try:
            process.stdin.write((self.secret + "\n").encode("ascii"))
            process.stdin.flush()
        except OSError:
            self.stop()
            raise
        threading.Thread(
            target=self._relay_log,
            args=(process,),
            name="agent_transport_log",
            daemon=True,
        ).start()
        deadline = time.monotonic() + TRANSPORT_START_TIMEOUT_S
        while True:
            if process.poll() is not None:
                code = process.returncode
                self.stop()
                raise OSError(f"the transport exited with {code} at its start")
            try:
                open_local(self.listen, timeout_s=TRANSPORT_START_POLL_S).close()
                return
            except OSError:
                if time.monotonic() >= deadline:
                    self.stop()
                    raise OSError(
                        f"the transport did not answer on {self.listen} in "
                        f"{TRANSPORT_START_TIMEOUT_S:.0f} s"
                    ) from None
            time.sleep(TRANSPORT_START_POLL_S)

    def stop(self) -> None:
        """End the child: its standard input closes, and a child that does
        not exit in time is killed."""
        process, self._process = self._process, None
        if process is None:
            return
        with contextlib.suppress(OSError):
            process.stdin.close()
        try:
            process.wait(timeout=TRANSPORT_STOP_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(OSError):
                process.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=TRANSPORT_STOP_TIMEOUT_S)

    def _prepare_listener(self) -> None:
        """Make the socket's directory root-only and take a stale socket away."""
        if self.listen.startswith(TRANSPORT_PIPE_PREFIX):
            return
        directory = os.path.dirname(self.listen)
        os.makedirs(directory, mode=0o700, exist_ok=True)
        with contextlib.suppress(OSError):
            os.chmod(directory, 0o700)
        with contextlib.suppress(FileNotFoundError):
            os.unlink(self.listen)

    def _relay_log(self, process: subprocess.Popen) -> None:
        """Pass each line the transport writes to its stderr into the agent's log."""
        with contextlib.suppress(OSError, ValueError):
            for raw in process.stderr:
                line = raw.decode("utf-8", "replace").rstrip()
                if line:
                    self._log(f"transport: {line}")


@contextlib.contextmanager
def one_shot_transport(platform, *, on_event=None, on_frame=None, log=print):
    """A transport of this process's own, for one join, leave or status probe.

    Args:
        platform: The machine's platform, which names the program and the
            listener's system.
        on_event: Called with each event line; None drops them.
        on_frame: Called with each frame the hub sent; None drops them.
        log: Callable used for the transport's own lines.

    Yields:
        A started :class:`TransportControlClient`.

    Raises:
        OSError: When the transport cannot start or does not answer.
    """
    process = TransportProcess(
        program=program_path(platform),
        listen=listen_path(platform.os_name, is_one_shot=True),
        log=log,
    )
    process.start()
    control = TransportControlClient(
        connect=functools.partial(open_local, process.listen),
        secret=process.secret,
        on_event=on_event or _drop,
        on_frame=on_frame or _drop,
        on_question=_refuse_question,
        log=log,
    )
    try:
        control.start()
        yield control
    finally:
        control.close()
        process.stop()


def _drop(line: dict) -> None:
    """An event or a frame nobody waits for."""


def _refuse_question(question: dict) -> dict:
    """A one-shot transport publishes no port."""
    return {"code": "port_not_published", "params": {"port": question.get("port", 0)}}
