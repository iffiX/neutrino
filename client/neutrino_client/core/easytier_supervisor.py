"""The one easytier-core process the EasyTier daemon runs, as its own child.

The core runs only while its command is not None, which is while at least
one manual network or a console is configured. A change restarts it at
once; a core that ends by itself is started again after a wait that doubles
from ``CLIENT_EASYTIER_RESTART_MIN_S`` to ``CLIENT_EASYTIER_RESTART_MAX_S``,
and one that ran ``CLIENT_EASYTIER_STABLE_S`` first waits the least again.
The core's output goes, line by line, to a callable.

Not pure: starts, watches and ends a process.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import os
import subprocess
import threading
import time

from neutrino_client.constants import (
    CLIENT_EASYTIER_RESTART_MAX_S,
    CLIENT_EASYTIER_RESTART_MIN_S,
    CLIENT_EASYTIER_STABLE_S,
    CLIENT_EASYTIER_STOP_TIMEOUT_S,
)
from neutrino_client.platforms.base import CREATE_NO_WINDOW

# How often the watching thread looks at the core.
SUPERVISOR_TICK_S = 0.5


def _nobody(*_args) -> None:
    """Nobody listening."""


def start_core_process(argv: list, env: dict) -> "subprocess.Popen":
    """Start the core with no console, its output one text stream.

    Args:
        argv: The argument vector.
        env: The whole environment the core runs with.

    Returns:
        The started process.

    Raises:
        OSError: When it cannot be started.
    """
    return subprocess.Popen(
        argv,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


class EasytierCoreSupervisor:
    """Starts, restarts and stops the core to match its command."""

    def __init__(
        self,
        *,
        command_of,
        log=print,
        core_log=None,
        start_process=None,
        on_started=None,
        clock=None,
    ):
        """
        Args:
            command_of: Returns ``(argv, env)`` for the core, or None when
                nothing is configured and no core may run.
            log: Callable used for progress messages.
            core_log: Called with each line the core prints; None drops them.
            start_process: ``start_process(argv, env)`` returns a process
                with ``poll``, ``terminate``, ``kill``, ``wait`` and
                ``stdout``; None starts a real one.
            on_started: Called with each process once started; the Windows
                daemon ties the core to its own life here.
            clock: Returns the time in seconds; None is ``time.monotonic``.
        """
        self._command_of = command_of
        self._log = log
        self._core_log = core_log if core_log is not None else _nobody
        self._start_process = (
            start_process if start_process is not None else start_core_process
        )
        self._on_started = on_started if on_started is not None else _nobody
        self._clock = clock if clock is not None else time.monotonic
        self._lock = threading.RLock()
        self._process = None
        self._started_at = 0.0
        self._restart_at: "float | None" = None
        self._wait_s = CLIENT_EASYTIER_RESTART_MIN_S
        self._stop = threading.Event()
        self._thread: "threading.Thread | None" = None

    @property
    def is_running(self) -> bool:
        """Whether a core is running now."""
        with self._lock:
            return self._process is not None and self._process.poll() is None

    @property
    def restart_wait_s(self) -> float:
        """How long the next restart after a core's own end waits."""
        with self._lock:
            return self._wait_s

    def apply(self) -> None:
        """Match the core to the command now: stop it, then start it when one is wanted."""
        with self._lock:
            self._end_process()
            self._wait_s = CLIENT_EASYTIER_RESTART_MIN_S
            self._restart_at = None
            self._start()

    def tick(self) -> None:
        """Look at the core once: a core that ended is started again after its wait."""
        with self._lock:
            now = self._clock()
            process = self._process
            if process is not None:
                status = process.poll()
                if status is None:
                    if now - self._started_at >= CLIENT_EASYTIER_STABLE_S:
                        self._wait_s = CLIENT_EASYTIER_RESTART_MIN_S
                    return
                self._process = None
                if now - self._started_at >= CLIENT_EASYTIER_STABLE_S:
                    self._wait_s = CLIENT_EASYTIER_RESTART_MIN_S
                self._restart_at = now + self._wait_s
                self._log(
                    f"easytier-core ended with {status}; "
                    f"starting it again in {self._wait_s} s"
                )
                self._wait_s = min(self._wait_s * 2, CLIENT_EASYTIER_RESTART_MAX_S)
                return
            if self._restart_at is not None and now >= self._restart_at:
                self._restart_at = None
                self._start()

    def start(self) -> None:
        """Watch the core on a thread of its own until :meth:`stop`."""
        thread = threading.Thread(
            target=self._watch_forever, name="easytier_supervisor", daemon=True
        )
        thread.start()
        self._thread = thread

    def stop(self) -> None:
        """Stop watching and end the core. Idempotent."""
        self._stop.set()
        with self._lock:
            self._restart_at = None
            self._end_process()

    def _watch_forever(self) -> None:
        while not self._stop.wait(SUPERVISOR_TICK_S):
            try:
                self.tick()
            except Exception as error:  # noqa: BLE001 - the watch must survive
                self._log(f"easytier-core could not be watched: {error}")

    def _start(self) -> None:
        """Start a core when one is wanted; a failed start waits like an end."""
        command = self._command_of()
        if command is None:
            return
        argv, env = command
        try:
            process = self._start_process(list(argv), dict(env))
        except OSError as error:
            self._log(f"easytier-core could not start: {error}")
            self._restart_at = self._clock() + self._wait_s
            self._wait_s = min(self._wait_s * 2, CLIENT_EASYTIER_RESTART_MAX_S)
            return
        self._process = process
        self._started_at = self._clock()
        self._log(f"easytier-core started as {getattr(process, 'pid', '?')}")
        try:
            self._on_started(process)
        except OSError as error:
            self._log(f"easytier-core could not be tied to the daemon: {error}")
        stream = getattr(process, "stdout", None)
        if stream is not None:
            threading.Thread(
                target=self._pump, args=(stream,), name="easytier_output", daemon=True
            ).start()

    def _pump(self, stream) -> None:
        """Hand each line the core prints to the core log, until it ends."""
        try:
            for raw in iter(stream.readline, b""):
                line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
                self._core_log(line.rstrip("\r\n"))
        except (OSError, ValueError):
            return

    def _end_process(self) -> None:
        """End the running core: asked first, killed when it does not end."""
        process = self._process
        self._process = None
        if process is None or process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=CLIENT_EASYTIER_STOP_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=CLIENT_EASYTIER_STOP_TIMEOUT_S)
        except OSError:
            pass
        self._log("easytier-core stopped")
