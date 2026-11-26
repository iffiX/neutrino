"""ComfyUI as a module: its Python environment, its service, the shared folders, comfy-mcp, its page.

The archives ``python``, ``uv`` and ``source`` come down package streams
and are unpacked and sealed under the module's directory; on Windows the
DLLs of the ``vc_runtime`` wheel are copied beside the module's
``python.exe``, each the Python does not carry itself. ``mcp`` is a lock
uv installs as root with wheels alone into ``mcp/``, then sealed. ``venv``
is a lock uv installs as the service's account into ``venv/`` in the data
directory, after the ``account`` step: another lock than the one the record
keeps stops ComfyUI, makes ``venv/`` again and installs each custom node's
``requirements.txt`` after it. Each ``configure`` takes ComfyUI's port and
the forwarder's, writes the shared folders' entries for the default
account, its comfy-mcp workspace and its tools' entries, and writes and
runs the service, waiting at most 300 seconds for ``/system_stats``. The
forwarder serves the page while ComfyUI runs, and idle unload reads its
queue every 60 seconds. The uninstall keeps ``data/`` and the account.

Not pure: drives ComfyUI through its applier and uv.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import dataclasses
import functools
import os
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
import zipfile

from neutrino_agent.constants import (
    AGENT_ARTIFACT_KIND_UV_LOCK,
    AGENT_MODULE_STATE_INSTALL_FAILED,
    AGENT_STEP_ACCOUNT,
    AGENT_STEP_ARTIFACT,
    AGENT_STEP_CONFIGURE,
    AGENT_STEP_UNINSTALL,
    AGENT_STEP_VERIFY,
    AGENT_WANT_STOPPED,
)
from neutrino_agent.exceptions import ModuleApplyError, PlatformUnsupportedError
from neutrino_agent.modules.comfyui.config import ComfyuiConfig, idle_seconds
from neutrino_agent.modules.comfyui.constants import (
    COMFYUI_ARTIFACT_MCP,
    COMFYUI_ARTIFACT_PYTHON,
    COMFYUI_ARTIFACT_UV,
    COMFYUI_ARTIFACT_VC_RUNTIME,
    COMFYUI_ARTIFACT_VENV,
    COMFYUI_BASE_PORT,
    COMFYUI_CUSTOM_NODES_DIR,
    COMFYUI_DETAIL_CHARS,
    COMFYUI_FORWARDER_BASE_PORT,
    COMFYUI_HOST,
    COMFYUI_LOCKS_DIR,
    COMFYUI_MCP_DIR,
    COMFYUI_NAME,
    COMFYUI_PROBE_TIMEOUT_S,
    COMFYUI_PYTHON_DIR,
    COMFYUI_RECORD_FIELDS,
    COMFYUI_RECORD_NAME,
    COMFYUI_REQUIREMENTS_NAME,
    COMFYUI_SOFTWARE_DIRS,
    COMFYUI_START_POLL_S,
    COMFYUI_START_WAIT_S,
    COMFYUI_STATS_PATH,
    COMFYUI_UV_DIR,
    COMFYUI_UV_TIMEOUT_S,
    COMFYUI_VC_RUNTIME_MEMBER,
    COMFYUI_VENV_DIR,
)
from neutrino_agent.modules.comfyui.darwin_applier import ComfyuiDarwinApplier
from neutrino_agent.modules.comfyui.forwarder import (
    ComfyuiForwarderHooks,
    page_forwarder,
)
from neutrino_agent.modules.comfyui.idle_unload import ComfyuiIdleUnload
from neutrino_agent.modules.comfyui.linux_applier import ComfyuiLinuxApplier
from neutrino_agent.modules.comfyui.mcp_wiring import ComfyuiMcpWiring
from neutrino_agent.modules.comfyui.server import ComfyuiServer, server_environment
from neutrino_agent.modules.comfyui.windows_applier import ComfyuiWindowsApplier
from neutrino_agent.modules.shared import source_fetch
from neutrino_agent.modules.shared.base import ModuleRunner, ModuleStep
from neutrino_agent.modules.shared.log_tail import file_tail
from neutrino_agent.modules.shared.loopback_port import is_port_free, pick_port
from neutrino_agent.modules.shared.package import (
    artifacts_of,
    joiner,
    params_of,
    unpack_artifact,
)
from neutrino_agent.modules.shared.python_env import (
    PythonEnvironment,
    environment_python,
    uv_variables,
)
from neutrino_agent.modules.shared.record_store import InstanceRecordStore
from neutrino_agent.modules.shared.step_locks import SYSTEM_ACCOUNTS_LOCKS
from neutrino_agent.modules.shared.subprocess_run import run as run_command
from neutrino_agent.modules.shared.subprocess_run import units_journal
from neutrino_agent.modules.shared.unpacked_tree import (
    make_staging,
    remove_tree,
    seal_tree,
)
from neutrino_agent.modules.shared.windows_acl import leave_to_system

# The source set the ``pypi`` variables of the service come from.
PYPI_SET = "pypi"


def stats_answer(port: int, timeout_s: float = COMFYUI_PROBE_TIMEOUT_S) -> bool:
    """Whether ``GET /system_stats`` answers 200 on ComfyUI's port.

    Args:
        port: ComfyUI's port.
        timeout_s: How long the read waits.

    Returns:
        True for a 200.
    """
    if not port:
        return False
    url = f"http://{COMFYUI_HOST}:{int(port)}{COMFYUI_STATS_PATH}"
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as answer:
            return answer.status == 200
    except (OSError, ValueError, urllib.error.URLError):
        return False


def comfyui_applier_for(platform):
    """The applier that runs ComfyUI on this system.

    Args:
        platform: The machine's platform.

    Returns:
        The Linux, macOS or Windows applier.

    Raises:
        PlatformUnsupportedError: On a system with none.
    """
    state_dir = platform.agent_var_dir()
    if platform.os_name == "linux":
        return ComfyuiLinuxApplier(state_dir=state_dir, platform=platform)
    if platform.os_name == "darwin":
        return ComfyuiDarwinApplier(state_dir=state_dir, platform=platform)
    if platform.os_name == "windows":
        return ComfyuiWindowsApplier(state_dir=state_dir, platform=platform)
    raise PlatformUnsupportedError("no ComfyUI here")


def artifact_named(recipe: dict, name: str) -> dict:
    """The recipe's artifact of one name, empty when it names none. Pure."""
    for artifact in artifacts_of(recipe):
        if artifact.get("name") == name:
            return artifact
    return {}


class ComfyuiModuleRunner(ModuleRunner):
    """Installs ComfyUI's Python environment, runs its service and serves its page."""

    runner = COMFYUI_NAME
    name = COMFYUI_NAME

    def __init__(
        self,
        *,
        platform,
        log=print,
        publish=None,
        applier=None,
        wiring=None,
        idle=None,
        hooks=None,
        forwarder_factory=page_forwarder,
        record_dir: str = "",
        read_stats=stats_answer,
        probe_one=source_fetch.probe,
        is_free=is_port_free,
        run_root=None,
        clock=time.monotonic,
        sleep=time.sleep,
    ):
        """
        Args:
            platform: The machine's platform.
            log: Callable used for progress messages.
            publish: Called with ``(name, status)`` for transient states.
            applier: The system's applier; None picks the platform's own.
            wiring: comfy-mcp's wiring for the default account; None makes
                it.
            idle: Idle unload; None makes it.
            hooks: The forwarder's rule; None makes it.
            forwarder_factory: Called with ``record``, ``hooks`` and
                ``log``; returns a forwarder.
            record_dir: Where the module's record lives; empty is the
                module's directory.
            read_stats: Called with ComfyUI's port; whether
                ``/system_stats`` answers.
            probe_one: Probes one source, as :func:`source_fetch.probe`.
            is_free: Answers whether a loopback port can be bound now.
            run_root: Runs uv as root, as :meth:`_run_root` does; None runs
                it here.
            clock: The monotonic clock the wait for the server is read on.
            sleep: Waits between two looks at the server.

        Raises:
            PlatformUnsupportedError: On a system with no applier.
        """
        super().__init__(platform=platform, log=log, publish=publish)
        self._applier = (
            applier if applier is not None else comfyui_applier_for(platform)
        )
        self._join = joiner(platform.os_name)
        self._wiring = (
            wiring
            if wiring is not None
            else ComfyuiMcpWiring(
                platform=platform,
                module_dir=self.module_dir,
                base_dir=self._applier.base_dir,
                log=log,
            )
        )
        self._idle = idle if idle is not None else ComfyuiIdleUnload(log=log)
        self._hooks = hooks if hooks is not None else ComfyuiForwarderHooks()
        self._forwarder_factory = forwarder_factory
        self._records = InstanceRecordStore(
            directory=record_dir or self.module_dir,
            fields=COMFYUI_RECORD_FIELDS,
            seal=(
                functools.partial(leave_to_system, run_command)
                if platform.os_name == "windows"
                else None
            ),
        )
        self._read_stats = read_stats
        self._probe_one = probe_one
        self._is_free = is_free
        self._run_root_command = run_root if run_root is not None else self._run_root
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._recipe: dict = {}
        self._config = ComfyuiConfig()
        self._source_sets: dict = {}
        self._forwarder = None
        self._is_resumed = False

    # --- what the engine hands the runner ---

    def take_recipe(self, recipe: dict) -> None:
        """Take the recipe the state names, whose locks and version the install reads.

        Args:
            recipe: ``{runner, method, params}``.
        """
        self._recipe = dict(recipe)

    def take_config(self, config: dict) -> None:
        """Take the configuration the state names.

        Args:
            config: ``{secret, cookie_name, local_name, torch_build,
                idle_unload, account, password, tools}``.
        """
        self._config = ComfyuiConfig.from_dict(config)

    def take_source_sets(self, source_sets: dict) -> None:
        """Take the state's ``source_sets`` section: the ``pytorch`` and ``pypi`` sets the locks install from.

        Args:
            source_sets: ``{name: {probe, sources, variables}}``.
        """
        self._source_sets = dict(source_sets)

    # --- the install ---

    def verify(self, recipe: dict) -> bool:
        """Whether the module's own Python is on the machine.

        Args:
            recipe: The module's recipe, empty here.

        Returns:
            True when the Python program is there.
        """
        return os.path.isfile(self._python_program())

    def install_steps(self, recipe: dict, steps: list) -> list:
        """The install's steps: every archive and ``mcp``, ``verify``, ``account`` on Linux and macOS, then ``venv``.

        An archive or a lock whose digest the record keeps for what is in
        place is left out, so another PyTorch build installs its lock alone.

        Args:
            recipe: The module's recipe.
            steps: The steps the method plans.

        Returns:
            The steps.
        """
        installed = self._installed_digests()
        early, venv, verify = [], [], []
        for step in steps:
            if step.name == AGENT_STEP_VERIFY:
                verify.append(step)
                continue
            if step.name != AGENT_STEP_ARTIFACT:
                early.append(step)
                continue
            name = str(step.params.get("name", "") or "")
            artifact = artifact_named(recipe, name)
            if installed.get(name) == artifact.get("digest") and self._is_in_place(
                name
            ):
                continue
            (venv if name == COMFYUI_ARTIFACT_VENV else early).append(step)
        account = []
        if self._applier.account:
            account = [
                ModuleStep(
                    name=AGENT_STEP_ACCOUNT,
                    params={"account": self._applier.account},
                    run=self._run_account,
                    failed_state=AGENT_MODULE_STATE_INSTALL_FAILED,
                    error_code="install_failed",
                )
            ]
        return early + verify + account + venv

    def is_install_owed(self, recipe: dict) -> bool:
        """Whether an artifact the recipe names is not the one in place, another lock among them.

        Args:
            recipe: The module's recipe.

        Returns:
            True when an artifact's digest differs from the one the record
            keeps, or its folder is missing.
        """
        installed = self._installed_digests()
        for artifact in artifacts_of(recipe):
            name = str(artifact.get("name", "") or "")
            if installed.get(name) != artifact.get("digest") or not self._is_in_place(
                name
            ):
                return True
        return False

    def install_artifact(self, recipe: dict, artifact: dict, path: str) -> None:
        """Put one artifact in place, as its name says.

        Args:
            recipe: The module's recipe.
            artifact: The artifact.
            path: The file on local disk, whose digest was checked.

        Raises:
            ModuleApplyError: ``install_failed {detail}`` when it cannot be
                put in place.
            OSError: When the module's directory cannot be written.
        """
        name = str(artifact.get("name", "") or "")
        if name == COMFYUI_ARTIFACT_VC_RUNTIME:
            self._place_vc_runtime(artifact, path)
        elif name == COMFYUI_ARTIFACT_MCP:
            self._install_mcp(path)
        elif name == COMFYUI_ARTIFACT_VENV:
            self._install_venv(
                path,
                str(artifact.get("digest", "") or ""),
                [str(name) for name in artifact.get("source_sets") or []],
            )
        elif str(artifact.get("kind", "") or "") == AGENT_ARTIFACT_KIND_UV_LOCK:
            raise ModuleApplyError(
                "install_failed", {"detail": f"artifact {name!r} has no place"}
            )
        else:
            placed = unpack_artifact(
                artifact, path, module_dir=self.module_dir, join=self._join
            )
            self._platform.label_programs(placed)
            self._platform.open_to_accounts(self.module_dir)
        self._keep_digest(name, str(artifact.get("digest", "") or ""))

    def step_locks(self, step: str) -> tuple:
        """``system_accounts`` for ``account`` and ``uninstall``.

        Args:
            step: The step's name.

        Returns:
            The step locks the module adds to the step.
        """
        if step in (AGENT_STEP_ACCOUNT, AGENT_STEP_UNINSTALL):
            return SYSTEM_ACCOUNTS_LOCKS
        return ()

    def uninstall(self, recipe: dict) -> None:
        """Take the service, the module's directory, the venv and the caches, the tools' entries and the workspace off; ``data/`` and the account stay.

        Args:
            recipe: The module's recipe.
        """
        self._idle.stop()
        self._close_forwarder()
        account = self._config.account or str(
            self._record().get("default_account", "") or ""
        )
        if account:
            self._wiring.remove(account=account, password=str(self._config.password))
        self._applier.stop()
        for name in COMFYUI_SOFTWARE_DIRS:
            path = self._join(self._applier.data_dir, name)
            try:
                self._applier.remove_as_service(path)
            except (OSError, ModuleApplyError) as error:
                self._log(f"comfyui: {path} stays: {error}")
        self._applier.uninstall()

    # --- the configuration ---

    def validate(self, config: dict) -> None:
        """Check the configuration against its choices.

        Args:
            config: The desired configuration.

        Raises:
            ModuleApplyError: ``config_invalid {field}``; ``account_unknown
                {account}`` for a default account the machine does not have.
        """
        settings = ComfyuiConfig.from_dict(config)
        settings.validate(self._platform.os_name)
        self._check_account(str(settings.account))

    def apply(self, config: dict) -> None:
        """Write the shared folders' entries, comfy-mcp and the service, and run the server, at most 300 seconds until it answers.

        Args:
            config: The desired configuration.

        Raises:
            ModuleApplyError: ``config_invalid {field}``; ``account_unknown
                {account}``; ``apply_failed {detail}`` when the service cannot
                be written or the server does not answer in time.
        """
        self._apply(config, is_started=True)

    def apply_stopped(self, config: dict) -> None:
        """Write everything under ``stopped``; the service neither enabled nor started.

        Args:
            config: The desired configuration.

        Raises:
            ModuleApplyError: As :meth:`apply` does.
        """
        self._apply(config, is_started=False)

    def configure_steps(self, config: dict, want: str, steps: list) -> list:
        """The core's steps, the ``configure`` of ``stopped`` writing and starting nothing.

        Args:
            config: The configuration the task's entry carries.
            want: ``running`` or ``stopped``.
            steps: ``configure``, then ``start`` or ``stop``.

        Returns:
            The steps.
        """
        if want != AGENT_WANT_STOPPED:
            return steps
        return [
            (
                dataclasses.replace(
                    step,
                    run=functools.partial(self._run_apply_stopped, dict(config)),
                )
                if step.name == AGENT_STEP_CONFIGURE
                else step
            )
            for step in steps
        ]

    def stop(self) -> None:
        """Take the server down and keep it from starting at boot, the data in place."""
        self._idle.stop()
        self._close_forwarder()
        record = self._record()
        if record:
            self._keep({**record, "is_stopped": True})
        self._applier.stop()

    def is_active(self) -> bool:
        """Whether the service runs."""
        self._resume()
        return self._applier.is_active()

    def forwarder_ports(self) -> tuple:
        """The forwarder's port while it listens."""
        with self._lock:
            forwarder = self._forwarder
        if forwarder is None or not forwarder.is_listening:
            return ()
        return (int(self._record().get("port", 0) or 0),)

    def details(self, recipe: dict) -> dict:
        """Whether ComfyUI answers, the forwarder's port and the tested version.

        Args:
            recipe: The module's recipe.

        Returns:
            ``{"is_running", "port", "version"}``.
        """
        record = self._resume()
        return {
            "is_running": bool(
                self._read_stats(int(record.get("upstream_port", 0) or 0))
            ),
            "port": int(record.get("port", 0) or 0),
            "version": str(params_of(recipe or self._recipe).get("version", "") or ""),
        }

    def journal_units(self) -> list:
        """The module's unit on Linux; none elsewhere."""
        return self._applier.journal_units()

    def journal_text(self, lines: int) -> list:
        """The unit's journal on Linux; elsewhere the end of the server's output, then the agent's lines that name the module.

        Args:
            lines: How many lines to return at most.

        Returns:
            The lines, oldest first.
        """
        path = self._applier.output_path()
        if not path:
            return super().journal_text(lines)
        own = self._read_source(path, functools.partial(file_tail, path, lines))
        return self._with_agent_lines(own, lines)

    # --- the steps' own work ---

    def _run_account(self, context) -> None:
        """The ``account`` step: the service's account made when it is missing, and its data directory."""
        if self._applier.ensure_account(log=self._log):
            self._log(f"comfyui: gave its data to {self._applier.account}")

    def _run_apply_stopped(self, config: dict, context) -> None:
        """The ``configure`` step under ``stopped``."""
        self.apply_stopped(config)

    def _apply(self, config: dict, *, is_started: bool) -> None:
        """Write the entries, comfy-mcp and the service; with ``is_started`` run it and wait until it answers."""
        settings = ComfyuiConfig.from_dict(config)
        settings.validate(self._platform.os_name)
        self._check_account(str(settings.account))
        self._config = settings
        try:
            self._applier.prepare_data()
            record = self._ports(self._record(), is_started=is_started)
            index_url = self._index_url(record, settings)
            server = ComfyuiServer(
                port=int(record["upstream_port"]),
                index_url=index_url,
                is_cpu=settings.is_cpu,
            )
            left = self._applier.write_access(str(settings.account))
        except (OSError, KeyError, subprocess.SubprocessError) as error:
            raise ModuleApplyError("apply_failed", {"detail": str(error)[:500]})
        for path in left[:5]:
            self._log(f"comfyui: left the entries of {path} as they are")
        if settings.account:
            try:
                written = self._wiring.apply(
                    account=str(settings.account),
                    password=str(settings.password),
                    tools=list(settings.tools),
                    port=server.port,
                )
            except (OSError, KeyError, ModuleApplyError) as error:
                self._log(f"comfyui: comfy-mcp for {settings.account}: {error}")
                written = []
            if written:
                self._log(f"comfyui: comfy-mcp named in {', '.join(written)}")
        try:
            note = self._applier.apply(server, is_started=is_started)
        except (OSError, subprocess.SubprocessError, ModuleApplyError) as error:
            raise ModuleApplyError("apply_failed", {"detail": str(error)[:500]})
        record = self._keep(
            {
                **record,
                "secret": settings.secret,
                "cookie_name": settings.cookie_name,
                "local_name": settings.local_name,
                "index_url": index_url,
                "default_account": settings.account,
                "is_stopped": not is_started,
            }
        )
        self._log(f"comfyui: {note}")
        if not is_started:
            self._idle.stop()
            self._close_forwarder()
            return
        self._wait_for_server(server.port)
        self._sync_forwarder(record)
        self._idle.take(server.port, idle_seconds(str(settings.idle_unload)))

    def _check_account(self, account: str) -> None:
        """Refuse a default account the machine does not have.

        Raises:
            ModuleApplyError: ``account_unknown {account}``.
        """
        try:
            is_known = not account or self._platform.has_account(account)
        except PlatformUnsupportedError:
            is_known = True
        if not is_known:
            raise ModuleApplyError("account_unknown", {"account": account})

    def _ports(self, record: dict, *, is_started: bool) -> dict:
        """The record with ComfyUI's port and the forwarder's, each kept or taken from its base up.

        A kept port another program holds is replaced by the next free one.

        Raises:
            OSError: When no port is free.
        """
        upstream = int(record.get("upstream_port", 0) or 0)
        port = int(record.get("port", 0) or 0)
        is_running = self._applier.is_active()
        if not upstream or (not is_running and not self._is_free(upstream)):
            upstream = pick_port(COMFYUI_BASE_PORT, taken=[port], is_free=self._is_free)
        with self._lock:
            forwarder = self._forwarder
        is_served = forwarder is not None and forwarder.is_listening
        if not port or (not is_served and not self._is_free(port)):
            port = pick_port(
                COMFYUI_FORWARDER_BASE_PORT, taken=[upstream], is_free=self._is_free
            )
        return {**record, "upstream_port": upstream, "port": port}

    def _index_url(self, record: dict, settings: ComfyuiConfig) -> str:
        """The ``pypi`` set's first ranked source, or the record's while the service names it with nothing else changed."""
        ranked = self._ranked(PYPI_SET)
        fresh = ranked[0] if ranked else ""
        kept = str(record.get("index_url", "") or "")
        if not kept or kept == fresh:
            return fresh
        server = ComfyuiServer(
            port=int(record["upstream_port"]), index_url=kept, is_cpu=settings.is_cpu
        )
        if self._applier.written_text() == self._applier.service_text(server):
            return kept
        return fresh

    def _ranked(self, set_name: str) -> list:
        """One source set's sources, the fastest first; empty while the state names none."""
        held = self._source_sets.get(set_name)
        held = held if isinstance(held, dict) else {}
        sources = [str(source) for source in held.get("sources") or []]
        if not sources:
            return []
        return source_fetch.rank_set(
            sources,
            probe_path=str(held.get("probe", "") or "/"),
            probe_one=self._probe_one,
            latency_paths=held.get("latency_probes") or (),
            log=self._log,
            name=f"comfyui: source set {set_name}",
        )

    def _wait_for_server(self, port: int) -> None:
        """Wait until ``/system_stats`` answers on ComfyUI's port.

        Raises:
            ModuleApplyError: ``apply_failed {detail}`` naming the port and
                the server's last line when the wait runs out.
        """
        deadline = self._clock() + COMFYUI_START_WAIT_S
        while not self._read_stats(port):
            if self._clock() >= deadline:
                detail = f"comfyui did not answer on {COMFYUI_HOST}:{port}"
                said = self._last_words()
                if said:
                    detail += f": {said}"
                raise ModuleApplyError(
                    "apply_failed", {"detail": detail[:COMFYUI_DETAIL_CHARS]}
                )
            self._sleep(COMFYUI_START_POLL_S)

    def _last_words(self) -> str:
        """The last line of the server's output."""
        path = self._applier.output_path()
        try:
            lines = (
                file_tail(path, 1) if path else units_journal(self.journal_units(), 1)
            )
        except OSError:
            return ""
        return lines[-1].strip() if lines else ""

    def _install_mcp(self, path: str) -> None:
        """Install comfy-mcp's lock as root into ``mcp/`` with wheels alone, then seal it.

        Raises:
            ModuleApplyError: ``install_failed {detail}`` when uv refuses.
            OSError: When a file cannot be read or written.
        """
        folder = self._join(self.module_dir, COMFYUI_MCP_DIR)
        cache = make_staging(self.module_dir)
        try:
            remove_tree(folder)
            environment = PythonEnvironment(
                uv=self._uv_program(),
                python=self._python_program(),
                folder=folder,
                os_name=self._platform.os_name,
                run=functools.partial(self._run_root_command, cache),
                rank=self._ranked,
                log=self._log,
                name=self.name,
                is_root=True,
            )
            environment.make()
            environment.install(
                self._read_lock(path),
                parts_dir=self._join(self.module_dir, COMFYUI_LOCKS_DIR),
                source_sets=self._source_sets,
            )
        finally:
            remove_tree(cache)
        seal_tree(folder)
        self._platform.open_to_accounts(self.module_dir)

    def _install_venv(self, path: str, digest: str, sets: list) -> None:
        """Make ``venv/`` as the service's account and install the lock into it, ComfyUI stopped.

        Another lock than the one the record keeps makes ``venv/`` again,
        then installs each custom node's ``requirements.txt``.

        Raises:
            ModuleApplyError: ``install_failed {detail}`` when uv refuses.
            OSError: When a file cannot be read or written.
        """
        lock_text = self._read_lock(path)
        self._applier.prepare_data()
        venv = self._join(self._applier.data_dir, COMFYUI_VENV_DIR)
        environment = PythonEnvironment(
            uv=self._uv_program(),
            python=self._python_program(),
            folder=venv,
            os_name=self._platform.os_name,
            run=self._run_as_service,
            rank=self._ranked,
            log=self._log,
            name=self.name,
        )
        was_held = bool(self._record().get("lock_digest"))
        self._idle.stop()
        self._close_forwarder()
        self._applier.stop()
        self._applier.remove_as_service(venv)
        environment.make()
        environment.install(
            lock_text,
            parts_dir=self._join(self.module_dir, COMFYUI_LOCKS_DIR),
            source_sets=self._source_sets,
            set_order=tuple(sets),
        )
        self._keep({**self._record(), "lock_digest": digest})
        if was_held:
            self._reinstall_node_packages(environment)

    def _reinstall_node_packages(self, environment: PythonEnvironment) -> None:
        """Install each custom node's ``requirements.txt`` into a new venv, a failure logged."""
        nodes = self._join(self._applier.base_dir, COMFYUI_CUSTOM_NODES_DIR)
        try:
            names = sorted(os.listdir(nodes))
        except OSError:
            return
        ranked = self._ranked(PYPI_SET)
        if not ranked:
            return
        for name in names:
            requirements = self._join(nodes, name, COMFYUI_REQUIREMENTS_NAME)
            if not os.path.isfile(requirements) or os.path.islink(requirements):
                continue
            failure = environment.install_requirements(requirements, ranked[0])
            if failure:
                self._log(f"comfyui: the packages of {name} failed: {failure}")
            else:
                self._log(f"comfyui: installed the packages of {name} again")

    def _run_as_service(self, argv: list) -> tuple:
        """Run one uv command as the service's account with uv's variables."""
        environment = server_environment(
            ComfyuiServer(port=0),
            data_dir=self._applier.data_dir,
            os_name=self._platform.os_name,
        )
        return self._applier.run_as_service(argv, environment, COMFYUI_UV_TIMEOUT_S)

    def _run_root(self, cache: str, argv: list) -> tuple:
        """Run one uv command as root or SYSTEM with uv's variables and its cache.

        Returns:
            ``(exit_code, output)``.
        """
        variables = uv_variables(cache_dir=cache, os_name=self._platform.os_name)
        if self._platform.os_name == "windows":
            environment = {**os.environ, **variables}
        else:
            environment = {"PATH": "/usr/bin:/bin", "HOME": cache, **variables}
        try:
            done = subprocess.run(
                argv,
                capture_output=True,
                timeout=COMFYUI_UV_TIMEOUT_S,
                env=environment,
                cwd=self.module_dir,
            )
        except (OSError, subprocess.SubprocessError) as error:
            return 127, str(error)
        words = (done.stdout or b"") + b"\n" + (done.stderr or b"")
        return done.returncode, words.decode("utf-8", "replace")

    def _place_vc_runtime(self, artifact: dict, path: str) -> None:
        """Copy the wheel's DLLs beside the module's ``python.exe``, each the Python does not carry itself.

        Raises:
            ModuleApplyError: ``install_failed {detail}`` for a wheel that
                does not read or holds no such folder.
            OSError: When a file cannot be written.
        """
        member = str(artifact.get("member", "") or "") or COMFYUI_VC_RUNTIME_MEMBER
        target = os.path.join(self.module_dir, COMFYUI_PYTHON_DIR)
        staging = make_staging(self.module_dir)
        try:
            try:
                with zipfile.ZipFile(path) as wheel:
                    names = [
                        name
                        for name in wheel.namelist()
                        if name.startswith(member.rstrip("/") + "/")
                        and "/" not in name[len(member.rstrip("/")) + 1 :]
                        and not name.endswith("/")
                    ]
                    if not names:
                        raise ModuleApplyError(
                            "install_failed",
                            {"detail": f"the wheel holds no {member}"},
                        )
                    for name in names:
                        wheel.extract(name, staging)
            except zipfile.BadZipFile as error:
                raise ModuleApplyError(
                    "install_failed", {"detail": str(error)[:200]}
                ) from error
            for name in names:
                placed = os.path.join(target, name.rsplit("/", 1)[-1])
                if os.path.exists(placed):
                    continue
                shutil.copyfile(os.path.join(staging, *name.split("/")), placed)
                os.chmod(placed, 0o555)
        finally:
            remove_tree(staging)

    def _read_lock(self, path: str) -> str:
        """A lock's text, as it came down the package stream."""
        with open(path, "r", encoding="utf-8") as stream:
            return stream.read()

    def _python_program(self) -> str:
        """The module's own Python program."""
        folder = self._join(self.module_dir, COMFYUI_PYTHON_DIR)
        if self._platform.os_name == "windows":
            return self._join(folder, "python.exe")
        return self._join(folder, "bin", "python3")

    def _uv_program(self) -> str:
        """The module's uv program."""
        name = "uv.exe" if self._platform.os_name == "windows" else "uv"
        return self._join(self.module_dir, COMFYUI_UV_DIR, name)

    def _is_in_place(self, name: str) -> bool:
        """Whether an artifact's files are where it puts them."""
        if name == COMFYUI_ARTIFACT_VENV:
            venv = self._join(self._applier.data_dir, COMFYUI_VENV_DIR)
            return os.path.isfile(environment_python(venv, self._platform.os_name))
        if name == COMFYUI_ARTIFACT_VC_RUNTIME:
            return os.path.isdir(self._join(self.module_dir, COMFYUI_PYTHON_DIR))
        if name == COMFYUI_ARTIFACT_PYTHON:
            return os.path.isfile(self._python_program())
        if name == COMFYUI_ARTIFACT_UV:
            return os.path.isfile(self._uv_program())
        return os.path.isdir(self._join(self.module_dir, name))

    def _installed_digests(self) -> dict:
        """Each artifact's digest the record keeps for what is in place."""
        held = self._record().get("artifacts")
        digests = dict(held) if isinstance(held, dict) else {}
        lock = str(self._record().get("lock_digest", "") or "")
        if lock:
            digests[COMFYUI_ARTIFACT_VENV] = lock
        return digests

    def _keep_digest(self, name: str, digest: str) -> None:
        """Keep one artifact's digest in the record once it is in place."""
        record = self._record()
        held = record.get("artifacts")
        artifacts = dict(held) if isinstance(held, dict) else {}
        artifacts[name] = digest
        self._keep({**record, "artifacts": artifacts})

    def _record(self) -> dict:
        """The module's record; empty before the first write."""
        return self._records.read(COMFYUI_RECORD_NAME)

    def _keep(self, record: dict) -> dict:
        """Write the module's record, and give it back as written."""
        kept = {**record, "account": COMFYUI_RECORD_NAME}
        try:
            self._records.write(kept)
        except OSError as error:
            self._log(f"comfyui: the record was not kept: {error}")
        return kept

    def _resume(self) -> dict:
        """Start the forwarder and idle unload the record names, once, after the agent starts."""
        record = self._record()
        with self._lock:
            if self._is_resumed:
                return record
            self._is_resumed = True
        if record and not record.get("is_stopped") and record.get("port"):
            self._sync_forwarder(record)
            self._idle.take(
                int(record.get("upstream_port", 0) or 0),
                idle_seconds(str(self._config.idle_unload)),
            )
        return record

    def _sync_forwarder(self, record: dict) -> None:
        """Run one forwarder for the record as it stands."""
        with self._lock:
            self._is_resumed = True
            current = self._forwarder
            if current is not None and current.matches(record):
                return
            self._forwarder = None
        if current is not None:
            current.close()
        if not record.get("port") or not record.get("upstream_port"):
            return
        forwarder = self._forwarder_factory(
            record=record, hooks=self._hooks, log=self._log
        )
        with self._lock:
            self._forwarder = forwarder
        forwarder.start()

    def _close_forwarder(self) -> None:
        with self._lock:
            forwarder, self._forwarder = self._forwarder, None
        if forwarder is not None:
            forwarder.close()
