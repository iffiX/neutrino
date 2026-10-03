"""Controlling the daemons the hub runs, by the names the panel uses.

One method set for every system: on Linux each daemon is a systemd unit
(:class:`neutrino_hub.system.systemd_ctl.SystemdServiceController`); on macOS
and Windows each is a child of the hub's one service
(:class:`SupervisedProcessController`). The runtime hands one out from
:func:`neutrino_hub.platforms.detect.process_controller`.
"""

import collections
import json
import os
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

from neutrino_hub.platforms.constants import PLATFORM_SERVICE_RUNNING
from neutrino_hub.system.child_supervisor import ChildStartLine
from neutrino_hub.system.constants import (
    SYSTEM_CHILD_LOG_SUFFIX,
    SYSTEM_JOURNAL_LINES,
    SYSTEM_RESTART_DELAY_S,
    SYSTEM_RESTART_EXIT_STATUS,
    SYSTEM_SERVICES_RECONCILE_S,
    SYSTEM_SUPERVISED_NAMES,
    SYSTEM_SUPERVISED_WEB,
)
from neutrino_hub.utils.json_file import write_generated

ALLOWED_ACTIONS = ("start", "stop", "restart", "enable", "disable")


@dataclass
class ServiceStatus:
    """State of one managed daemon.

    Attributes:
        name: Panel-facing name, for example ``xray``.
        unit: The systemd unit behind it, or the name of the child.
        is_installed: Whether the system knows the daemon at all.
        is_active: Whether it is running now.
        is_enabled: Whether it starts with the machine.
    """

    name: str
    unit: str
    is_installed: bool
    is_active: bool
    is_enabled: bool


class ProcessController:
    """The method set every system's controller answers."""

    def status(self, name: str) -> ServiceStatus:
        """Read one daemon's state.

        Args:
            name: Panel-facing service name.

        Returns:
            Its current state.

        Raises:
            KeyError: If the name is not a managed daemon.
        """
        raise NotImplementedError

    def status_all(self) -> list:
        """Read every managed daemon's state.

        Returns:
            One entry per managed daemon, in the declared order.
        """
        raise NotImplementedError

    def control(self, name: str, action: str) -> None:
        """Start, stop, restart, enable, or disable one daemon.

        Args:
            name: Panel-facing service name.
            action: One of :data:`ALLOWED_ACTIONS`.

        Raises:
            KeyError: If the name is not a managed daemon.
            ValueError: If the action is not allowed.
            subprocess.CalledProcessError: If the system refuses.
        """
        raise NotImplementedError

    def journal(self, name: str, *, line_count: int = SYSTEM_JOURNAL_LINES) -> str:
        """Read the tail of one daemon's log.

        Args:
            name: Panel-facing service name.
            line_count: How many lines to return.

        Returns:
            The log text.

        Raises:
            KeyError: If the name is not a managed daemon.
        """
        raise NotImplementedError

    def reload(self) -> None:
        """Read the daemons' definitions again after one changed.

        Raises:
            subprocess.CalledProcessError: If the system refuses.
        """
        raise NotImplementedError

    def set_start_line(self, name: str, argv, env: dict, cwd) -> None:
        """Say how one daemon starts from now on.

        Args:
            name: Panel-facing service name.
            argv: The argument vector, the program first; None returns the
                daemon to its own start line.
            env: Variables its environment adds.
            cwd: The directory it starts in; None keeps the default.

        Raises:
            KeyError: If the name is not a managed daemon.
            OSError: If the start line cannot be written.
        """
        raise NotImplementedError

    def is_active(self, name: str) -> bool:
        """Whether one daemon runs now.

        Args:
            name: Panel-facing service name.

        Returns:
            True while it runs.

        Raises:
            KeyError: If the name is not a managed daemon.
        """
        return self.status(name).is_active

    def is_enabled(self, name: str) -> bool:
        """Whether one daemon starts with the machine.

        Args:
            name: Panel-facing service name.

        Returns:
            True when it does.

        Raises:
            KeyError: If the name is not a managed daemon.
        """
        return self.status(name).is_enabled

    def start(self, name: str) -> None:
        """Start one daemon.

        Args:
            name: Panel-facing service name.

        Raises:
            KeyError: If the name is not a managed daemon.
            subprocess.CalledProcessError: If the system refuses.
        """
        self.control(name, "start")

    def stop(self, name: str) -> None:
        """Stop one daemon.

        Args:
            name: Panel-facing service name.

        Raises:
            KeyError: If the name is not a managed daemon.
            subprocess.CalledProcessError: If the system refuses.
        """
        self.control(name, "stop")

    def restart(self, name: str) -> None:
        """Restart one daemon.

        Args:
            name: Panel-facing service name.

        Raises:
            KeyError: If the name is not a managed daemon.
            subprocess.CalledProcessError: If the system refuses.
        """
        self.control(name, "restart")

    def enable(self, name: str) -> None:
        """Have one daemon start with the machine.

        Args:
            name: Panel-facing service name.

        Raises:
            KeyError: If the name is not a managed daemon.
            subprocess.CalledProcessError: If the system refuses.
        """
        self.control(name, "enable")

    def disable(self, name: str) -> None:
        """Stop one daemon starting with the machine.

        Args:
            name: Panel-facing service name.

        Raises:
            KeyError: If the name is not a managed daemon.
            subprocess.CalledProcessError: If the system refuses.
        """
        self.control(name, "disable")


def read_services_state(path: Path) -> dict:
    """What ``services.json`` says: the enabled children and their start lines.

    Args:
        path: The file.

    Returns:
        ``{"enabled": [...], "start_lines": {name: {...}}}``; both empty when
        the file is not there or cannot be read.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    enabled = data.get("enabled")
    lines = data.get("start_lines")
    return {
        "enabled": [str(name) for name in enabled] if isinstance(enabled, list) else [],
        "start_lines": dict(lines) if isinstance(lines, dict) else {},
    }


class SupervisedProcessController(ProcessController):
    """The children of the hub's one service on macOS and Windows.

    Inside the service, after :meth:`supervise`, each verb acts on the
    child, and ``services.json`` is read again every
    ``SYSTEM_SERVICES_RECONCILE_S``: a child another process enabled is
    started, one it disabled is stopped. In any other process, such as a
    ``nhub`` command, ``start``, ``restart`` and ``enable`` of a child write
    it into ``services.json`` and leave the starting to the service; only a
    ``restart`` while the service runs restarts the service.
    """

    def __init__(
        self,
        *,
        supervisor,
        service,
        state_path: Path,
        log_dir: Path,
        exit=None,
        restart_delay_s: float = SYSTEM_RESTART_DELAY_S,
        reconcile_s: float = SYSTEM_SERVICES_RECONCILE_S,
    ):
        """
        Args:
            supervisor: The :class:`ChildProcessSupervisor` of this process.
            service: The platform, whose ``service_state``,
                ``start_service``, ``stop_service`` and ``restart_service``
                drive the one service.
            state_path: The ``services.json`` file.
            log_dir: Where each child's ``<name>.log`` is.
            exit: Ends the process with a status; None is ``os._exit``.
            restart_delay_s: How long a panel restart waits before the
                service exits.
            reconcile_s: How often the service reads ``services.json``
                again.
        """
        self._supervisor = supervisor
        self._service = service
        self._state_path = Path(state_path)
        self._log_dir = Path(log_dir)
        self._exit = exit if exit is not None else os._exit
        self._restart_delay_s = restart_delay_s
        self._reconcile_s = reconcile_s
        self._lock = threading.RLock()
        self._is_supervising = False
        self._own_start_lines: set = set()
        self._seen_enabled: set = set()
        self._stopping = threading.Event()

    @property
    def is_supervising(self) -> bool:
        """Whether this process is the service running the children."""
        return self._is_supervising

    def supervise(self, start_lines: dict) -> None:
        """Become the service: hold the start lines and run every enabled child.

        Args:
            start_lines: Name to :class:`ChildStartLine` for the children
                whose start line the service knows itself; a line kept in
                ``services.json`` is used for the others.
        """
        with self._lock:
            self._is_supervising = True
            self._own_start_lines = set(start_lines)
            state = read_services_state(self._state_path)
            self._hold_kept_start_lines(state)
            for name, line in start_lines.items():
                self._supervisor.set_start_line(name, line)
            self._seen_enabled = self._enabled_children(state)
            for name in sorted(self._seen_enabled):
                if self._supervisor.start_line(name) is not None:
                    self._supervisor.start(name)
            self._supervisor.watch()
        self._stopping.clear()
        threading.Thread(
            target=self._reconcile_forever, name="services_json", daemon=True
        ).start()

    def reconcile(self) -> None:
        """Make the children what ``services.json`` says now.

        A start line kept there is held; a child that came into the enabled
        list since the last read is started, one that left it is stopped.
        A child started or stopped in this process without a change to the
        list is left as it is.
        """
        with self._lock:
            state = read_services_state(self._state_path)
            self._hold_kept_start_lines(state)
            enabled = self._enabled_children(state)
            for name in sorted(enabled - self._seen_enabled):
                if self._supervisor.start_line(name) is not None:
                    self._supervisor.start(name)
            for name in sorted(self._seen_enabled - enabled):
                self._supervisor.stop(name)
            self._seen_enabled = enabled

    def shutdown(self) -> None:
        """End every child; the service is stopping."""
        self._stopping.set()
        self._supervisor.stop_all()

    def status(self, name: str) -> ServiceStatus:
        """Read one child's state.

        Args:
            name: Panel-facing service name.

        Returns:
            Its current state; ``web`` is the service itself.

        Raises:
            KeyError: If the name is not one the service runs.
        """
        self._check(name)
        if name == SYSTEM_SUPERVISED_WEB:
            is_active = self._is_supervising or self._is_service_running()
            return ServiceStatus(name, name, True, is_active, True)
        enabled = read_services_state(self._state_path)["enabled"]
        is_enabled = name in enabled
        if self._is_supervising:
            is_installed = self._supervisor.start_line(name) is not None
            is_active = self._supervisor.is_running(name)
        else:
            is_installed = is_enabled
            is_active = is_enabled and self._is_service_running()
        return ServiceStatus(name, name, is_installed, is_active, is_enabled)

    def status_all(self) -> list:
        """Read every child's state.

        Returns:
            One entry per name the service runs, in the declared order.
        """
        return [self.status(name) for name in SYSTEM_SUPERVISED_NAMES]

    def control(self, name: str, action: str) -> None:
        """Start, stop, restart, enable, or disable one child.

        Args:
            name: Panel-facing service name.
            action: One of :data:`ALLOWED_ACTIONS`.

        Raises:
            KeyError: If the name is not one the service runs, or a child
                is started that has no start line.
            ValueError: If the action is not allowed.
            RuntimeError: If one child is stopped from outside the service.
            subprocess.CalledProcessError: If the service manager refuses.
        """
        if action not in ALLOWED_ACTIONS:
            raise ValueError(
                f"unsupported action {action!r}; "
                f"expected one of {', '.join(ALLOWED_ACTIONS)}"
            )
        self._check(name)
        with self._lock:
            if action == "enable":
                self._write_enabled(name, is_enabled=True)
                if self._is_supervising and name != SYSTEM_SUPERVISED_WEB:
                    self._supervisor.start(name)
            elif action == "disable":
                self._write_enabled(name, is_enabled=False)
                if self._is_supervising and name != SYSTEM_SUPERVISED_WEB:
                    self._supervisor.stop(name)
            elif name == SYSTEM_SUPERVISED_WEB:
                self._control_service(action)
            elif self._is_supervising:
                getattr(self._supervisor, action)(name)
            elif action == "restart" and self._is_service_running():
                self._service.restart_service()
            elif action in ("start", "restart"):
                self._write_enabled(name, is_enabled=True)
            else:
                raise RuntimeError(
                    f"{name} runs inside the hub's service; nhub stop stops it"
                )

    def journal(self, name: str, *, line_count: int = SYSTEM_JOURNAL_LINES) -> str:
        """Read the tail of one child's log file.

        Args:
            name: Panel-facing service name.
            line_count: How many lines to return.

        Returns:
            The last lines of ``<log>/<name>.log``; empty when there is none.

        Raises:
            KeyError: If the name is not one the service runs.
        """
        self._check(name)
        path = self._log_dir / f"{name}{SYSTEM_CHILD_LOG_SUFFIX}"
        try:
            with open(path, encoding="utf-8", errors="replace") as stream:
                tail = collections.deque(stream, maxlen=max(0, line_count))
        except OSError:
            return ""
        return "".join(tail)

    def reload(self) -> None:
        """Nothing to read again: the service holds every start line itself."""

    def set_start_line(self, name: str, argv, env: dict, cwd) -> None:
        """Hold how one child starts, and keep it in ``services.json``.

        Args:
            name: Panel-facing service name.
            argv: The argument vector, the program first; None forgets it.
            env: Variables its environment adds.
            cwd: The directory it starts in; None keeps the service's.

        Raises:
            KeyError: If the name is not one the service runs.
            OSError: If ``services.json`` cannot be written.
        """
        self._check(name)
        line = None
        if argv is not None:
            line = ChildStartLine(
                argv=[str(word) for word in argv],
                env=dict(env or {}),
                cwd=str(cwd or ""),
            )
        with self._lock:
            state = read_services_state(self._state_path)
            if line is None:
                state["start_lines"].pop(name, None)
            else:
                state["start_lines"][name] = line.to_dict()
            self._write_state(state)
            self._supervisor.set_start_line(name, line)

    def _check(self, name: str) -> None:
        """Refuse a name the service does not run."""
        if name not in SYSTEM_SUPERVISED_NAMES:
            raise KeyError(
                f"{name!r} is not a managed service; "
                f"expected one of {', '.join(SYSTEM_SUPERVISED_NAMES)}"
            )

    def _hold_kept_start_lines(self, state: dict) -> None:
        """Hold the start lines ``services.json`` keeps for the other children."""
        for name in SYSTEM_SUPERVISED_NAMES:
            if name in self._own_start_lines or name == SYSTEM_SUPERVISED_WEB:
                continue
            data = state["start_lines"].get(name)
            try:
                line = ChildStartLine.from_dict(data) if data is not None else None
            except ValueError:
                continue
            if line != self._supervisor.start_line(name):
                self._supervisor.set_start_line(name, line)

    def _enabled_children(self, state: dict) -> set:
        """The children ``services.json`` enables, the panel left out."""
        return {
            name
            for name in state["enabled"]
            if name in SYSTEM_SUPERVISED_NAMES and name != SYSTEM_SUPERVISED_WEB
        }

    def _reconcile_forever(self) -> None:
        """Reconcile on the timer until the service stops; a failed pass is logged."""
        while not self._stopping.wait(self._reconcile_s):
            try:
                self.reconcile()
            except (OSError, ValueError, KeyError) as error:
                print(f"services.json could not be followed: {error}", file=sys.stderr)

    def _is_service_running(self) -> bool:
        """Whether the service manager says the one service runs."""
        return self._service.service_state() == PLATFORM_SERVICE_RUNNING

    def _control_service(self, action: str) -> None:
        """Act on the one service, which serves the panel."""
        if action == "stop":
            if self._is_supervising:
                self._exit_later(0)
                return
            self._service.stop_service()
            return
        if action == "restart" and self._is_supervising:
            self._exit_later(SYSTEM_RESTART_EXIT_STATUS)
            return
        if action == "restart" and self._is_service_running():
            self._service.restart_service()
            return
        if not self._is_service_running():
            self._service.start_service()

    def _exit_later(self, status: int) -> None:
        """End the service after the delay, its children first."""

        def end() -> None:
            self._supervisor.stop_all()
            self._exit(status)

        timer = threading.Timer(self._restart_delay_s, end)
        timer.daemon = True
        timer.start()

    def _write_enabled(self, name: str, *, is_enabled: bool) -> None:
        """Add one name to the enabled list in ``services.json``, or take it out."""
        state = read_services_state(self._state_path)
        enabled = [entry for entry in state["enabled"] if entry != name]
        if is_enabled:
            enabled.append(name)
        state["enabled"] = enabled
        self._write_state(state)

    def _write_state(self, state: dict) -> None:
        """Write ``services.json``, readable by root alone."""
        write_generated(
            self._state_path, json.dumps(state, indent=2) + "\n", mode=0o600
        )
