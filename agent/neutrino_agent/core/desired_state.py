"""The hub's desired state for this machine, kept and made true.

The hub holds one desired state per device: which modules are enabled,
each module's configuration, the catalog resolved for this platform, and
the seat password this machine's desktop answers with. A copy lands here on
every ``state`` frame, root-only on disk, and the applier makes it true in
one fixed module order. An enabled module that is installed is applied, an
installed module that is disabled is stopped, and a module that is not
installed is left alone until an order installs it.

The applied hash is what the hub compares against: it moves to the state's
hash only once every enabled module applied, so a failed apply keeps asking
for the same state until it takes.

Not pure: writes the desired-state file and drives the module runners.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import json
import os
import tempfile
import threading

from neutrino_agent.constants import AGENT_DESIRED_STATE_PATH
from neutrino_agent.exceptions import ModuleApplyError, PlatformUnsupportedError

# The order modules apply in: storage first, then what serves from it.
APPLY_ORDER = ("zfs", "samba", "gitea", "podman")


class DesiredStateStore:
    """The last desired state taken from the hub, on disk."""

    def __init__(self, *, path: str = AGENT_DESIRED_STATE_PATH):
        """
        Args:
            path: Where the file lives.
        """
        self._path = path

    def read(self) -> "tuple[str, dict]":
        """The stored state.

        Returns:
            ``(hash, desired)``, both empty when nothing was ever taken or
            the file cannot be read.
        """
        try:
            with open(self._path, "r", encoding="utf-8") as stream:
                held = json.load(stream)
        except (OSError, ValueError):
            return "", {}
        if not isinstance(held, dict):
            return "", {}
        desired = held.get("desired")
        return str(held.get("hash", "") or ""), (
            dict(desired) if isinstance(desired, dict) else {}
        )

    def write(self, state_hash: str, desired: dict) -> None:
        """Keep one state, root-only, whole or not at all.

        Args:
            state_hash: The hub's hash of the state.
            desired: The state itself.

        Raises:
            OSError: When the file cannot be written; the partial file is
                removed first.
        """
        directory = os.path.dirname(self._path)
        os.makedirs(directory, mode=0o700, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=directory, prefix=".desired_")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump({"hash": state_hash, "desired": desired}, stream)
            os.chmod(temporary, 0o600)
            os.replace(temporary, self._path)
        except BaseException:
            if os.path.exists(temporary):
                os.unlink(temporary)
            raise


class DesiredStateApplier:
    """Takes states from the hub and makes the latest one true, in order."""

    def __init__(
        self, *, engine, runners: dict, store: DesiredStateStore, rdp=None, log=print
    ):
        """
        Args:
            engine: The :class:`ModuleEngine`, which holds the catalog and
                reports each module.
            runners: Module name to its runner, for the modules this agent
                applies.
            store: Where the last taken state is kept.
            rdp: The :class:`RdpShareHost` the desktop half of the state is
                handed to; None applies nothing of it.
            log: Callable used for progress messages.
        """
        self._engine = engine
        self._runners = dict(runners)
        self._store = store
        self._rdp = rdp
        self._log = log
        self._lock = threading.Lock()
        self._idle = threading.Condition(self._lock)
        self._is_applying = False
        self._pending: "tuple | None" = None
        self._applied_hash = ""
        self._state_error: "dict | None" = None
        self._wakeup = threading.Event()
        self._worker = threading.Thread(
            target=self._run, name="desired_state", daemon=True
        )
        self._worker.start()

    @property
    def applied_hash(self) -> str:
        """The hash of the last state every enabled module applied."""
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

    def take(self, state_hash: str, desired: dict) -> None:
        """Keep one state from the hub and apply it when it is news.

        Args:
            state_hash: The hub's hash of the state.
            desired: The state itself.
        """
        try:
            self._store.write(state_hash, desired)
        except OSError as error:
            self._log(f"could not keep the desired state: {error}")
        with self._lock:
            self._pending = (state_hash, dict(desired))
        self._wakeup.set()

    def apply_again(self) -> None:
        """Apply the last state taken once more, whatever its hash.

        Run after an order changed what is installed: a module that was
        skipped for being absent is there now and owes its configuration.
        """
        with self._lock:
            if self._pending is None:
                held_hash, held = self._store.read()
                if not held_hash:
                    return
                self._pending = (held_hash, held)
            self._applied_hash = ""
        self._wakeup.set()

    def apply(self, state_hash: str, desired: dict) -> None:
        """Make one state true now, in the caller's thread.

        Args:
            state_hash: The hub's hash of the state.
            desired: The state itself.
        """
        catalog = desired.get("catalog")
        self._engine.update(
            catalog=dict(catalog) if isinstance(catalog, dict) else {"modules": {}},
            catalog_hash=state_hash,
        )
        modules = desired.get("modules")
        modules = modules if isinstance(modules, dict) else {}
        self._apply_rdp(desired.get("rdp"))
        first_failure = None
        for name in APPLY_ORDER:
            runner = self._runners.get(name)
            wanted = modules.get(name)
            if runner is None or not isinstance(wanted, dict):
                continue
            resolved = self._engine.resolved(name)
            if resolved is None or not self._is_installed(runner, resolved):
                self._engine.record_apply(name, "", {})
                continue
            failure = self._apply_one(name, runner, wanted)
            self._engine.record_apply(
                name,
                failure["code"] if failure else "",
                failure["params"] if failure else {},
            )
            if failure and first_failure is None:
                first_failure = {"module": name, **failure}
        with self._lock:
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

    def _apply_rdp(self, wanted) -> None:
        """Give the desktop host the seat password the hub holds.

        The password is set into RustDesk only when it is not the one this
        machine already set. A refusal is logged rather than raised: it says
        nothing about whether the modules applied.

        Args:
            wanted: The state's ``rdp`` block, or anything else when it
                carries none.
        """
        if self._rdp is None or not isinstance(wanted, dict):
            return
        refusal = self._rdp.apply_seat_password(str(wanted.get("seat_password", "")))
        if refusal:
            self._log(f"rdp: {refusal['code']}")

    def _apply_one(self, name: str, runner, wanted: dict) -> "dict | None":
        """Apply or stop one installed module.

        Returns:
            None when it took, ``{"code", "params"}`` when it did not.
        """
        try:
            if wanted.get("is_enabled"):
                config = wanted.get("config")
                runner.apply(dict(config) if isinstance(config, dict) else {})
                self._log(f"{name}: applied")
            else:
                runner.stop()
                self._log(f"{name}: stopped")
        except ModuleApplyError as error:
            self._log(f"{name}: {error.code}")
            return {"code": error.code, "params": dict(error.params)}
        except PlatformUnsupportedError:
            return {"code": "unsupported_platform", "params": {}}
        except Exception as error:  # noqa: BLE001 - reported, never raised
            self._log(f"{name}: {error}")
            return {"code": "apply_failed", "params": {"detail": str(error)[:200]}}
        return None

    @staticmethod
    def _is_installed(runner, resolved: dict) -> bool:
        try:
            return bool(runner.verify(resolved))
        except Exception:  # noqa: BLE001 - an unreadable module is not installed
            return False

    def _run(self) -> None:
        while True:
            self._wakeup.wait()
            self._wakeup.clear()
            while True:
                with self._lock:
                    pending = self._pending
                    self._pending = None
                    applied = self._applied_hash
                if pending is None:
                    with self._idle:
                        self._idle.notify_all()
                    break
                state_hash, desired = pending
                if state_hash and state_hash == applied:
                    with self._idle:
                        self._idle.notify_all()
                    continue
                with self._idle:
                    self._is_applying = True
                try:
                    self.apply(state_hash, desired)
                except Exception as error:  # noqa: BLE001 - the loop must survive
                    self._log(f"applying the desired state crashed: {error}")
                finally:
                    with self._idle:
                        self._is_applying = False
                        self._idle.notify_all()
