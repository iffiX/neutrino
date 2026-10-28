"""The hub's state for this machine, kept and made true.

The hub sends one state per device: ``{hash, modules, desktop}``, with one
entry per module it has a say about, ``{want, config, install}``, the
recipe ``install`` being ``{runner, method, params}``, and the seat password
this machine's desktop answers with. A copy lands
here on every ``state`` frame, root-only on disk, and the applier makes
each mentioned module's actual state equal its ``want``, in one fixed
module order:

| ``want`` | The applier ensures |
| --- | --- |
| ``absent`` | the software is uninstalled by its recipe, the configuration the hub wrote and the configured mark are gone; the data stays |
| ``installed`` | the software is there; nothing is configured, nothing started |
| ``stopped`` | the software is there, the configuration applied, the unit stopped |
| ``running`` | the software is there, the configuration applied, the unit up |

A module the state does not mention is left as it is. Each artifact an
install receives comes down a ``package {module, artifact, digest}`` stream
the applier opens, and an install's or an uninstall's output goes up a
``log {module}`` stream.

The applied hash is what the hub compares against: it moves to the state's
hash once no mentioned module's last step failed or waits. Each module's
entry, and the ``ai_tools`` section, is tried once: the hash of the entry
last tried is kept per section beside the state on disk, under the build of
the agent that tried it, so a change to one entry, or a retry mark on it,
runs that module's step alone, an agent that starts again tries nothing
again, and an agent of another build tries every entry once again. A
failure the socket caused keeps no hash, so the next state with that entry
tries it again. Each step's outcome replaces the module's kept failure:
``install_failed`` for an install, ``failed`` for any other step, nothing
for a step that took. A module whose last install failed is installed again
by its next attempt, and uninstalled by an ``absent`` whatever the check
finds. The marks hold for one install, one build and one binding: the
agent's removal, a join and a leave delete them, and another build reads
none of them. Modules apply one at a time; while one applies, each other
module the apply will reach whose ``want`` differs from its reported state
reads ``queued``. A
module whose apply waits on an install that still runs is no failure: the
state is applied again every recheck interval until the install has ended.

Not pure: writes the state file, drives the module runners and opens
streams.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading

from neutrino_agent import AGENT_BUILT_AT, AGENT_VERSION
from neutrino_agent.constants import (
    AGENT_CONTAINERS_MODULE,
    AGENT_DESIRED_STATE_PATH,
    AGENT_METHOD_CONTAINER,
    AGENT_MODULE_INSTALL_RECHECK_S,
    AGENT_MODULE_STATE_FAILED,
    AGENT_MODULE_STATE_INSTALL_FAILED,
    AGENT_PRESENT_WANTS,
    AGENT_WANT_ABSENT,
    AGENT_WANT_RUNNING,
    AGENT_WANT_STOPPED,
)
from neutrino_agent.exceptions import (
    GatewayUnreachable,
    ModuleApplyError,
    ModuleInstallPending,
    PlatformUnsupportedError,
)
from neutrino_agent.modules.remote_desktop.constants import REMOTE_DESKTOP_NAME
from neutrino_agent.streams import STREAM_KIND_LOG, STREAM_KIND_PACKAGE
from neutrino_agent.streams.log import LogStream
from neutrino_agent.streams.package import PackageStream

# The order modules apply in. A container module the list does not name
# applies right after Containers, whose Podman runs it.
APPLY_ORDER = (
    "samba",
    "terminal",
    "ssh_server",
    "gitea",
    "podman",
    "hermes_webui",
    "vscode",
    "code_server",
    "cloudcli",
    "codeg",
    "remote_desktop",
)

# The wants that apply the hub's configuration.
CONFIGURING_WANTS = (AGENT_WANT_RUNNING, AGENT_WANT_STOPPED)

# The one failure the next state frame tries again: the socket went away
# under the operation, and nothing about the machine made it fail.
RETRIED_CODE = "hub_unreachable"
# What an apply that waits on a running install answers inside this file;
# it is never reported.
PENDING_CODE = "install_pending"
# The file beside the state that keeps the hash last tried, per section.
TRIED_SUFFIX = ".tried"
# This agent's build, which the hashes last tried are kept under: its
# version and the time its package was built.
AGENT_BUILD = f"{AGENT_VERSION} {AGENT_BUILT_AT}".strip()
# The state's section for the machine's AI tools, tried like a module.
AI_TOOLS_SECTION = "ai_tools"
# The state's section of the source sets its recipes name.
SOURCE_SETS_SECTION = "source_sets"
# The module whose Podman runs every container module, applied again once a
# container module's install took.
CONTAINERS_MODULE = AGENT_CONTAINERS_MODULE


def apply_order(modules: dict, runners: dict) -> list:
    """The modules of one state that have a runner, in the order they apply.

    Args:
        modules: The state's modules section.
        runners: Module name to its runner.

    Returns:
        The names in ``APPLY_ORDER``; a container module the order does not
        name comes right after Containers, by name.
    """
    named = [name for name in APPLY_ORDER if name in modules and name in runners]
    extra = sorted(
        name
        for name in modules
        if name in runners
        and name not in APPLY_ORDER
        and _method_of(modules[name]) == AGENT_METHOD_CONTAINER
    )
    slot = APPLY_ORDER.index(CONTAINERS_MODULE) + 1
    at = len([name for name in named if APPLY_ORDER.index(name) < slot])
    return named[:at] + extra + named[at:]


def _method_of(entry: dict) -> str:
    """The install method a state entry's recipe names, empty for none."""
    recipe = entry.get("install") if isinstance(entry, dict) else None
    return (
        str((recipe or {}).get("method", "") or "") if isinstance(recipe, dict) else ""
    )


def _section_hash(section) -> str:
    """The SHA-256 of one section's canonical JSON form."""
    serialized = json.dumps(section, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class DesiredStateStore:
    """The last state taken from the hub, on disk."""

    def __init__(
        self, *, path: str = AGENT_DESIRED_STATE_PATH, build: str = AGENT_BUILD
    ):
        """
        Args:
            path: Where the file lives.
            build: The agent's build the hashes last tried are kept under.
        """
        self._path = path
        self._build = build

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

    def read_tried(self) -> dict:
        """The hash of the entry last tried, per section, by this build.

        Returns:
            Module name, or ``ai_tools``, to the hash; empty when none is
            kept, the file cannot be read, it holds another shape, or
            another build of the agent kept it.
        """
        try:
            with open(self._path + TRIED_SUFFIX, "r", encoding="utf-8") as stream:
                held = json.load(stream)
        except (OSError, ValueError):
            return {}
        if not isinstance(held, dict) or held.get("build") != self._build:
            return {}
        hashes = held.get("hashes")
        if not isinstance(hashes, dict):
            return {}
        return {
            str(name): value
            for name, value in hashes.items()
            if isinstance(value, str) and value
        }

    def clear_tried(self) -> None:
        """Delete every hash last tried, so the next state is applied whatever
        its hashes.

        Raises:
            OSError: When the file is there and cannot be deleted.
        """
        try:
            os.unlink(self._path + TRIED_SUFFIX)
        except FileNotFoundError:
            pass

    def write_tried(self, tried: dict) -> None:
        """Keep the hash of the entry last tried, per section, root-only,
        under this build.

        Args:
            tried: Module name, or ``ai_tools``, to the hash.

        Raises:
            OSError: When the file cannot be written.
        """
        directory = os.path.dirname(self._path)
        os.makedirs(directory, mode=0o700, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=directory, prefix=".tried_")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(
                    {"build": self._build, "hashes": dict(tried)},
                    stream,
                    sort_keys=True,
                )
            os.chmod(temporary, 0o600)
            os.replace(temporary, self._path + TRIED_SUFFIX)
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
        ai_tools=None,
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
            ai_tools: The :class:`AiToolsApplier` the state's ``ai_tools``
                section is handed to, after the modules; None applies
                nothing of it.
        """
        self._engine = engine
        self._runners = dict(runners)
        self._store = store
        self._rdp = rdp
        self._log = log
        self._open_stream = open_stream
        self._package_dir = package_dir
        self._ai_tools = ai_tools
        self._lock = threading.Lock()
        self._idle = threading.Condition(self._lock)
        self._is_applying = False
        self._pending: "dict | None" = None
        self._applied_hash = ""
        self._tried = store.read_tried()
        # Module name to its last step's ``{"code", "params"}`` in this
        # process; None when it took.
        self._outcomes: dict = {}
        self._state_error: "dict | None" = None
        # The state whose apply waits on a running install, applied again.
        self._rechecked: "dict | None" = None
        # Set when a container module's install took, so Containers is
        # applied again and renders its containers.
        self._is_containers_marked = False
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

    def forget_tried(self) -> None:
        """Forget every hash last tried, here and on disk: what each was tried
        against is gone."""
        with self._lock:
            self._tried = {}
        try:
            self._store.clear_tried()
        except OSError as error:
            self._log(f"could not forget the tried state: {error}")

    def reload_tried(self) -> None:
        """Read the hashes last tried from disk again, after another process
        changed the binding and, with it, the marks."""
        tried = self._store.read_tried()
        with self._lock:
            self._tried = tried

    def latest(self) -> dict:
        """The last state taken from the hub, as it was kept.

        Returns:
            The document, ``{hash, modules, desktop}``; empty when none was
            ever taken.
        """
        return self._store.read()

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

        Each mentioned module with a runner whose entry differs from the one
        last tried is made to match its ``want``, one at a time in
        ``APPLY_ORDER``, a container module the order does not name right
        after Containers. A ``want`` outside the four is left alone, with a
        line in the log. A container module whose install took marks
        Containers to be applied again, and the state is applied once more;
        a container module the state asks to be present while it is not
        installed reads ``installing`` from here until it reads its want.

        Args:
            document: The state, ``{hash, modules, desktop, source_sets}``.
        """
        state_hash = str(document.get("hash", "") or "")
        modules = document.get("modules")
        modules = {
            name: entry
            for name, entry in (modules if isinstance(modules, dict) else {}).items()
            if isinstance(entry, dict)
        }
        source_sets = document.get(SOURCE_SETS_SECTION)
        self._engine.take_state(
            modules, source_sets if isinstance(source_sets, dict) else {}
        )
        self._apply_desktop(document.get("desktop"))
        with self._lock:
            tried = dict(self._tried)
            self._is_containers_marked = False
        hashes = {
            name: _section_hash(
                [entry, document.get("desktop")]
                if name == REMOTE_DESKTOP_NAME
                else entry
            )
            for name, entry in modules.items()
        }
        runners = {**self._runners, **self._engine.container_runners()}
        order = apply_order(modules, runners)
        steps = [name for name in order if hashes[name] != tried.get(name)]
        self._engine.hold_installing(
            [name for name in steps if self._is_container_install(name, modules[name])]
        )
        reported = self._engine.report()
        waiting = [
            name
            for name in steps
            if str(modules[name].get("want", "") or "")
            != str((reported.get(name) or {}).get("state", ""))
        ]
        for name in steps:
            waiting = [other for other in waiting if other != name]
            self._engine.set_queued(waiting)
            failure = self._reconcile_one(name, runners[name], modules[name])
            code = failure["code"] if failure else ""
            is_failed = bool(code) and code != PENDING_CODE
            self._engine.record_failure(name, failure if is_failed else None)
            is_kept = code not in (PENDING_CODE, RETRIED_CODE)
            self._keep_tried(name, hashes[name] if is_kept else "")
            with self._lock:
                self._outcomes[name] = failure
        self._engine.set_queued(())
        if self._ai_tools is not None:
            section = document.get(AI_TOOLS_SECTION)
            section_hash = _section_hash(section)
            if section_hash != tried.get(AI_TOOLS_SECTION):
                self._ai_tools.apply(section, state_hash, receive=self._receive)
                self._keep_tried(AI_TOOLS_SECTION, section_hash)
        self._settle_hash(state_hash, order, document)
        with self._lock:
            is_marked = self._is_containers_marked
        if is_marked:
            self._keep_tried(CONTAINERS_MODULE, "")
            with self._lock:
                if self._pending is None:
                    self._pending = dict(document)
            self._wakeup.set()
        self._engine.refresh_now()

    def _is_container_install(self, name: str, wanted: dict) -> bool:
        """Whether a state entry asks a container module to be present that is not installed."""
        return (
            _method_of(wanted) == AGENT_METHOD_CONTAINER
            and str(wanted.get("want", "") or "") in AGENT_PRESENT_WANTS
            and (
                self._engine.is_install_failed(name)
                or not self._engine.is_installed(name)
            )
        )

    def _apply_desktop(self, wanted) -> None:
        """Give the desktop host the seat password the hub holds.

        The Remote desktop module writes it into RustDesk's settings when it
        applies, and only when it is not the one written there.

        Args:
            wanted: The state's ``desktop`` section, or anything else when
                it carries none.
        """
        if self._rdp is None or not isinstance(wanted, dict):
            return
        self._rdp.take_seat_password(str(wanted.get("seat_password", "")))

    def _keep_tried(self, name: str, entry_hash: str) -> None:
        """Keep the hash one section was tried under, here and on disk; empty
        keeps none."""
        with self._lock:
            if entry_hash:
                self._tried[name] = entry_hash
            else:
                self._tried.pop(name, None)
            tried = dict(self._tried)
        try:
            self._store.write_tried(tried)
        except OSError as error:
            self._log(f"could not keep the tried state: {error}")

    def _settle_hash(self, state_hash: str, order: list, document: dict) -> None:
        """Move the applied hash and the state error by the last outcome of
        every mentioned module, in the order they apply."""
        with self._lock:
            first_failure = None
            is_pending = False
            for name in order:
                outcome = self._outcomes.get(name)
                if outcome is None:
                    continue
                if outcome["code"] == PENDING_CODE:
                    is_pending = True
                elif first_failure is None:
                    first_failure = {"module": name, **outcome}
            self._rechecked = dict(document) if is_pending else None
            if first_failure is not None:
                self._state_error = {
                    "code": first_failure["code"],
                    "params": {
                        "module": first_failure["module"],
                        **first_failure["params"],
                    },
                }
                return
            self._state_error = None
            if not is_pending:
                self._applied_hash = state_hash

    def _reconcile_one(self, name: str, runner, wanted: dict) -> "dict | None":
        """Make one module's actual state equal its ``want``.

        A module whose last install failed is installed again under a
        present ``want`` and uninstalled under ``absent``, whatever its
        check finds. An installed ``hub`` module whose recipe names another
        version than the one installed is switched to it first.

        Args:
            name: The module name.
            runner: Its runner.
            wanted: The state's entry for it.

        Returns:
            None when it took, ``{"state", "code", "params"}`` when it did
            not, ``state`` being the one the module reads afterwards.
        """
        want = str(wanted.get("want", "") or "")
        is_install_failed = self._engine.is_install_failed(name)
        if want == AGENT_WANT_ABSENT:
            if is_install_failed or self._engine.is_installed(name):
                return self._package_operation(
                    name, self._uninstall, AGENT_MODULE_STATE_FAILED
                )
            self._engine.clear_configured(name)
            return None
        if want not in AGENT_PRESENT_WANTS:
            self._log(f"{name}: want {want!r} is not one this agent knows")
            return None
        if is_install_failed or not self._engine.is_installed(name):
            failure = self._package_operation(
                name, self._install, AGENT_MODULE_STATE_INSTALL_FAILED
            )
            if failure:
                return failure
            if _method_of(wanted) == AGENT_METHOD_CONTAINER:
                with self._lock:
                    self._is_containers_marked = True
        elif self._engine.take_version_switch(name):
            failure = self._package_operation(
                name, self._switch_version, AGENT_MODULE_STATE_FAILED
            )
            if failure:
                return failure
        if want not in CONFIGURING_WANTS:
            return None
        failure = self._apply_one(name, runner, want, wanted.get("config"))
        if failure is None:
            self._engine.mark_configured(name)
            return None
        return {"state": AGENT_MODULE_STATE_FAILED, **failure}

    def _install(self, name: str, on_line) -> dict:
        return self._engine.install(name, receive=self._receive, on_line=on_line)

    def _uninstall(self, name: str, on_line) -> dict:
        return self._engine.uninstall(name, on_line=on_line)

    def _switch_version(self, name: str, on_line) -> dict:
        return self._engine.switch_version(name, receive=self._receive, on_line=on_line)

    def _package_operation(
        self, name: str, operation, failed_state: str
    ) -> "dict | None":
        """Run one package operation with its output up a log stream.

        Args:
            name: The module name.
            operation: Called with ``(name, on_line)``; returns empty or
                ``{"code", "params"}``.
            failed_state: The state the module reads when the operation
                fails, ``install_failed`` or ``failed``.

        Returns:
            None when it took, ``{"state", "code", "params"}`` when it did
            not.
        """
        log = self._open_log(name)
        refusal = operation(name, log.send if log is not None else None)
        if log is not None:
            if refusal:
                state = failed_state
            else:
                state = str((self._engine.report().get(name) or {}).get("state", ""))
            log.close(
                state,
                str(refusal.get("code", "") or "") if refusal else "",
                dict(refusal.get("params") or {}) if refusal else {},
            )
        if refusal:
            self._log(f"{name}: {refusal['code']}")
            return {
                "state": failed_state,
                "code": refusal["code"],
                "params": dict(refusal.get("params", {})),
            }
        return None

    def _open_log(self, name: str) -> "LogStream | None":
        """A ``log {module}`` stream to the hub, or None with no socket."""
        if self._open_stream is None:
            return None
        try:
            return LogStream(self._open_stream(STREAM_KIND_LOG, module=name))
        except GatewayUnreachable:
            return None

    def _receive(self, name: str, artifact: dict) -> dict:
        """One artifact's bytes, down a ``package {module, artifact, digest}`` stream.

        Args:
            name: The module the artifact belongs to, or ``cc_switch``.
            artifact: The recipe's artifact, ``{name, digest, ...}``.

        Returns:
            ``{"path", "sha256"}`` naming the file the close's digest
            checked and that digest, or ``{"code", "params"}``.
        """
        if self._open_stream is None:
            return {"code": RETRIED_CODE, "params": {}}
        try:
            channel = self._open_stream(
                STREAM_KIND_PACKAGE,
                module=name,
                artifact=str(artifact.get("name", "") or ""),
                digest=str(artifact.get("digest", "") or ""),
            )
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
            if want == AGENT_WANT_RUNNING:
                runner.start()
            elif want == AGENT_WANT_STOPPED:
                runner.stop()
            self._log(f"{name}: {want}")
        except ModuleInstallPending:
            return {"code": PENDING_CODE, "params": {}}
        except ModuleApplyError as error:
            said = " ".join(f"{key}={value}" for key, value in error.params.items())
            self._log(f"{name}: {error.code} {said}".rstrip()[:500])
            return {"code": error.code, "params": dict(error.params)}
        except PlatformUnsupportedError:
            return {"code": "unsupported_platform", "params": {}}
        except Exception as error:  # noqa: BLE001 - reported, never raised
            self._log(f"{name}: {error}")
            return {"code": "apply_failed", "params": {"detail": str(error)[:200]}}
        return None

    def _run(self) -> None:
        while True:
            with self._lock:
                timeout_s = AGENT_MODULE_INSTALL_RECHECK_S if self._rechecked else None
            is_woken = self._wakeup.wait(timeout_s)
            self._wakeup.clear()
            if not is_woken:
                with self._lock:
                    if self._pending is None:
                        self._pending = self._rechecked
            while True:
                with self._lock:
                    pending = self._pending
                    self._pending = None
                if pending is None:
                    with self._idle:
                        self._idle.notify_all()
                    break
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
