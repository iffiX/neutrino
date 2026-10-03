"""The daemons the hub's one service runs as its own children.

On macOS and Windows one process serves the panel and starts each daemon
from the start line it holds. A child that ends is started again after a
wait that doubles from ``SYSTEM_CHILD_RESTART_MIN_S`` to
``SYSTEM_CHILD_RESTART_MAX_S``; one that ran ``SYSTEM_CHILD_STABLE_S``
first waits the least again. A child that requires another runs only while
that one runs: it is stopped before the one it requires stops, restarts or
is found ended, and started again once that one runs. Each child's output
goes to ``<name>.log`` under the log directory, rotated by size.

Not pure: starts, watches and ends processes.
"""

import logging
import logging.handlers
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from neutrino_hub.system.constants import (
    SYSTEM_CHILD_LOG_BACKUP_COUNT,
    SYSTEM_CHILD_LOG_MAX_BYTES,
    SYSTEM_CHILD_LOG_SUFFIX,
    SYSTEM_CHILD_RESTART_MAX_S,
    SYSTEM_CHILD_RESTART_MIN_S,
    SYSTEM_CHILD_STABLE_S,
    SYSTEM_CHILD_STOP_TIMEOUT_S,
    SYSTEM_CHILD_TICK_S,
)


def start_child_process(argv: list, env: dict, cwd, creation_flags: int):
    """Start one child with its output as one stream.

    Args:
        argv: The argument vector.
        env: The whole environment the child runs with.
        cwd: The directory it starts in; None keeps this process's.
        creation_flags: Windows process creation flags; 0 elsewhere.

    Returns:
        The started process.

    Raises:
        OSError: When it cannot be started.
    """
    return subprocess.Popen(
        argv,
        env=env,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=creation_flags,
    )


@dataclass
class ChildStartLine:
    """How one child is started.

    Attributes:
        argv: The argument vector, the program first.
        env: Variables added to this process's environment.
        cwd: The directory it starts in; empty keeps this process's.
        log_name: The file its output goes to under the log directory,
            without the suffix; empty is the child's own name.
    """

    argv: list
    env: dict = field(default_factory=dict)
    cwd: str = ""
    log_name: str = ""

    def to_dict(self) -> dict:
        """The start line as ``services.json`` keeps it.

        Returns:
            ``argv``, ``env``, ``cwd`` and ``log_name``.
        """
        return {
            "argv": [str(word) for word in self.argv],
            "env": {str(key): str(value) for key, value in self.env.items()},
            "cwd": str(self.cwd),
            "log_name": self.log_name,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ChildStartLine":
        """Read a start line back from ``services.json``.

        Args:
            data: What :meth:`to_dict` wrote.

        Returns:
            The start line.

        Raises:
            ValueError: When it has no argument vector.
        """
        argv = data.get("argv")
        if not isinstance(argv, list) or not argv:
            raise ValueError("a start line needs an argument vector")
        return cls(
            argv=[str(word) for word in argv],
            env=dict(data.get("env") or {}),
            cwd=str(data.get("cwd") or ""),
            log_name=str(data.get("log_name") or ""),
        )


class ChildProcessSupervisor:
    """Starts, restarts and stops the service's children by name."""

    def __init__(
        self,
        *,
        log_dir: Path,
        base_env=None,
        start_process=None,
        on_started=None,
        creation_flags: int = 0,
        requirements: dict | None = None,
        clock=None,
        log=print,
    ):
        """
        Args:
            log_dir: Where each child's ``<name>.log`` is written.
            base_env: The environment every child starts from; None is a
                copy of this process's at each start.
            start_process: ``start_process(argv, env, cwd, creation_flags)``
                returns a process with ``poll``, ``terminate``, ``kill``,
                ``wait`` and ``stdout``; None starts a real one.
            on_started: Called with each process once started; the Windows
                platform ties it to the service's life here.
            creation_flags: Windows process creation flags; 0 elsewhere.
            requirements: Child name to the child it runs only beside; None
                is none.
            clock: Returns the time in seconds; None is ``time.monotonic``.
            log: Called with each progress line.
        """
        self._log_dir = Path(log_dir)
        self._base_env = base_env
        self._start_process = start_process or start_child_process
        self._on_started = on_started
        self._creation_flags = creation_flags
        self._requirements = dict(requirements or {})
        self._watcher = None
        self._clock = clock or time.monotonic
        self._log = log
        self._lock = threading.RLock()
        self._children: dict = {}
        self._loggers: dict = {}
        self._stopping = threading.Event()
        self._thread = None

    def set_watcher(self, watcher) -> None:
        """Hand every ended child and every tick to one watcher.

        Args:
            watcher: Has ``child_ended(name)``, called once a child's process
                has ended for any reason, and ``tick()``, called after each
                tick of the watch thread; None is none.
        """
        self._watcher = watcher

    def set_start_line(self, name: str, line) -> None:
        """Hold one child's start line; None forgets it and stops the child.

        Args:
            name: The child's name.
            line: A :class:`ChildStartLine`, or None.
        """
        with self._lock:
            child = self._child(name)
            child.line = line
            if line is None:
                child.is_wanted = False
                self._end(name)

    def start_line(self, name: str):
        """The start line held for one child.

        Args:
            name: The child's name.

        Returns:
            The :class:`ChildStartLine`, or None when none is held.
        """
        with self._lock:
            child = self._children.get(name)
            return child.line if child is not None else None

    def start(self, name: str) -> None:
        """Run one child from now on; one already running is left as it is.

        A child whose required child is not running is started once that
        one runs.

        Args:
            name: The child's name.

        Raises:
            KeyError: When no start line is held for it.
        """
        with self._lock:
            child = self._child(name)
            if child.line is None:
                raise KeyError(f"no start line is held for {name!r}")
            child.is_wanted = True
            child.wait_s = SYSTEM_CHILD_RESTART_MIN_S
            child.restart_at = None
            if not self._is_alive(child) and self._is_ready(name):
                self._start(name, child)

    def stop(self, name: str) -> None:
        """Stop one child and keep it stopped.

        Args:
            name: The child's name.
        """
        with self._lock:
            child = self._child(name)
            child.is_wanted = False
            child.restart_at = None
            self._end(name)

    def restart(self, name: str) -> None:
        """Stop one child and start it again at once.

        Args:
            name: The child's name.

        Raises:
            KeyError: When no start line is held for it.
        """
        with self._lock:
            child = self._child(name)
            if child.line is None:
                raise KeyError(f"no start line is held for {name!r}")
            self._end(name)
            self.start(name)

    def is_running(self, name: str) -> bool:
        """Whether one child runs now.

        Args:
            name: The child's name.

        Returns:
            True while its process has not ended.
        """
        with self._lock:
            child = self._children.get(name)
            return child is not None and self._is_alive(child)

    def tick(self) -> None:
        """Look at every child once: one that ended starts again after its wait.

        A child waiting on the child it requires starts once that one runs.
        The watcher's own tick runs after, outside the lock.
        """
        with self._lock:
            now = self._clock()
            for name, child in list(self._children.items()):
                self._tick_one(name, child, now)
            for name in self._requirements:
                child = self._children.get(name)
                if (
                    child is not None
                    and child.is_wanted
                    and child.line is not None
                    and child.restart_at is None
                    and not self._is_alive(child)
                    and self._is_ready(name)
                ):
                    self._start(name, child)
        if self._watcher is not None:
            self._watcher.tick()

    def watch(self) -> None:
        """Run :meth:`tick` on a thread of its own until :meth:`stop_all`."""
        self._stopping.clear()
        self._thread = threading.Thread(
            target=self._watch_forever, name="child_supervisor", daemon=True
        )
        self._thread.start()

    def stop_all(self) -> None:
        """Stop watching and end every child. Idempotent.

        A child that requires another is ended first; the rest are all
        asked at once.
        """
        self._stopping.set()
        with self._lock:
            for name in self._requirements:
                child = self._children.get(name)
                if child is not None:
                    child.is_wanted = False
                    child.restart_at = None
                    self._end(name)
            processes = []
            ended = []
            for name, child in self._children.items():
                child.is_wanted = False
                child.restart_at = None
                if child.process is not None:
                    ended.append(name)
                processes.append(child.process)
                child.process = None
            ending = [process for process in processes if _ask_to_end(process)]
            for process in ending:
                _wait_ended(process)
            for name in ended:
                self._tell_ended(name)
            for logger in self._loggers.values():
                for handler in list(logger.handlers):
                    handler.close()
                    logger.removeHandler(handler)
            self._loggers.clear()

    def _child(self, name: str) -> "_Child":
        """The record of one child, made on first use."""
        child = self._children.get(name)
        if child is None:
            child = _Child()
            self._children[name] = child
        return child

    def _tick_one(self, name: str, child: "_Child", now: float) -> None:
        """Look at one child once."""
        if child.process is not None:
            status = child.process.poll()
            if status is None:
                if now - child.started_at >= SYSTEM_CHILD_STABLE_S:
                    child.wait_s = SYSTEM_CHILD_RESTART_MIN_S
                return
            child.process = None
            self._end_dependents(name)
            self._tell_ended(name)
            if not child.is_wanted:
                return
            if now - child.started_at >= SYSTEM_CHILD_STABLE_S:
                child.wait_s = SYSTEM_CHILD_RESTART_MIN_S
            child.restart_at = now + child.wait_s
            self._log(f"{name} ended with {status}; starting it in {child.wait_s} s")
            child.wait_s = min(child.wait_s * 2, SYSTEM_CHILD_RESTART_MAX_S)
            return
        if child.is_wanted and child.restart_at is not None and now >= child.restart_at:
            if not self._is_ready(name):
                return
            child.restart_at = None
            self._start(name, child)

    def _watch_forever(self) -> None:
        """Tick until stopped; a tick that fails is logged and the watch goes on."""
        while not self._stopping.wait(SYSTEM_CHILD_TICK_S):
            try:
                self.tick()
            except (OSError, ValueError, RuntimeError) as error:
                self._log(f"the children could not be watched: {error}")

    def _start(self, name: str, child: "_Child") -> None:
        """Start one child; a failed start waits like an end."""
        line = child.line
        env = dict(self._base_env if self._base_env is not None else os.environ)
        env.update({str(key): str(value) for key, value in line.env.items()})
        try:
            process = self._start_process(
                [str(word) for word in line.argv],
                env,
                line.cwd or None,
                self._creation_flags,
            )
        except OSError as error:
            self._log(f"{name} could not start: {error}")
            child.restart_at = self._clock() + child.wait_s
            child.wait_s = min(child.wait_s * 2, SYSTEM_CHILD_RESTART_MAX_S)
            return
        child.process = process
        child.started_at = self._clock()
        self._log(f"{name} started as {getattr(process, 'pid', '?')}")
        if self._on_started is not None:
            try:
                self._on_started(process)
            except OSError as error:
                self._log(f"{name} could not be tied to the service: {error}")
        stream = getattr(process, "stdout", None)
        if stream is not None:
            threading.Thread(
                target=_pump,
                args=(stream, self._logger(line.log_name or name)),
                name=f"{name}_output",
                daemon=True,
            ).start()

    def _logger(self, log_name: str) -> logging.Logger:
        """The logger writing plain lines to one rotated file, made once."""
        logger = self._loggers.get(log_name)
        if logger is not None:
            return logger
        self._log_dir.mkdir(parents=True, exist_ok=True)
        logger = logging.Logger(f"neutrino_hub.child.{log_name}", logging.INFO)
        handler = logging.handlers.RotatingFileHandler(
            self._log_dir / f"{log_name}{SYSTEM_CHILD_LOG_SUFFIX}",
            maxBytes=SYSTEM_CHILD_LOG_MAX_BYTES,
            backupCount=SYSTEM_CHILD_LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        self._loggers[log_name] = logger
        return logger

    def _is_alive(self, child: "_Child") -> bool:
        """Whether the child's process has not ended."""
        return child.process is not None and child.process.poll() is None

    def _is_ready(self, name: str) -> bool:
        """Whether the child this one requires runs, or it requires none."""
        required = self._requirements.get(name)
        if required is None:
            return True
        child = self._children.get(required)
        return child is not None and self._is_alive(child)

    def _end(self, name: str) -> None:
        """End one child's process, the children requiring it first.

        Each is asked first and killed when it does not end; a child that
        requires this one stays wanted and starts again once it runs.
        """
        self._end_dependents(name)
        child = self._children.get(name)
        if child is None or child.process is None:
            return
        process = child.process
        child.process = None
        if _ask_to_end(process):
            _wait_ended(process)
        self._tell_ended(name)

    def _end_dependents(self, name: str) -> None:
        """End every child that requires this one, keeping it wanted."""
        for dependent, required in self._requirements.items():
            if required == name:
                self._end(dependent)

    def _tell_ended(self, name: str) -> None:
        """Tell the watcher one child's process ended; a failure is logged."""
        if self._watcher is None:
            return
        try:
            self._watcher.child_ended(name)
        except (OSError, ValueError, RuntimeError) as error:
            self._log(f"the end of {name} could not be followed: {error}")


def _ask_to_end(process) -> bool:
    """Ask a process that runs to end; whether it was asked."""
    if process is None or process.poll() is not None:
        return False
    try:
        process.terminate()
    except OSError:
        return False
    return True


def _wait_ended(process) -> None:
    """Wait for an asked process to end, and kill it when it does not in time."""
    try:
        process.wait(timeout=SYSTEM_CHILD_STOP_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=SYSTEM_CHILD_STOP_TIMEOUT_S)
    except OSError:
        pass


def _pump(stream, logger: logging.Logger) -> None:
    """Write each line a child prints to its log, until it ends."""
    try:
        for raw in iter(stream.readline, b""):
            line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
            if not line:
                break
            logger.info(line.rstrip("\r\n"))
    except (OSError, ValueError):
        return


@dataclass
class _Child:
    """What the supervisor knows of one child."""

    line: "ChildStartLine | None" = None
    process: object = None
    is_wanted: bool = False
    started_at: float = 0.0
    restart_at: "float | None" = None
    wait_s: float = SYSTEM_CHILD_RESTART_MIN_S
