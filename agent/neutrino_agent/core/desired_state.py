"""The hub's state for this machine, kept and made true.

The hub sends one state per device: ``{hash, modules, desktop}``, with one
entry per module it has a say about, ``{want, config, install, uninstall}``,
and the seat password this machine's desktop answers with. A copy lands
here on every ``state`` frame, root-only on disk, and the applier makes
each mentioned module's actual state equal its ``want``, in one fixed
module order:

| ``want`` | The applier ensures |
| --- | --- |
| ``absent`` | the software is uninstalled by its recipe, the configuration the hub wrote and the configured mark are gone; the data stays |
| ``installed`` | the software is there; nothing is configured, nothing started |
| ``stopped`` | the software is there, the configuration applied, the unit stopped |
| ``running`` | the software is there, the configuration applied, the unit up |

A module the state does not mention is left as it is. An install's bytes
come down a ``package {module}`` stream the applier opens, and an
install's or an uninstall's output goes up a ``log {module}`` stream.

The applied hash is what the hub compares against: it moves to the state's
hash only once every mentioned module applied. A state whose apply failed
is reported with its code under the old hash, and is tried again only when
a state with another hash arrives; the one exception is a failure the
socket caused, which the next state frame tries again.

Not pure: writes the state file, drives the module runners and opens
streams.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import json
import os
import tempfile
import threading

from neutrino_agent.constants import (
    AGENT_DESIRED_STATE_PATH,
    AGENT_WANT_ABSENT,
    AGENT_WANT_INSTALLED,
    AGENT_WANT_RUNNING,
    AGENT_WANT_STOPPED,
)
from neutrino_agent.exceptions import (
    GatewayUnreachable,
    ModuleApplyError,
    PlatformUnsupportedError,
)
from neutrino_agent.streams import STREAM_KIND_LOG, STREAM_KIND_PACKAGE
from neutrino_agent.streams.log import LogStream
from neutrino_agent.streams.package import PackageStream

# The order modules apply in: storage first, then what serves from it.
APPLY_ORDER = ("zfs", "samba", "gitea", "podman")

# The wants under which the software must be there.
PRESENT_WANTS = (AGENT_WANT_INSTALLED, AGENT_WANT_STOPPED, AGENT_WANT_RUNNING)
# The wants that apply the hub's configuration.
CONFIGURING_WANTS = (AGENT_WANT_RUNNING, AGENT_WANT_STOPPED)

# The one failure the next state frame tries again: the socket went away
# under the operation, and nothing about the machine made it fail.
RETRIED_CODE = "hub_unreachable"


class DesiredStateStore:
    """The last state taken from the hub, on disk."""

    def __init__(self, *, path: str = AGENT_DESIRED_STATE_PATH):
        """
        Args:
            path: Where the file lives.
        """
        self._path = path

    def read(self) -> dict:
        """The stored state.

        Returns:
            The document, ``{hash, modules, desktop}``; empty when nothing
            was ever taken or the file cannot be read.
        """
        try:
            with open(self._path, "r", encoding="utf-8") as stream:
                held = json.load(stream)
        except (OSError, ValueError):
            return {}
        return dict(held) if isinstance(held, dict) else {}

    def write(self, document: dict) -> None:
        """Keep one state, root-only, whole or not at all.

        Args:
            document: The state as the hub sent it.

        Raises:
            OSError: When the file cannot be written; the partial file is
                removed first.
        """
        directory = os.path.dirname(self._path)
        os.makedirs(directory, mode=0o700, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=directory, prefix=".desired_")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(document, stream)
            os.chmod(temporary, 0o600)
            os.replace(temporary, self._path)
        except BaseException:
            if os.path.exists(temporary):
                os.unlink(temporary)
            raise


class DesiredStateApplier:
    """Takes states from the hub and makes the latest one true, in order."""

    def __init__(
        self,
        *,
        engine,
        runners: dict,
        store: DesiredStateStore,
        rdp=None,
        log=print,
        open_stream=None,
        package_dir: str = "",
    ):
        """
        Args:
            engine: The :class:`ModuleEngine`, which observes each module
                against the state, reports it, and moves its software.
            runners: Module name to its runner, for the modules this agent
                applies.
            store: Where the last taken state is kept.
            rdp: The :class:`RdpShareHost` the desktop section is handed
                to; None applies nothing of it.
            log: Callable used for progress messages.
            open_stream: Called with ``(kind, **args)`` to open a stream
                to the hub; returns its channel and raises
                :class:`GatewayUnreachable` with no socket. None opens
                nothing: an install that needs bytes then fails
                ``hub_unreachable``.
            package_dir: Where a package's bytes land until their digest
                is checked.
        """
        self._engine = engine
        self._runners = dict(runners)
        self._store = store
        self._rdp = rdp
        self._log = log
        self._open_stream = open_stream
        self._package_dir = package_dir
        self._lock = threading.Lock()
        self._idle = threading.Condition(self._lock)
        self._is_applying = False
        self._pending: "dict | None" = None
        self._applied_hash = ""
        self._tried_hash = ""
        self._state_error: "dict | None" = None
        self._wakeup = threading.Event()
        self._worker = threading.Thread(
            target=self._run, name="desired_state", daemon=True
        )
        self._worker.start()

    @property
    def applied_hash(self) -> str:
        """The hash of the last state every mentioned module applied."""
        with self._lock:
            return self._applied_hash

    @property
    def state_error(self) -> "dict | None":
        """Why the last state did not fully apply, as ``{"code", "params"}``."""
        with self._lock:
            return dict(self._state_error) if self._state_error else None

    def settle(self, timeout_s: float) -> bool:
        """Wait until no state is pending or mid-apply.

        A command that reads a module's configuration runs after the state
        it was asked against has taken, not beside it.

        Args:
            timeout_s: How long to wait.

        Returns:
            True when the applier is idle; False when the wait ran out.
        """
        with self._idle:
            return self._idle.wait_for(
                lambda: self._pending is None and not self._is_applying, timeout_s
            )

    def take(self, document: dict) -> None:
        """Keep one state from the hub and apply it when it is news.

        Args:
            document: The state, ``{hash, modules, desktop}``.
        """
        kept = dict(document)
        try:
            self._store.write(kept)
        except OSError as error:
            self._log(f"could not keep the desired state: {error}")
        with self._lock:
            self._pending = kept
        self._wakeup.set()

    def apply(self, document: dict) -> None:
        """Make one state true now, in the caller's thread.

        Each mentioned module with a runner is made to match its ``want``.
        A ``want`` outside the four is left alone, with a line in the log.

        Args:
            document: The state, ``{hash, modules, desktop}``.
        """
        state_hash = str(document.get("hash", "") or "")
        modules = document.get("modules")
        modules = {
            name: entry
            for name, entry in (modules if isinstance(modules, dict) else {}).items()
            if isinstance(entry, dict)
        }
        self._engine.take_state(modules)
        self._apply_desktop(document.get("desktop"))
        first_failure = None
        for name in APPLY_ORDER:
            runner = self._runners.get(name)
            wanted = modules.get(name)
            if runner is None or wanted is None:
                continue
            failure = self._reconcile_one(name, runner, wanted)
            self._engine.record_apply(
                name,
                failure["code"] if failure else "",
                failure["params"] if failure else {},
            )
            if failure and first_failure is None:
                first_failure = {"module": name, **failure}
        with self._lock:
            is_retried = first_failure is not None and (
                first_failure["code"] == RETRIED_CODE
            )
            self._tried_hash = "" if is_retried else state_hash
            if first_failure is None:
                self._applied_hash = state_hash
                self._state_error = None
            else:
                self._state_error = {
                    "code": first_failure["code"],
                    "params": {
                        "module": first_failure["module"],
                        **first_failure["params"],
                    },
                }
        self._engine.refresh_now()

    def _apply_desktop(self, wanted) -> None:
        """Give the desktop host the seat password the hub holds.

        The password is set into RustDesk only when it is not the one this
        machine already set. A refusal is logged rather than raised: it says
        nothing about whether the modules applied.

        Args:
            wanted: The state's ``desktop`` section, or anything else when
                it carries none.
        """
        if self._rdp is None or not isinstance(wanted, dict):
            return
        refusal = self._rdp.apply_seat_password(str(wanted.get("seat_password", "")))
        if refusal:
            self._log(f"rdp: {refusal['code']}")

    def _reconcile_one(self, name: str, runner, wanted: dict) -> "dict | None":
        """Make one module's actual state equal its ``want``.

        Args:
            name: The module name.
            runner: Its runner.
            wanted: The state's entry for it.

        Returns:
            None when it took, ``{"code", "params"}`` when it did not.
        """
        want = str(wanted.get("want", "") or "")
        if want == AGENT_WANT_ABSENT:
            if self._engine.is_installed(name):
                return self._package_operation(name, self._uninstall)
            self._engine.clear_configured(name)
            return None
        if want not in PRESENT_WANTS:
            self._log(f"{name}: want {want!r} is not one this agent knows")
            return None
        if not self._engine.is_installed(name):
            failure = self._package_operation(name, self._install)
            if failure:
                return failure
        if want not in CONFIGURING_WANTS:
            return None
        failure = self._apply_one(name, runner, want, wanted.get("config"))
        if failure is None:
            self._engine.mark_configured(name)
        return failure

    def _install(self, name: str, on_line) -> dict:
        return self._engine.install(name, receive=self._receive, on_line=on_line)

    def _uninstall(self, name: str, on_line) -> dict:
        return self._engine.uninstall(name, on_line=on_line)

    def _package_operation(self, name: str, operation) -> "dict | None":
        """Run one package operation with its output up a log stream.

        Args:
            name: The module name.
            operation: Called with ``(name, on_line)``; returns empty or
                ``{"code", "params"}``.

        Returns:
            None when it took, ``{"code", "params"}`` when it did not.
        """
        log = self._open_log(name)
        refusal = operation(name, log.send if log is not None else None)
        if log is not None:
            state = str((self._engine.report().get(name) or {}).get("state", ""))
            log.close(
                state,
                str(refusal.get("code", "") or "") if refusal else "",
                dict(refusal.get("params") or {}) if refusal else {},
            )
        if refusal:
            self._log(f"{name}: {refusal['code']}")
            return {"code": refusal["code"], "params": dict(refusal.get("params", {}))}
        return None

    def _open_log(self, name: str) -> "LogStream | None":
        """A ``log {module}`` stream to the hub, or None with no socket."""
        if self._open_stream is None:
            return None
        try:
            return LogStream(self._open_stream(STREAM_KIND_LOG, module=name))
        except GatewayUnreachable:
            return None

    def _receive(self, name: str) -> dict:
        """One module's package, down a ``package {module}`` stream.

        Args:
            name: The module name.

        Returns:
            ``{"path"}`` naming the checked file, or ``{"code", "params"}``.
        """
        if self._open_stream is None:
            return {"code": RETRIED_CODE, "params": {}}
        try:
            channel = self._open_stream(STREAM_KIND_PACKAGE, module=name)
        except GatewayUnreachable:
            return {"code": RETRIED_CODE, "params": {}}
        return PackageStream(channel, directory=self._package_dir).receive()

    def _apply_one(self, name: str, runner, want: str, config) -> "dict | None":
        """Apply one installed module's configuration and settle its unit.

        Args:
            name: The module name.
            runner: Its runner.
            want: ``running`` or ``stopped``.
            config: The configuration the state carries for it.

        Returns:
            None when it took, ``{"code", "params"}`` when it did not.
        """
        try:
            runner.apply(dict(config) if isinstance(config, dict) else {})
            if want == AGENT_WANT_STOPPED:
                runner.stop()
            self._log(f"{name}: {want}")
        except ModuleApplyError as error:
            self._log(f"{name}: {error.code}")
            return {"code": error.code, "params": dict(error.params)}
        except PlatformUnsupportedError:
            return {"code": "unsupported_platform", "params": {}}
        except Exception as error:  # noqa: BLE001 - reported, never raised
            self._log(f"{name}: {error}")
            return {"code": "apply_failed", "params": {"detail": str(error)[:200]}}
        return None

    def _run(self) -> None:
        while True:
            self._wakeup.wait()
            self._wakeup.clear()
            while True:
                with self._lock:
                    pending = self._pending
                    self._pending = None
                    tried = self._tried_hash
                if pending is None:
                    with self._idle:
                        self._idle.notify_all()
                    break
                state_hash = str(pending.get("hash", "") or "")
                if state_hash and state_hash == tried:
                    with self._idle:
                        self._idle.notify_all()
                    continue
                with self._idle:
                    self._is_applying = True
                try:
                    self.apply(pending)
                except Exception as error:  # noqa: BLE001 - the loop must survive
                    self._log(f"applying the desired state crashed: {error}")
                finally:
                    with self._idle:
                        self._is_applying = False
                        self._idle.notify_all()
