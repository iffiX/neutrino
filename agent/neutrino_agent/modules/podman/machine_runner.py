"""Containers on Windows and macOS: Podman inside one account's Podman machine.

The install keeps each artifact the hub sent as the publisher's file under
``podman/<directory>/`` in the state root, and hands an msi or a pkg to the
system's installer; the machine image stays a file for ``podman machine
init``. An apply makes the account's default machine exist, rootful, on
WSL's NAT network on Windows and the size the Run settings name, writes and
starts the keeper that brings it up at boot, waits until the machine answers
the read, and writes the declared containers, and the hub containers of each
module whose images are in the machine's store, into it with one root
script. What differs between Windows and macOS around the machine is the
system's applier, a
:class:`PodmanSystemApplier`. A root-only record of the last apply lets the
reads, the journal and the verbs go on after the agent restarts.

Not pure: drives the machine, the keeper and the computer's installer.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import functools
import ntpath
import os
import subprocess
import threading
import time

from neutrino_agent.constants import AGENT_ARTIFACT_KIND_MSI, AGENT_ARTIFACT_KIND_PKG
from neutrino_agent.exceptions import (
    ModuleApplyError,
    ModuleInstallPending,
    PlatformUnsupportedError,
)
from neutrino_agent.modules.podman.applier import (
    PodmanStatusReader,
    ensure_network,
    fastest_sources,
    image_references,
    podman_version,
    ready_hub_containers,
)
from neutrino_agent.modules.podman.config import (
    CONTAINER_NAME_PATTERN,
    PodmanConfig,
    PodmanMachineSettings,
)
from neutrino_agent.modules.podman.constants import (
    PODMAN_COMMAND_CONTROL,
    PODMAN_COMMAND_JOURNAL,
    PODMAN_CONTAINER_ACTIONS,
    PODMAN_GIB,
    PODMAN_JOURNAL_LINES,
    PODMAN_MACHINE_API_POLL_S,
    PODMAN_MACHINE_API_WAIT_S,
    PODMAN_MACHINE_CHANGED_PREFIX,
    PODMAN_MACHINE_DEFAULT_DISK_GIB,
    PODMAN_MACHINE_DEFAULT_MEMORY_MAX_GIB,
    PODMAN_MACHINE_DETAIL_CHARS,
    PODMAN_MACHINE_FALLBACK_MEMORY_GIB,
    PODMAN_MACHINE_IMAGE_ARTIFACT,
    PODMAN_MACHINE_INFO_TTL_S,
    PODMAN_MACHINE_IMAGE_KINDS,
    PODMAN_MACHINE_RUNNER,
    PODMAN_MACHINE_RECORD_FIELDS,
    PODMAN_MODULE_NAME,
    PODMAN_SOURCE_MANUAL,
    PODMAN_WINDOWS_WSL_ARTIFACT,
)
from neutrino_agent.modules.podman.machine import PodmanMachine
from neutrino_agent.modules.podman.machine_keeper import keeper_service
from neutrino_agent.modules.podman.machine_paths import to_host_source
from neutrino_agent.modules.podman.page_ports import PodmanPagePortStore
from neutrino_agent.modules.podman.renderer import (
    PodmanMachineScriptRenderer,
    PodmanRenderContext,
    machine_control_script,
    machine_drop_script,
    machine_journal_script,
    machine_stop_script,
)
from neutrino_agent.modules.podman.service_probe import PodmanServiceProbe
from neutrino_agent.modules.shared import account_service
from neutrino_agent.modules.shared.base import ModuleRunner, command_outcome
from neutrino_agent.modules.shared.instances import machine_for
from neutrino_agent.modules.shared.log_tail import file_tail
from neutrino_agent.modules.shared.package import keep_artifact, kept_artifact_path
from neutrino_agent.modules.shared.record_store import InstanceRecordStore
from neutrino_agent.modules.shared.subprocess_run import command_detail
from neutrino_agent.modules.shared.unpacked_tree import remove_tree


def podman_system_applier_for(platform, *, log=print) -> PodmanSystemApplier:
    """The applier that does this system's part around a Podman machine.

    Args:
        platform: The computer's platform.
        log: Called with each progress line.

    Returns:
        The system's applier; the base, which refuses every step, on a
        system with none.
    """
    # Imported here: each system's applier is built on this module's base.
    if platform.os_name == "windows":
        from neutrino_agent.modules.podman.windows_applier import (
            PodmanWindowsApplier,
        )

        return PodmanWindowsApplier(platform=platform, log=log)
    if platform.os_name == "darwin":
        from neutrino_agent.modules.podman.darwin_applier import PodmanDarwinApplier

        return PodmanDarwinApplier(platform=platform)
    return PodmanSystemApplier()


def default_memory_gib(host_memory_gib: int) -> int:
    """The machine's memory for a 0 in the Run settings.

    Args:
        host_memory_gib: The computer's memory in GiB; 0 when it was not read.

    Returns:
        Half the computer's memory, at most 4 GiB and at least 1; Podman's
        own 2 GiB when the computer's memory was not read.
    """
    if host_memory_gib <= 0:
        return PODMAN_MACHINE_FALLBACK_MEMORY_GIB
    return max(1, min(PODMAN_MACHINE_DEFAULT_MEMORY_MAX_GIB, host_memory_gib // 2))


def _unit_names(declared: list, hub_names: dict) -> list:
    """The containers a unit file stands for in the machine: every declared and hub one."""
    names = list(declared)
    for module_names in hub_names.values():
        names += module_names
    return names


def _whole(value) -> int:
    """A whole number from ``podman info``, 0 for anything else."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


class PodmanSystemApplier:
    """What a Podman machine needs of the computer: the part Windows and macOS do differently.

    The Windows applier turns on the Windows features, installs WSL and
    Podman's msi, writes the account's ``.wslconfig`` and resizes the WSL
    disk; the macOS applier installs Podman's pkg and sizes the machine
    through Podman. This base is the honest answer on a system with neither:
    it reads nothing and refuses every step.

    Attributes:
        provider: The machine provider, ``wsl`` or ``applehv``.
        binary: Podman's program on the computer.
    """

    provider = ""
    binary = ""

    def install_artifact(self, artifact: dict, path: str) -> None:
        """Install one artifact the system's installer takes, an msi or a pkg.

        Args:
            artifact: ``{name, kind, digest, directory}``.
            path: The kept file.

        Raises:
            ModuleApplyError: ``windows_feature_failed {feature, exit_code}``
                or ``podman_install_failed {artifact, exit_code}``.
            PlatformUnsupportedError: On a system with no applier.
        """
        raise PlatformUnsupportedError("no Podman machine here")

    def is_reboot_pending(self) -> bool:
        """Whether the computer owes the restart an install step asked for.

        Returns:
            False on a system that asks for none.
        """
        return False

    def uninstall(self) -> None:
        """Uninstall Podman and forget the restart mark; the machine stays.

        Raises:
            PlatformUnsupportedError: On a system with no applier.
        """
        raise PlatformUnsupportedError("no Podman machine here")

    def host_facts(self) -> tuple:
        """The computer's size, which the Run settings may not pass.

        Returns:
            ``(cpus, memory_gib)``: its logical processors and its memory in
            GiB, 0 for what cannot be read.
        """
        return (os.cpu_count() or 0, 0)

    def disk_gib(self, machine: PodmanMachine) -> int:
        """The size of the machine's disk now, its virtual size in GiB.

        Args:
            machine: The machine.

        Returns:
            The size; 0 when it cannot be read.
        """
        return 0

    def halt(self, machine: PodmanMachine) -> None:
        """Stop what holds the machine's size, so a new size can take.

        Args:
            machine: The machine.

        Raises:
            ModuleApplyError: ``machine_set_failed`` when the system refuses.
            PlatformUnsupportedError: On a system with no applier.
        """
        raise PlatformUnsupportedError("no Podman machine here")

    def terminate(self, machine: PodmanMachine) -> None:
        """End the stopped machine's own system where the computer keeps it
        after a stop, so its next start takes the computer's network anew.

        Args:
            machine: The machine.

        Raises:
            ModuleApplyError: ``machine_set_failed`` when the system refuses.
        """

    def write_resources(
        self, machine: PodmanMachine, *, cpus: int, memory_gib: int
    ) -> None:
        """Give the halted machine its processors and memory.

        Args:
            machine: The machine.
            cpus: Its processors, a 0 already made the default's number.
            memory_gib: Its memory in GiB, a 0 already made the default's.

        Raises:
            ModuleApplyError: ``machine_set_failed`` when the system refuses.
            PlatformUnsupportedError: On a system with no applier.
        """
        raise PlatformUnsupportedError("no Podman machine here")

    def resize_disk(self, machine: PodmanMachine, *, disk_gib: int) -> None:
        """Give the halted machine's disk a new size.

        Args:
            machine: The machine.
            disk_gib: The size in GiB.

        Raises:
            ModuleApplyError: ``machine_set_failed`` when the system refuses.
            PlatformUnsupportedError: On a system with no applier.
        """
        raise PlatformUnsupportedError("no Podman machine here")

    def machine_environment(self, account: str) -> dict:
        """The variables every machine command of the account runs with, beside the provider.

        Args:
            account: The machine's account.

        Returns:
            Name to value; empty on a system that needs none.
        """
        return {}


class PodmanMachineModuleRunner(ModuleRunner):
    """Installs Podman from the hub's bytes and keeps the declared containers running in one account's machine."""

    runner = PODMAN_MACHINE_RUNNER
    name = PODMAN_MODULE_NAME

    def __init__(
        self,
        *,
        platform,
        log=print,
        publish=None,
        system=None,
        service_machine=None,
        machine_class=PodmanMachine,
        clock=time.monotonic,
        sleep=time.sleep,
    ):
        """
        Args:
            platform: The computer's platform.
            log: Callable used for progress messages.
            publish: Called with ``(name, status)`` for transient states.
            system: The system's applier; None picks the platform's own.
            service_machine: The computer as the account service layer
                reaches it; None is the platform's own.
            machine_class: Made with ``platform``, ``account``, ``password``,
                ``binary``, ``provider`` and ``environment``; drives one
                account's machine.
            clock: The monotonic clock the waits and the reading age on.
            sleep: Waits between two asks while the machine starts.
        """
        super().__init__(platform=platform, log=log, publish=publish)
        self._system = (
            system
            if system is not None
            else podman_system_applier_for(platform, log=self._log)
        )
        self._service_machine = (
            service_machine
            if service_machine is not None
            else machine_for(platform, self.name)
        )
        self._records = InstanceRecordStore(
            directory=self._service_machine.record_dir,
            fields=PODMAN_MACHINE_RECORD_FIELDS,
        )
        self._machine_class = machine_class
        self._clock = clock
        self._sleep = sleep
        self._probe = PodmanServiceProbe()
        self._join = ntpath.join if platform.os_name == "windows" else os.path.join
        self._lock = threading.Lock()
        # One apply, stop or removal at a time.
        self._apply_lock = threading.Lock()
        self._config: "PodmanConfig | None" = None
        self._written: "PodmanConfig | None" = None
        self._wanted: "PodmanConfig | None" = None
        self._source_sets: dict = {}
        self._page_ports = PodmanPagePortStore(directory=platform.agent_data_dir())
        # The last reading of the machine: ``(at, account, command, info)``,
        # ``info`` None when the machine did not answer.
        self._reading: "tuple | None" = None
        # The computer's memory in GiB, read at the first report; 0 until
        # it is read.
        self._host_memory_gib = 0

    def verify(self, recipe: dict) -> bool:
        """Whether Podman's program is on the computer.

        Args:
            recipe: The module's recipe.

        Returns:
            True when the system applier's program exists.
        """
        return bool(self._system.binary) and os.path.isfile(self._system.binary)

    def install_artifact(self, recipe: dict, artifact: dict, path: str) -> None:
        """Keep one artifact as the publisher's file, and have the system install an msi or a pkg.

        Args:
            recipe: The module's recipe.
            artifact: ``{name, kind, digest, directory}``.
            path: The file on local disk; it is moved, not copied.

        Raises:
            ModuleApplyError: ``install_failed`` for an artifact whose name,
                directory or kind the module does not keep; the system
                applier's codes for an msi or a pkg it cannot install.
            OSError: When the file cannot be kept or opened to every account.
        """
        kept = keep_artifact(
            artifact,
            path,
            module_dir=self._service_machine.module_dir,
            join=self._join,
        )
        self._platform.open_to_accounts(self._service_machine.module_dir)
        self._log(f"podman: kept {artifact.get('name', '')}")
        if artifact.get("kind") in (AGENT_ARTIFACT_KIND_MSI, AGENT_ARTIFACT_KIND_PKG):
            self._system.install_artifact(dict(artifact), kept)

    def uninstall_package(self, recipe: dict, artifact: dict) -> None:
        """Uninstall the Podman package before another version's is installed.

        WSL's msi is the system's and stays; the machine stays as well.

        Args:
            recipe: The module's recipe.
            artifact: The ``msi`` or ``pkg`` artifact being replaced.

        Raises:
            ModuleApplyError: ``uninstall_failed`` when msiexec fails.
            OSError: When a file the pkg put down cannot be deleted.
            PlatformUnsupportedError: On a system with no applier.
        """
        if artifact.get("name") == PODMAN_WINDOWS_WSL_ARTIFACT:
            return
        self._system.uninstall()
        self._log(f"podman: uninstalled {artifact.get('name', '')} for another version")

    def uninstall(self, recipe: dict) -> None:
        """Uninstall Podman and delete the kept artifacts; the machine stays.

        A keeper an apply left behind goes first, with the containers'
        files in the machine.

        Args:
            recipe: The module's recipe.

        Raises:
            PlatformUnsupportedError: On a system with no applier.
        """
        if self._record():
            self.remove_configuration()
        self._system.uninstall()
        remove_tree(self._service_machine.module_dir)

    def validate(self, config: dict) -> None:
        """Parse and check a configuration against this computer.

        Args:
            config: The desired configuration.

        Raises:
            ModuleApplyError: Naming the first problem found, the machine's
                ``account_unknown {account}`` and on Windows
                ``credential_missing {account}`` among them.
        """
        self._checked(PodmanConfig.from_dict(config))

    def apply(self, config: dict) -> None:
        """Make the account's machine run the declared containers.

        A declared container the checks refuse is left out, and the rest is
        applied.

        Args:
            config: The desired configuration.

        Raises:
            ModuleApplyError: When the configuration is refused, the machine
                cannot be made, sized or reached, or systemd in the machine
                refuses a unit; the first left-out container's refusal once
                the rest is applied.
            ModuleInstallPending: While the computer owes a restart.
        """
        with self._apply_lock:
            # A failed first apply after a start leaves every module unwritten.
            if self._written is None:
                self._written = PodmanConfig()
            parsed, refused = PodmanConfig.from_dict(config).without_refused(
                os_name=self._platform.os_name
            )
            settings = self._checked(parsed)
            if self._system.is_reboot_pending():
                raise ModuleInstallPending("reboot_required")
            record = self._record()
            if record and record.get("account") != settings.account:
                self._retire(record)
                record = {}
            # Held before the script runs: a start waits on the image pull,
            # and a report taken meanwhile lists a declared container.
            self._config = parsed
            if not settings.account:
                self._log("podman: no account is named; no machine runs")
                self._refuse_left_out(refused)
                return
            machine = self._machine_of(settings.account, settings.password)
            try:
                notes, disk_gib = self._prepare(machine, settings, record)
            except (OSError, subprocess.SubprocessError) as error:
                raise ModuleApplyError(
                    "apply_failed",
                    {"detail": command_detail(error)[:PODMAN_MACHINE_DETAIL_CHARS]},
                ) from error
            self._wait_for_machine(machine)
            try:
                rendered, context = self._rendered_config(machine, parsed)
            except (OSError, subprocess.SubprocessError) as error:
                raise ModuleApplyError(
                    "apply_failed",
                    {"detail": command_detail(error)[:PODMAN_MACHINE_DETAIL_CHARS]},
                ) from error
            self._config = rendered
            self._write_record(settings, disk_gib, rendered)
            script = PodmanMachineScriptRenderer(
                config=rendered, os_name=self._platform.os_name, context=context
            ).render()
            done = machine.shell(script)
            output = f"{done.stdout or ''}{done.stderr or ''}"
            if done.returncode != 0:
                raise ModuleApplyError(
                    "apply_failed",
                    {"detail": output.strip()[-PODMAN_MACHINE_DETAIL_CHARS:]},
                )
            self._written = rendered
            changed = [
                line[len(PODMAN_MACHINE_CHANGED_PREFIX) :]
                for line in output.splitlines()
                if line.startswith(PODMAN_MACHINE_CHANGED_PREFIX)
            ]
            notes.append(
                f"containers: {', '.join(changed)}"
                if changed
                else "containers unchanged"
            )
            self._log(f"podman: {'; '.join(notes)}")
            self._refuse_left_out(refused)

    def take_config(self, config: dict) -> None:
        """Take the configuration the state names, before any apply of it.

        Args:
            config: The module's configuration in the state.
        """
        self._wanted = PodmanConfig.from_dict(config)

    def take_source_sets(self, source_sets: dict) -> None:
        """Take the state's ``source_sets`` section.

        Args:
            source_sets: ``{name: {probe, sources, variables}}``.
        """
        self._source_sets = dict(source_sets)

    def stop(self) -> None:
        """Stop every declared and hub container, then the keeper, then the machine.

        Images and volumes stay. The keeper starts the machine again at
        the computer's next boot.

        Raises:
            ModuleApplyError: ``machine_set_failed`` when Podman cannot stop
                the machine; ``credential_invalid`` when Windows refuses the
                login.
            OSError: When the service manager cannot stop the keeper.
        """
        with self._apply_lock:
            record = self._record()
            if not record:
                return
            account = str(record.get("account", "") or "")
            password = str(record.get("password", "") or "")
            machine = self._machine_of(account, password)
            self._run_quietly(machine, machine_stop_script())
            # The keeper starts a stopped machine again within 30 seconds.
            account_service.stop(
                self._keeper_of(account, password), self._service_machine
            )
            try:
                machine.stop()
            finally:
                with self._lock:
                    self._reading = None
            self._log(f"podman: stopped the machine of {account}")

    def remove_configuration(self) -> None:
        """Take the containers' files out of the machine, remove the keeper and stop the machine.

        The machine, its disk, images and named volumes stay in the
        account's profile.
        """
        with self._apply_lock:
            self._config = None
            record = self._record()
            if not record:
                return
            script = PodmanMachineScriptRenderer(
                config=PodmanConfig(), os_name=self._platform.os_name
            ).render()
            self._run_quietly(self._machine_of_record(record), script)
            self._retire(record)

    def is_installing(self) -> bool:
        """Whether the computer owes the restart the install asked for."""
        return bool(self._system.is_reboot_pending())

    def install_wait(self) -> dict:
        """``reboot_required`` while the computer owes a restart, else nothing."""
        if self._system.is_reboot_pending():
            return {"code": "reboot_required", "params": {}}
        return {}

    def is_active(self) -> bool:
        """Whether the machine answers the read."""
        record = self._record()
        if not record:
            return False
        _command, info = self._read(self._machine_of_record(record))
        return info is not None

    def read_command(self) -> tuple:
        """The read's command, which a container's shell runs ``exec -it`` through.

        Returns:
            Podman's program with the ``--url`` and the ``--identity`` that
            reach root's Podman in the last applied account's machine, the
            port read now; empty while no machine was applied.

        Raises:
            ModuleApplyError: ``machine_unreachable`` when the machine's
                settings file names no port; ``account_unknown {account}``
                when the computer no longer has the account.
        """
        record = self._record()
        if not record:
            return ()
        machine = self._machine_of_record(record)
        try:
            return machine.read_command()
        except KeyError:
            raise ModuleApplyError(
                "account_unknown", {"account": machine.account}
            ) from None

    def details(self, recipe: dict) -> dict:
        """Every container in the machine, and the machine itself.

        Args:
            recipe: The module's recipe.

        Returns:
            ``{"containers", "mirrors", "version", "is_active", "machine"}``,
            each container as on Linux with its addresses empty and its
            folders written as the computer names them, and ``machine``
            ``{"account", "is_running", "cpus", "memory_gib", "disk_gib",
            "default_memory_gib"}``, the last the memory a 0 in the Run
            settings gives on this computer.
        """
        record = self._record()
        config = self._config or PodmanConfig()
        names = self._declared_names(record)
        binary = self._system.binary
        details = {
            "containers": [],
            "mirrors": list(config.mirrors),
            "version": podman_version(podman=(binary,)) if binary else "",
            "is_active": False,
            "machine": {
                "account": str(record.get("account", "") or ""),
                "is_running": False,
                "cpus": 0,
                "memory_gib": 0,
                "disk_gib": 0,
                "default_memory_gib": self._default_memory_gib(),
            },
        }
        if not record:
            return details
        machine = self._machine_of_record(record)
        details["machine"]["disk_gib"] = self._system.disk_gib(machine) or int(
            record.get("disk_gib") or 0
        )
        command, info = self._read(machine)
        if info is None:
            return details
        hub_names = self.hub_names()
        states = PodmanStatusReader(
            podman=command,
            has_unit=frozenset(_unit_names(names, hub_names)).__contains__,
            is_address_kept=False,
            host_volume=functools.partial(
                to_host_source, os_name=self._platform.os_name
            ),
            probe=self._probe,
        ).survey(declared_names=names, hub_names=hub_names)
        host = info.get("host") if isinstance(info.get("host"), dict) else {}
        details["containers"] = [vars(state) for state in states]
        details["is_active"] = True
        details["machine"].update(
            {
                "is_running": True,
                "cpus": _whole(host.get("cpus")),
                "memory_gib": round(_whole(host.get("memTotal")) / PODMAN_GIB),
            }
        )
        return details

    def journal_text(self, lines: int) -> list:
        """The keeper's log, then the agent's lines that name the module.

        Args:
            lines: How many lines to return at most.

        Returns:
            The lines, oldest first.
        """
        record = self._record()
        own = []
        if record:
            path = account_service.log_path(
                self.name, str(record["account"]), self._service_machine
            )
            own = self._read_source(path, functools.partial(file_tail, path, lines))
        return self._with_agent_lines(own, lines)

    def command(self, verb: str, args: dict, on_line=None) -> dict:
        """Run one of the module's verbs.

        Args:
            verb: ``control``, ``journal`` or ``validate``.
            args: ``{"name", "action"}`` for control, ``{"name"}`` for one
                container's journal, ``{"lines"}`` for the module's own.
            on_line: Called with each output line.

        Returns:
            ``{"exit_code", "code", "params", "output"}``.
        """
        if verb not in (PODMAN_COMMAND_CONTROL, PODMAN_COMMAND_JOURNAL) or (
            verb == PODMAN_COMMAND_JOURNAL and not args.get("name")
        ):
            return super().command(verb, args, on_line)
        name = str(args.get("name", ""))
        if not CONTAINER_NAME_PATTERN.match(name):
            return command_outcome(1, "container_name_invalid", {"name": name})
        record = self._record()
        if not record:
            return command_outcome(1, "container_unknown", {"name": name})
        machine = self._machine_of_record(record)
        if verb == PODMAN_COMMAND_JOURNAL:
            return self._journal_of(machine, name, on_line)
        action = str(args.get("action", ""))
        if action not in PODMAN_CONTAINER_ACTIONS:
            return command_outcome(
                1, "verb_unknown", {"module": self.name, "verb": action}
            )
        return self._control(machine, record, name, action)

    # --- what a container module asks of the engine ---

    def podman_command(self) -> tuple:
        """The podman command a container module reaches the engine with.

        Returns:
            The read's command into the last applied account's machine;
            empty while no machine was applied.

        Raises:
            ModuleApplyError: ``machine_unreachable`` when the machine's
                settings file names no port; ``account_unknown {account}``
                when the computer no longer has the account.
        """
        return self.read_command()

    def hub_names(self) -> dict:
        """The hub containers the last apply wrote into the machine, by module.

        Returns:
            Module name to its containers' names: the last apply's in this
            process, else the record's after a start.
        """
        if self._config is not None:
            return self._config.hub_names()
        held = self._record().get("hub_names")
        if not isinstance(held, dict):
            return {}
        return {
            str(module): [str(name) for name in names]
            for module, names in held.items()
            if isinstance(names, list)
        }

    def is_applied(self, module: str) -> bool:
        """Whether the last apply wrote a module's hub containers into the machine as the state names them.

        Args:
            module: The container module.

        Returns:
            True as well while no apply ran since the start.
        """
        if self._written is None or self._wanted is None:
            return True
        return self._written.hub_containers_of(
            module
        ) == self._wanted.hub_containers_of(module)

    def is_engine_active(self) -> bool:
        """Whether the machine answers the read."""
        return self.is_active()

    def drive_hub_containers(self, names: list, action: str) -> None:
        """Start, stop or restart the units of some hub containers in the machine.

        Args:
            names: The containers.
            action: ``start``, ``stop`` or ``restart``.

        Raises:
            ValueError: For an action outside those.
            ModuleApplyError: ``command_failed`` with systemd's words when it
                refuses, the machine's own code when it cannot be reached.
        """
        record = self._record()
        if not record or not names:
            return
        script = "".join(machine_control_script(name, action) for name in names)
        done = self._machine_of_record(record).shell(script)
        if done.returncode != 0:
            said = f"{done.stdout or ''}{done.stderr or ''}".strip()
            raise ModuleApplyError(
                "command_failed", {"detail": said[-PODMAN_MACHINE_DETAIL_CHARS:]}
            )

    def drop_hub_containers(self, module: str) -> None:
        """Stop and delete one module's hub containers' files in the machine, and forget them.

        Args:
            module: The container module.
        """
        names = self.hub_names().get(module, [])
        record = self._record()
        if record and names:
            self._run_quietly(
                self._machine_of_record(record),
                machine_drop_script(names),
            )
        if self._config is not None:
            self._config = self._config.with_hub_containers(
                [
                    container
                    for container in self._config.hub_containers
                    if container.module != module
                ]
            )
        if record:
            held = dict(record.get("hub_names") or {})
            held.pop(module, None)
            try:
                self._records.write({**record, "hub_names": held})
            except OSError as error:
                self._log(f"podman: the record was not written: {error}")
        self._page_ports.remove(module)

    def hub_journal(self, names: list, lines: int) -> list:
        """The journals of some hub containers' units in the machine, one after another.

        Args:
            names: The containers, in the order their journals come.
            lines: How many lines of each to read at most.

        Returns:
            The lines, each container's oldest first; empty while no
            machine was applied or the machine cannot be reached.
        """
        record = self._record()
        if not record or not names:
            return []
        script = "".join(machine_journal_script(name, lines) for name in names)
        try:
            done = self._machine_of_record(record).shell(script)
        except ModuleApplyError as error:
            self._log(f"podman: the journal was not read: {error}")
            return []
        return (done.stdout or "").splitlines()

    def page_port(self, module: str, name: str) -> int:
        """The loopback port a hub container's page is published at.

        Args:
            module: The container module.
            name: The hub container.

        Returns:
            The port its module's record keeps, picked the first time.

        Raises:
            OSError: When no port can be picked or kept.
        """
        return self._page_ports.port_for(module, name)

    def _record(self) -> dict:
        """The last apply's record, empty when none is held."""
        records = self._records.read_all()
        return records[0] if records else {}

    def _default_memory_gib(self) -> int:
        """The memory a 0 in the Run settings gives, the computer's memory read once."""
        if self._host_memory_gib <= 0:
            self._host_memory_gib = self._system.host_facts()[1]
        return default_memory_gib(self._host_memory_gib)

    def _machine_of(self, account: str, password: str) -> PodmanMachine:
        return self._machine_class(
            platform=self._platform,
            account=account,
            password=password,
            binary=self._system.binary,
            provider=self._system.provider,
            environment=self._system.machine_environment(account),
        )

    def _machine_of_record(self, record: dict) -> PodmanMachine:
        return self._machine_of(
            str(record.get("account", "") or ""), str(record.get("password", "") or "")
        )

    def _keeper_of(self, account: str, password: str):
        return keeper_service(
            os_name=self._platform.os_name,
            module_dir=self._service_machine.module_dir,
            account=account,
            password=password,
            binary=self._system.binary,
            provider=self._system.provider,
        )

    def _checked(self, parsed: PodmanConfig) -> PodmanMachineSettings:
        """Check a parsed configuration against this computer.

        Returns:
            Its Run settings, empty where the state named none.

        Raises:
            ModuleApplyError: Naming the first problem found.
        """
        settings = parsed.machine or PodmanMachineSettings()
        host_cpus, host_memory_gib = self._system.host_facts()
        disk_gib_now = 0
        is_known = True
        if settings.account:
            try:
                self._service_machine.lookup_account(settings.account)
            except KeyError:
                is_known = False
            if is_known:
                machine = self._machine_of(settings.account, settings.password)
                disk_gib_now = self._disk_now(machine, self._record())
        parsed.validate(
            os_name=self._platform.os_name,
            host_cpus=host_cpus,
            host_memory_gib=host_memory_gib,
            disk_gib_now=disk_gib_now,
        )
        if not is_known:
            raise ModuleApplyError("account_unknown", {"account": settings.account})
        if (
            settings.account
            and self._platform.os_name == "windows"
            and not settings.password
        ):
            raise ModuleApplyError("credential_missing", {"account": settings.account})
        return settings

    def _refuse_left_out(self, refused: list) -> None:
        """Log the declared containers an apply left out, and raise the first one's refusal.

        Args:
            refused: ``(name, error)`` per container left out.

        Raises:
            ModuleApplyError: The first container's refusal.
        """
        if not refused:
            return
        self._log("podman: left out " + ", ".join(name for name, _ in refused))
        raise refused[0][1]

    def _prepare(
        self, machine: PodmanMachine, settings: PodmanMachineSettings, record: dict
    ) -> tuple:
        """Make the machine, root's and its size, and run its keeper.

        Returns:
            ``(notes, disk_gib)``: what changed, and the size of the disk
            as far as it is known.

        Raises:
            ModuleApplyError: ``machine_image_missing``, the machine's own
                codes, or the system applier's.
            OSError: When the keeper cannot be written.
            subprocess.SubprocessError: When the service manager refuses.
        """
        host_cpus, host_memory_gib = self._system.host_facts()
        cpus = settings.cpus or max(1, host_cpus // 2)
        memory_gib = settings.memory_gib or default_memory_gib(host_memory_gib)
        keeper = self._keeper_of(settings.account, settings.password)
        notes = []
        if not machine.is_present():
            disk_gib = settings.disk_gib or PODMAN_MACHINE_DEFAULT_DISK_GIB
            machine.init(
                self._image_path(), cpus=cpus, memory_gib=memory_gib, disk_gib=disk_gib
            )
            if not machine.is_sized_at_init:
                self._size_new_machine(
                    machine, cpus=cpus, memory_gib=memory_gib, disk_gib=disk_gib
                )
            notes.append(f"made the machine of {settings.account}")
        else:
            disk_gib = self._disk_now(machine, record)
            state = machine.inspect()
            is_resized = (
                not record
                or record.get("cpus") != settings.cpus
                or record.get("memory_gib") != settings.memory_gib
                or bool(settings.disk_gib and settings.disk_gib != disk_gib)
            )
            is_set = not state.is_rootful or state.has_user_mode_networking
            if is_set or is_resized:
                # The keeper would start the machine in the middle of the change.
                account_service.stop(keeper, self._service_machine)
            if is_set and state.is_running:
                machine.stop()
            if not state.is_rootful:
                machine.set_rootful()
                notes.append("made the machine rootful")
            if state.has_user_mode_networking:
                machine.set_nat_networking()
                self._system.terminate(machine)
                notes.append("set the machine back to WSL's NAT networking")
            if is_resized:
                self._system.halt(machine)
                self._system.write_resources(machine, cpus=cpus, memory_gib=memory_gib)
                if settings.disk_gib > disk_gib:
                    self._system.resize_disk(machine, disk_gib=settings.disk_gib)
                    disk_gib = settings.disk_gib
                notes.append("sized the machine")
        is_changed = account_service.write(keeper, self._service_machine)
        account_service.start(keeper, self._service_machine, is_restart=is_changed)
        return notes, disk_gib

    def _size_new_machine(
        self, machine: PodmanMachine, *, cpus: int, memory_gib: int, disk_gib: int
    ) -> None:
        """Size a machine the init just made, and remove it when the sizing fails.

        Raises:
            ModuleApplyError: The step's own code when the write or the
                resize fails.
        """
        try:
            self._system.write_resources(machine, cpus=cpus, memory_gib=memory_gib)
            self._system.resize_disk(machine, disk_gib=disk_gib)
        except ModuleApplyError:
            try:
                machine.remove()
            except ModuleApplyError as error:
                self._log(
                    f"podman: the new machine of {machine.account} was not removed: {error}"
                )
            raise

    def _wait_for_machine(self, machine: PodmanMachine) -> None:
        """Wait until the machine answers the read, which the keeper's start brings.

        Raises:
            ModuleApplyError: ``machine_unreachable`` with the last answer
                when it does not answer in time.
        """
        deadline = self._clock() + PODMAN_MACHINE_API_WAIT_S
        while True:
            try:
                command = machine.read_command()
                info = machine.info(command)
            except ModuleApplyError:
                if self._clock() >= deadline:
                    raise
            else:
                with self._lock:
                    self._reading = (self._clock(), machine.account, command, info)
                return
            self._sleep(PODMAN_MACHINE_API_POLL_S)

    def _read(self, machine: PodmanMachine) -> tuple:
        """The read's command and what the machine answered, kept a few seconds.

        The port is read once per reading, before its first command.

        Returns:
            ``(command, info)``; ``info`` is None when the machine did not
            answer, and ``command`` empty when it has no port.
        """
        with self._lock:
            reading = self._reading
        if (
            reading is not None
            and reading[1] == machine.account
            and self._clock() - reading[0] < PODMAN_MACHINE_INFO_TTL_S
        ):
            return reading[2], reading[3]
        command: tuple = ()
        info = None
        try:
            command = machine.read_command()
            info = machine.info(command)
        except (ModuleApplyError, KeyError):
            pass
        with self._lock:
            self._reading = (self._clock(), machine.account, command, info)
        return command, info

    def _journal_of(self, machine: PodmanMachine, name: str, on_line) -> dict:
        """One container's journal, read in the machine by the root script."""
        try:
            done = machine.shell(machine_journal_script(name, PODMAN_JOURNAL_LINES))
        except ModuleApplyError as error:
            return command_outcome(1, error.code, error.params)
        lines = (done.stdout or done.stderr or "").splitlines()
        for line in lines:
            if on_line is not None:
                on_line(line)
        return command_outcome(0, output="\n".join(lines))

    def _control(
        self, machine: PodmanMachine, record: dict, name: str, action: str
    ) -> dict:
        """Start, stop or restart one container through its rightful owner.

        A declared container goes through systemd in the machine; one a
        person started by hand through the read's command.
        """
        names = self._declared_names(record)
        hub_names = self.hub_names()
        command, info = self._read(machine)
        if info is None:
            return command_outcome(1, "machine_unreachable", {"detail": ""})
        states = PodmanStatusReader(
            podman=command,
            has_unit=frozenset(_unit_names(names, hub_names)).__contains__,
        ).survey(declared_names=names, hub_names=hub_names)
        state = next((entry for entry in states if entry.name == name), None)
        if state is None:
            return command_outcome(1, "container_unknown", {"name": name})
        try:
            if state.source != PODMAN_SOURCE_MANUAL:
                done = machine.shell(machine_control_script(name, action))
                if done.returncode != 0:
                    said = f"{done.stdout or ''}{done.stderr or ''}".strip()
                    return command_outcome(
                        1,
                        "command_failed",
                        {"detail": said[-PODMAN_MACHINE_DETAIL_CHARS:]},
                    )
            else:
                machine.control(name, action)
        except ModuleApplyError as error:
            return command_outcome(1, error.code, error.params)
        except (OSError, subprocess.SubprocessError) as error:
            return command_outcome(
                1,
                "command_failed",
                {"detail": command_detail(error)[:PODMAN_MACHINE_DETAIL_CHARS]},
            )
        return command_outcome(0, output=f"{action} {name}\n")

    def _retire(self, record: dict) -> None:
        """Remove one account's keeper, stop its machine and forget its record.

        The machine, its images and named volumes stay as they are.
        """
        account = str(record.get("account", "") or "")
        password = str(record.get("password", "") or "")
        try:
            account_service.remove(
                self._keeper_of(account, password), self._service_machine
            )
        except (OSError, ModuleApplyError) as error:
            self._log(f"podman: the keeper of {account} was not removed: {error}")
        try:
            self._machine_of(account, password).stop()
        except (ModuleApplyError, KeyError, OSError, PlatformUnsupportedError) as error:
            self._log(f"podman: the machine of {account} was not stopped: {error}")
        self._records.remove(account)
        with self._lock:
            self._reading = None
        self._log(f"podman: stopped the machine of {account}")

    def _run_quietly(self, machine: PodmanMachine, script: str) -> None:
        """Run one root script, logging a failure instead of raising it."""
        try:
            done = machine.shell(script)
        except (ModuleApplyError, KeyError, PlatformUnsupportedError) as error:
            self._log(f"podman: the machine did not take the script: {error}")
            return
        if done.returncode != 0:
            said = f"{done.stdout or ''}{done.stderr or ''}".strip()
            self._log(
                f"podman: the machine's script failed: {said[-PODMAN_MACHINE_DETAIL_CHARS:]}"
            )

    def _disk_now(self, machine: PodmanMachine, record: dict) -> int:
        """The size of the machine's disk now: the system's reading, else the last apply's."""
        now = self._system.disk_gib(machine)
        if not now and record and record.get("account") == machine.account:
            now = int(record.get("disk_gib") or 0)
        return now

    def _image_path(self) -> str:
        """The kept machine image.

        Raises:
            ModuleApplyError: ``machine_image_missing`` when none is kept.
        """
        for kind in PODMAN_MACHINE_IMAGE_KINDS:
            path = kept_artifact_path(
                self._service_machine.module_dir,
                PODMAN_MACHINE_IMAGE_ARTIFACT,
                kind,
                self._join,
            )
            if os.path.isfile(path):
                return path
        raise ModuleApplyError("machine_image_missing", {})

    def _write_record(
        self, settings: PodmanMachineSettings, disk_gib: int, parsed: PodmanConfig
    ) -> None:
        """Keep the last apply: the account, its login, the Run settings, the disk's size, the declared names and the hub names by module.

        Raises:
            ModuleApplyError: ``apply_failed`` when the record cannot be written.
        """
        try:
            self._records.write(
                {
                    "account": settings.account,
                    "password": settings.password,
                    "cpus": settings.cpus,
                    "memory_gib": settings.memory_gib,
                    "disk_gib": disk_gib,
                    "names": parsed.declared_names,
                    "hub_names": parsed.hub_names(),
                }
            )
        except OSError as error:
            raise ModuleApplyError(
                "apply_failed", {"detail": str(error)[:PODMAN_MACHINE_DETAIL_CHARS]}
            ) from error

    def _declared_names(self, record: dict) -> list:
        """The declared containers' names: the configuration's, else the record's after a restart."""
        if self._config is not None:
            return self._config.declared_names
        return [str(name) for name in record.get("names") or []]

    def _rendered_config(self, machine: PodmanMachine, parsed: PodmanConfig) -> tuple:
        """The configuration this apply writes into the machine, and what its files name.

        Returns:
            ``(config, context)``: the configuration with the hub containers
            whose module has every image in the machine's store, and their
            stored images, page ports and source sets' sources. The
            machine's own Podman maps ``host.containers.internal``, so no
            gateway is named.

        Raises:
            ModuleApplyError: ``machine_unreachable`` when the machine's
                settings file names no port.
            subprocess.CalledProcessError: If Podman refuses to make a
                network.
            OSError: When Podman cannot start or a page port cannot be kept.
        """
        if not parsed.hub_containers:
            return parsed, PodmanRenderContext()
        command = machine.read_command()
        ready, images = ready_hub_containers(parsed, image_references(podman=command))
        networks = []
        for container in ready:
            if container.network not in networks:
                networks.append(container.network)
        for network in networks:
            if ensure_network(network, podman=command):
                self._log(f"podman: made the network {network}")
        page_ports = {
            container.name: self.page_port(container.module, container.name)
            for container in ready
            if container.page_port
        }
        set_names = []
        for container in ready:
            set_names += [
                name for name in container.source_sets if name not in set_names
            ]
        sources, variables = fastest_sources(set_names, self._source_sets)
        context = PodmanRenderContext(
            images=images, page_ports=page_ports, sources=sources, variables=variables
        )
        return parsed.with_hub_containers(ready), context
