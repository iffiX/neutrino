"""Making the declared and hub containers true on the machine, and reading what runs.

Declared and hub containers live as units with their environment files and
are driven through systemd; containers someone started by hand at a shell
are still listed and still controllable, through podman directly. Each
container's owner is read in one order: the label ``neutrino.module`` makes
it a hub container of that module, a declared name makes it declared, and
any other is a person's own.

Not pure: writes unit and environment files, runs podman and drives systemd.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import ipaddress
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field

from neutrino_agent.modules.podman.config import PodmanConfig
from neutrino_agent.modules.podman.constants import (
    PODMAN_ANONYMOUS_VOLUME_PATTERN,
    PODMAN_BINARY,
    PODMAN_CNI_DIR,
    PODMAN_CNI_SUFFIX,
    PODMAN_CNI_VERSION,
    PODMAN_CONTAINER_ACTIONS,
    PODMAN_ENV_DIR,
    PODMAN_ENV_DIR_MODE,
    PODMAN_ENV_FILE_MODE,
    PODMAN_ENV_SUFFIX,
    PODMAN_GENERATED_MARKER,
    PODMAN_MODULE_LABEL,
    PODMAN_PROBE_ADDRESS,
    PODMAN_PROTOCOL_TCP,
    PODMAN_QUADLET_DIRS,
    PODMAN_QUADLET_SUFFIX,
    PODMAN_REGISTRIES_CONF_PATH,
    PODMAN_SOURCE_DECLARED,
    PODMAN_SOURCE_HUB,
    PODMAN_SOURCE_MANUAL,
    PODMAN_UNIT_DIR,
    PODMAN_UNIT_FILE_MODE,
    PODMAN_UNIT_SUFFIX,
    PODMAN_VOLUME_MOUNT,
)
from neutrino_agent.modules.podman.renderer import source_neutral
from neutrino_agent.modules.shared import source_fetch
from neutrino_agent.modules.shared.subprocess_run import run, unit_state

# The order a survey lists the containers in, by where each comes from.
SOURCE_ORDER = (PODMAN_SOURCE_DECLARED, PODMAN_SOURCE_HUB, PODMAN_SOURCE_MANUAL)


@dataclass
class PodmanContainerState:
    """One container as podman sees it right now.

    Attributes:
        name: The container's name.
        image: The image it runs.
        status: Podman's own words, for example ``Up 2 hours``.
        is_running: Whether it is running.
        source: Where it comes from: ``hub`` for one a container module
            runs, ``declared`` for one the hub declares, ``manual`` for one
            a person started by hand.
        module: The module its label ``neutrino.module`` names; empty for
            any other container.
        host_ports: The published host ports.
        ports: Every published port as ``host:container``, from inspect.
        volumes: Every mount as ``source:destination``, from inspect.
        environment: The container's environment, ``KEY=value`` each;
            empty for a hub container, whose environment holds its
            module's secrets.
        has_unit: Whether a unit file this machine renders stands for it.
        host_bindings: Each published host port with the host address it
            is published on, its protocol and what answers on it,
            ``{"address", "port", "protocol", "detected"}``, the protocol
            ``tcp`` or ``udp``, the address empty for every address, and
            ``detected`` ``http``, ``https`` or ``tcp`` once the service
            probe found it on a running container's TCP port, else empty.
    """

    name: str
    image: str
    status: str
    is_running: bool
    source: str
    module: str = ""
    host_ports: list = field(default_factory=list)
    ports: list = field(default_factory=list)
    volumes: list = field(default_factory=list)
    environment: list = field(default_factory=list)
    has_unit: bool = False
    host_bindings: list = field(default_factory=list)


def podman_version(*, podman: tuple = (PODMAN_BINARY,)) -> str:
    """The version podman prints, empty when it cannot run.

    Args:
        podman: The podman command: the program and the options before
            its verb.

    Returns:
        The last word of ``--version``'s answer.
    """
    try:
        result = run([*podman, "--version"], is_checked=False, timeout_s=30)
    except (OSError, subprocess.SubprocessError):
        return ""
    words = result.stdout.split()
    return words[-1] if result.is_success and words else ""


def ensure_network(name: str, *, podman: tuple = (PODMAN_BINARY,)) -> bool:
    """Make one network when Podman has none of that name.

    Where Podman's backend is CNI, as with Podman 3.4, the new network's
    ``cniVersion`` is set to the one its plugins read.

    Args:
        name: The network.
        podman: The podman command: the program and the options before
            its verb.

    Returns:
        True when the network was made now.

    Raises:
        subprocess.CalledProcessError: If podman refuses to make it.
        OSError: When podman cannot start.
    """
    found = run([*podman, "network", "exists", name], is_checked=False, timeout_s=30)
    if found.is_success:
        return False
    run([*podman, "network", "create", name], timeout_s=60)
    if podman == (PODMAN_BINARY,):
        fix_cni_version(os.path.join(PODMAN_CNI_DIR, name + PODMAN_CNI_SUFFIX))
    return True


def fix_cni_version(path: str) -> bool:
    """Set a CNI network's ``cniVersion`` to the one Podman 3.4's plugins read.

    Args:
        path: The network's ``.conflist``; a missing one is netavark's
            network, which has none.

    Returns:
        True when the file was rewritten.

    Raises:
        OSError: When the file is there and cannot be rewritten.
    """
    text = _read(path)
    if text is None:
        return False
    try:
        held = json.loads(text)
    except ValueError:
        return False
    if not isinstance(held, dict) or held.get("cniVersion") == PODMAN_CNI_VERSION:
        return False
    held["cniVersion"] = PODMAN_CNI_VERSION
    with open(path + ".new", "w", encoding="utf-8") as stream:
        json.dump(held, stream, indent=2)
        stream.write("\n")
    os.replace(path + ".new", path)
    return True


def network_gateway(name: str, *, podman: tuple = (PODMAN_BINARY,)) -> str:
    """The gateway address of one network, as ``podman network inspect`` gives it.

    Args:
        name: The network.
        podman: The podman command.

    Returns:
        The first gateway netavark's ``subnets`` or CNI's bridge ``ipam``
        names; empty when Podman cannot say.
    """
    try:
        result = run(
            [*podman, "network", "inspect", name], is_checked=False, timeout_s=30
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if not result.is_success:
        return ""
    try:
        found = json.loads(result.stdout or "[]")
    except ValueError:
        return ""
    entry = found[0] if isinstance(found, list) and found else found
    return _gateway_of(entry) if isinstance(entry, dict) else ""


def image_references(*, podman: tuple = (PODMAN_BINARY,)) -> set:
    """Every image reference with a digest in Podman's store.

    Args:
        podman: The podman command.

    Returns:
        ``<repository>@<digest>`` for each name and digest of each image,
        the digest of the index it was pulled by among them; empty when
        Podman cannot say.
    """
    try:
        result = run(
            [*podman, "images", "--format", "json"], is_checked=False, timeout_s=60
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    if not result.is_success:
        return set()
    try:
        entries = json.loads(result.stdout or "[]")
    except ValueError:
        return set()
    references: set = set()
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        for key in ("RepoDigests", "Names"):
            for name in entry.get(key) or []:
                if isinstance(name, str) and "@" in name:
                    references.add(name)
    return references


def stored_reference(digest: str, sources: list, references: set) -> str:
    """The reference an image with a digest is stored under, among its sources.

    Args:
        digest: The image's digest.
        sources: Its references with no tag, in the module's order.
        references: What :func:`image_references` read.

    Returns:
        ``<source>@<digest>`` for the first source the store holds it
        under; empty when the store holds it under none.
    """
    for source in sources:
        reference = f"{source}@{digest}"
        if reference in references:
            return reference
    return ""


def ready_hub_containers(config: PodmanConfig, references: set) -> tuple:
    """The hub containers whose module has every image in the store.

    Args:
        config: The configuration.
        references: The store's references, as
            :func:`~neutrino_agent.modules.podman.applier.image_references`
            reads them.

    Returns:
        ``(ready, images)``: the hub containers of each module all of whose
        images the store holds, in order, and each one's stored reference
        by name. A module with one image missing is left out whole.
    """
    images = {}
    missing: set = set()
    for container in config.hub_containers:
        reference = stored_reference(container.digest, container.sources, references)
        if reference:
            images[container.name] = reference
        else:
            missing.add(container.module)
    ready = [
        container
        for container in config.hub_containers
        if container.module not in missing
    ]
    return ready, {container.name: images[container.name] for container in ready}


def fastest_sources(names, source_sets: dict, *, probe_one=source_fetch.probe) -> tuple:
    """Each named source set's fastest source, and its variables.

    Args:
        names: The sets the rendered containers list.
        source_sets: The state's ``source_sets`` section, ``{name: {probe,
            sources, variables}}``.
        probe_one: Called with ``url, source=``; returns a probe.

    Returns:
        ``(sources, variables)``, each by set name, for every named set the
        section holds with variables; a set none of whose sources answers
        names its first. A set with no variables is left unprobed, for the
        module's own step to rank.
    """
    sources = {}
    variables = {}
    for name in names:
        held = source_sets.get(name)
        if not isinstance(held, dict) or not held.get("sources"):
            continue
        if not held.get("variables"):
            continue
        order = source_fetch.rank_set(
            [str(source) for source in held["sources"]],
            probe_path=str(held.get("probe", "") or "/"),
            probe_one=probe_one,
        )
        sources[name] = order[0]
        variables[name] = [str(variable) for variable in held.get("variables") or []]
    return sources, variables


class PodmanUnitApplier:
    """Installs rendered container units and environment files, and reconciles systemd with them."""

    def __init__(
        self,
        *,
        directory: str = PODMAN_UNIT_DIR,
        env_directory: str = PODMAN_ENV_DIR,
        quadlet_directories: tuple = PODMAN_QUADLET_DIRS,
    ):
        """
        Args:
            directory: Where the units are written.
            env_directory: Where the environment files are written, root
                only.
            quadlet_directories: Where earlier builds wrote Quadlet files,
                which an apply stops and removes.
        """
        self._directory = directory
        self._env_directory = env_directory
        self._quadlet_directories = tuple(quadlet_directories)

    @property
    def directory(self) -> str:
        """Where this applier writes the units."""
        return self._directory

    def apply(
        self,
        rendered: dict,
        environments: dict,
        *,
        autostart_names: list,
        source_keys: "dict | None" = None,
    ) -> str:
        """Write the rendered files, drop stale ones, recreate what changed,
        and start what starts with the box.

        Only files carrying the generated marker are ever removed: a file a
        person wrote by hand beside these is theirs. Each Quadlet file an
        earlier build wrote is stopped and removed first, and its container
        started again at the end when its unit was active. A unit is
        enabled when its container starts with the box and disabled when it
        does not. An environment file whose only change is a source set's
        value is kept as it is.

        Args:
            rendered: Unit contents keyed by file name, ``<name>.service``.
            environments: Environment file contents keyed by file name,
                ``<name>.env``.
            autostart_names: Containers that should be running; a changed
                one of these is restarted even if it was stopped, and an
                unchanged one that is not active is started.
            source_keys: Container name to the variables a source set fills
                in; None or a name it does not hold has none.

        Returns:
            A short summary of what changed.

        Raises:
            subprocess.CalledProcessError: If systemd refuses a unit.
            OSError: When a file cannot be written.
        """
        names = [file_name[: -len(PODMAN_UNIT_SUFFIX)] for file_name in rendered]
        retired, was_active = self._retire_quadlet()
        was_active = [name for name in was_active if name in names]
        os.makedirs(self._directory, exist_ok=True)
        os.makedirs(self._env_directory, mode=PODMAN_ENV_DIR_MODE, exist_ok=True)
        os.chmod(self._env_directory, PODMAN_ENV_DIR_MODE)
        keys = dict(source_keys or {})
        changed_names = []
        notes = [f"-{file_name}" for file_name in retired]
        for name in names:
            unit_name = name + PODMAN_UNIT_SUFFIX
            env_name = name + PODMAN_ENV_SUFFIX
            is_changed = _write_changed(
                os.path.join(self._directory, unit_name),
                rendered[unit_name],
                mode=PODMAN_UNIT_FILE_MODE,
            )
            if is_changed:
                notes.append(unit_name)
            if _write_changed(
                os.path.join(self._env_directory, env_name),
                environments.get(env_name, PODMAN_GENERATED_MARKER + "\n"),
                mode=PODMAN_ENV_FILE_MODE,
                kept_keys=keys.get(name, ()),
            ):
                is_changed = True
                notes.append(env_name)
            if is_changed:
                changed_names.append(name)
        for file_name in self.generated_names():
            if file_name in rendered:
                continue
            name = file_name[: -len(PODMAN_UNIT_SUFFIX)]
            self._retire_unit(name)
            notes.append(f"-{file_name}")
        for name in self._stale_environments(names):
            with contextlib.suppress(OSError):
                os.unlink(os.path.join(self._env_directory, name + PODMAN_ENV_SUFFIX))
            notes.append(f"-{name}{PODMAN_ENV_SUFFIX}")
        for name in names:
            verb = "enable" if name in autostart_names else "disable"
            run(["systemctl", verb, "--no-reload", name + PODMAN_UNIT_SUFFIX])
        run(["systemctl", "daemon-reload"])
        for name in names:
            unit = name + PODMAN_UNIT_SUFFIX
            if name in changed_names:
                if name in autostart_names or unit_state(unit) == "active":
                    run(["systemctl", "restart", unit], timeout_s=900)
            elif name in autostart_names and unit_state(unit) != "active":
                run(["systemctl", "start", unit], timeout_s=900)
        for name in was_active:
            unit = name + PODMAN_UNIT_SUFFIX
            if unit_state(unit) != "active":
                run(["systemctl", "start", unit], timeout_s=900)
        if not notes:
            return "containers unchanged"
        return f"containers: {', '.join(sorted(notes))}"

    def drive(self, names: list, action: str) -> None:
        """Start, stop or restart the units of some containers, each that has a file.

        Args:
            names: The containers.
            action: One of :data:`PODMAN_CONTAINER_ACTIONS`.

        Raises:
            ValueError: For an action outside the list.
            subprocess.CalledProcessError: If systemd refuses a unit.
        """
        if action not in PODMAN_CONTAINER_ACTIONS:
            raise ValueError(action)
        owned = set(self.generated_names())
        for name in names:
            if name + PODMAN_UNIT_SUFFIX in owned:
                run(["systemctl", action, name + PODMAN_UNIT_SUFFIX], timeout_s=900)

    def remove(self, names: list) -> list:
        """Stop the units of some containers and delete their generated files.

        Args:
            names: The containers.

        Returns:
            The names whose unit was removed.
        """
        owned = set(self.generated_names())
        removed = []
        for name in names:
            if name + PODMAN_UNIT_SUFFIX not in owned:
                continue
            self._retire_unit(name)
            removed.append(name)
        if removed:
            run(["systemctl", "daemon-reload"], is_checked=False)
        return removed

    def stop_all(self) -> None:
        """Stop every generated unit, leaving its files in place."""
        for file_name in self.generated_names():
            run(["systemctl", "stop", file_name], is_checked=False)

    def remove_all(self) -> None:
        """Stop and disable every generated unit, and delete its files."""
        for file_name in self.generated_names():
            self._retire_unit(file_name[: -len(PODMAN_UNIT_SUFFIX)])
        for name in self._stale_environments(()):
            with contextlib.suppress(OSError):
                os.unlink(os.path.join(self._env_directory, name + PODMAN_ENV_SUFFIX))

    def generated_names(self) -> list:
        """The units this applier owns in its directory, ``<name>.service`` each."""
        return _marked_files(self._directory, PODMAN_UNIT_SUFFIX)

    def _stale_environments(self, names) -> list:
        """The containers whose marked environment file is there and whose name is not among these."""
        return [
            file_name[: -len(PODMAN_ENV_SUFFIX)]
            for file_name in _marked_files(self._env_directory, PODMAN_ENV_SUFFIX)
            if file_name[: -len(PODMAN_ENV_SUFFIX)] not in names
        ]

    def _retire_unit(self, name: str) -> None:
        """Stop and disable one container's unit, and delete its unit and environment file."""
        unit = name + PODMAN_UNIT_SUFFIX
        run(["systemctl", "stop", unit], is_checked=False)
        run(["systemctl", "disable", "--no-reload", unit], is_checked=False)
        for path in (
            os.path.join(self._directory, unit),
            os.path.join(self._env_directory, name + PODMAN_ENV_SUFFIX),
        ):
            with contextlib.suppress(OSError):
                os.unlink(path)

    def _retire_quadlet(self) -> tuple:
        """Stop and delete each marked Quadlet file an earlier build wrote.

        Returns:
            ``(removed, was_active)``: the files removed, and the containers
            whose unit was active before it stopped.
        """
        removed = []
        was_active = []
        for directory in self._quadlet_directories:
            for file_name in _marked_files(directory, PODMAN_QUADLET_SUFFIX):
                name = file_name[: -len(PODMAN_QUADLET_SUFFIX)]
                unit = name + PODMAN_UNIT_SUFFIX
                if unit_state(unit) == "active":
                    was_active.append(name)
                run(["systemctl", "stop", unit], is_checked=False)
                with contextlib.suppress(OSError):
                    os.unlink(os.path.join(directory, file_name))
                removed.append(file_name)
        return removed, was_active


class PodmanRegistriesApplier:
    """Installs the docker.io mirror drop-in, or removes it."""

    def apply(self, rendered: str) -> str:
        """Write the drop-in, or take it away when no mirrors are declared.

        Args:
            rendered: The drop-in text, empty for none.

        Returns:
            A short summary of what changed.
        """
        path = PODMAN_REGISTRIES_CONF_PATH
        if rendered == "":
            if os.path.isfile(path):
                os.unlink(path)
                return "mirrors removed"
            return "no mirrors"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if _read(path) == rendered:
            return "mirrors unchanged"
        with open(path, "w", encoding="utf-8") as stream:
            stream.write(rendered)
        return "mirrors updated"


class PodmanStatusReader:
    """Reads what podman is running right now."""

    def __init__(
        self,
        *,
        podman: tuple = (PODMAN_BINARY,),
        has_unit=None,
        is_address_kept: bool = True,
        host_volume=None,
        probe=None,
    ):
        """
        Args:
            podman: The podman command: the program and the options before
                its verb, such as ``--url`` and ``--identity`` reaching a
                Podman machine.
            has_unit: Called with a container's name, whether a unit file
                stands for it; None reads this machine's unit directories.
            is_address_kept: Whether a host binding keeps the address podman
                publishes the port on; False reads every binding as on every
                address.
            host_volume: Called with a mount's source as podman names it,
                the source as the configuration writes it; None keeps it.
            probe: The runner's
                :class:`~neutrino_agent.modules.podman.service_probe.PodmanServiceProbe`,
                which fills each running container's ``detected``; None
                leaves it empty.
        """
        self._podman = tuple(podman)
        self._has_unit = has_unit
        self._is_address_kept = is_address_kept
        self._host_volume = host_volume
        self._probe = probe

    def survey(self, *, declared_names: list, hub_names: "dict | None" = None) -> list:
        """List every container, running or not, each with its owner.

        Args:
            declared_names: The names the hub declares.
            hub_names: The hub containers' names by module, as the last
                apply rendered them; None names none.

        Returns:
            One :class:`PodmanContainerState` per container podman knows,
            and one per declared or hub container that has no container
            yet; declared ones first, then hub ones, then a person's own.
            Empty when podman is absent.
        """
        try:
            result = run(
                [*self._podman, "ps", "-a", "--format", "json"],
                is_checked=False,
                timeout_s=30,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        if not result.is_success:
            return []
        try:
            entries = json.loads(result.stdout or "[]")
        except ValueError:
            return []
        has_unit = self._has_unit if self._has_unit is not None else has_unit_file
        states = []
        probed = []
        inspected = self._inspect(
            [str((entry.get("Names") or ["?"])[0]) for entry in entries]
        )
        for entry in entries:
            names = entry.get("Names") or ["?"]
            detail = inspected.get(names[0], {})
            is_running = entry.get("State", "") == "running"
            bindings = _host_bindings(
                entry.get("Ports") or [], is_address_kept=self._is_address_kept
            )
            if is_running:
                probed += _probed_bindings(entry, bindings)
            module = _module_label(entry, detail)
            states.append(
                PodmanContainerState(
                    name=names[0],
                    image=entry.get("Image", ""),
                    status=entry.get("Status", ""),
                    is_running=is_running,
                    source=owner_of(names[0], module, declared_names),
                    module=module,
                    host_ports=_host_ports(entry.get("Ports") or []),
                    host_bindings=bindings,
                    ports=_inspected_ports(detail),
                    volumes=_inspected_volumes(detail, host_volume=self._host_volume),
                    environment=[] if module else _inspected_environment(detail),
                    has_unit=has_unit(names[0]),
                )
            )
        if self._probe is not None:
            found = self._probe.detected(
                [
                    (key, _probe_address(binding["address"]), binding["port"])
                    for key, binding in probed
                ]
            )
            for key, binding in probed:
                binding["detected"] = found.get(key, "")
        # A declared or hub container with autostart off exists only as a
        # unit until its first start, so podman has no row for it yet.
        present = {state.name for state in states}
        waiting = [(name, "") for name in declared_names]
        for module, names in (hub_names or {}).items():
            waiting += [(name, str(module)) for name in names]
        for name, module in waiting:
            if name in present:
                continue
            present.add(name)
            states.append(
                PodmanContainerState(
                    name=name,
                    image="",
                    status="not created yet",
                    is_running=False,
                    source=PODMAN_SOURCE_HUB if module else PODMAN_SOURCE_DECLARED,
                    module=module,
                )
            )
        states.sort(key=_by_source)
        return states

    def _inspect(self, names: list) -> dict:
        """What ``podman inspect`` says of each container, by name.

        Returns:
            The inspect object per name; empty when podman cannot be asked.
        """
        if not names:
            return {}
        try:
            result = run(
                [*self._podman, "inspect", "--type", "container"] + names,
                is_checked=False,
                timeout_s=30,
            )
        except (OSError, subprocess.SubprocessError):
            return {}
        if not result.is_success:
            return {}
        try:
            entries = json.loads(result.stdout or "[]")
        except ValueError:
            return {}
        inspected = {}
        for entry in entries:
            if isinstance(entry, dict):
                inspected[str(entry.get("Name", "")).lstrip("/")] = entry
        return inspected


def has_unit_file(name: str) -> bool:
    """Whether a rendered unit stands for one container.

    Args:
        name: The container's name.

    Returns:
        True when the unit directory holds its file.
    """
    return os.path.isfile(os.path.join(PODMAN_UNIT_DIR, name + PODMAN_UNIT_SUFFIX))


class PodmanContainerController:
    """Starts and stops containers, each through its rightful owner."""

    def control(self, name: str, action: str, *, source: str) -> None:
        """Start, stop or restart one container.

        A declared or hub container is driven through systemd, which
        supervises it; one a person started by hand has no unit, so podman
        is the only handle.

        Args:
            name: The container's name.
            action: One of :data:`PODMAN_CONTAINER_ACTIONS`.
            source: Where it comes from, ``hub``, ``declared`` or ``manual``.

        Raises:
            ValueError: For an action outside the list.
            subprocess.CalledProcessError: If the container refuses.
        """
        if action not in PODMAN_CONTAINER_ACTIONS:
            raise ValueError(action)
        if source == PODMAN_SOURCE_MANUAL:
            run([PODMAN_BINARY, action, name], timeout_s=120)
            return
        try:
            run(["systemctl", action, f"{name}.service"], timeout_s=900)
        except (OSError, subprocess.SubprocessError):
            # netavark's first veth of a boot sometimes fails and the unit's
            # own Restart heals it a second later.
            time.sleep(2)
            if unit_state(f"{name}.service") != "active" or action == "stop":
                raise


def journal_lines(name: str, lines: int) -> list:
    """The tail of one container unit's journal.

    Args:
        name: The container's name.
        lines: How many lines to read.

    Returns:
        The lines, in order.
    """
    try:
        result = run(
            [
                "journalctl",
                "-u",
                f"{name}.service",
                "-n",
                str(lines),
                "--no-pager",
                "--output",
                "short-iso",
            ],
            is_checked=False,
            timeout_s=30,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return (result.stdout or result.stderr).splitlines()


def owner_of(name: str, module: str, declared_names: list) -> str:
    """Where one container comes from, by the owner rule.

    Args:
        name: The container's name.
        module: The module its label ``neutrino.module`` names, empty for none.
        declared_names: The names the hub declares.

    Returns:
        ``hub`` for a container with the label, ``declared`` for a declared
        name, ``manual`` for any other.
    """
    if module:
        return PODMAN_SOURCE_HUB
    if name in declared_names:
        return PODMAN_SOURCE_DECLARED
    return PODMAN_SOURCE_MANUAL


def _by_source(state: PodmanContainerState) -> tuple:
    return (SOURCE_ORDER.index(state.source), state.name)


def _module_label(entry: dict, detail: dict) -> str:
    """The module the label ``neutrino.module`` names, from ``ps`` or else ``inspect``."""
    for labels in (
        entry.get("Labels"),
        (detail.get("Config") or {}).get("Labels"),
    ):
        if isinstance(labels, dict) and labels.get(PODMAN_MODULE_LABEL):
            return str(labels[PODMAN_MODULE_LABEL])
    return ""


def _gateway_of(network: dict) -> str:
    """The first gateway of one inspected network, netavark's or CNI's."""
    for subnet in network.get("subnets") or []:
        if isinstance(subnet, dict) and subnet.get("gateway"):
            return str(subnet["gateway"])
    for plugin in network.get("plugins") or []:
        ranges = ((plugin or {}).get("ipam") or {}).get("ranges") or []
        for group in ranges:
            for held in group if isinstance(group, list) else []:
                if isinstance(held, dict) and held.get("gateway"):
                    return str(held["gateway"])
    return ""


def _inspected_ports(detail: dict) -> list:
    """Every published port of one inspect object as the configuration
    writes it: ``host:container``, and ``host:container/udp`` on UDP. A port
    on another protocol, which the configuration cannot hold, is left out."""
    bindings = (detail.get("HostConfig") or {}).get("PortBindings") or {}
    ports = []
    for container_port, targets in sorted(bindings.items()):
        inside, _, protocol = str(container_port).partition("/")
        protocol = protocol.lower() or "tcp"
        if protocol not in ("tcp", "udp"):
            continue
        suffix = "/udp" if protocol == "udp" else ""
        for target in targets or []:
            host = str((target or {}).get("HostPort", "") or "")
            if host:
                ports.append(f"{host}:{inside}{suffix}")
    return ports


def _inspected_volumes(detail: dict, *, host_volume=None) -> list:
    """Every mount of one inspect object as ``source:destination``: a named
    volume by its name, any other source passed through ``host_volume`` when
    one is given. An anonymous volume is left out."""
    volumes = []
    for mount in detail.get("Mounts") or []:
        if not isinstance(mount, dict):
            continue
        name = str(mount.get("Name", "") or "")
        if mount.get("Type") == PODMAN_VOLUME_MOUNT and name:
            if re.fullmatch(PODMAN_ANONYMOUS_VOLUME_PATTERN, name):
                continue
            source = name
        else:
            source = str(mount.get("Source", "") or name)
            if source and host_volume is not None:
                source = host_volume(source)
        destination = str(mount.get("Destination", "") or "")
        if source and destination:
            volumes.append(f"{source}:{destination}")
    return volumes


def _inspected_environment(detail: dict) -> list:
    """The environment of one inspect object, ``KEY=value`` each."""
    environment = (detail.get("Config") or {}).get("Env") or []
    return [str(entry) for entry in environment if "=" in str(entry)]


def _mapped_port(entry: dict):
    """The host port of one ``ps`` port mapping, as Podman 3.4 or a later version writes it."""
    port = entry.get("host_port")
    return port if port is not None else entry.get("hostPort")


def _mapped_address(entry: dict) -> str:
    """The host address of one ``ps`` port mapping, as Podman 3.4 or a later version writes it."""
    address = entry.get("host_ip")
    if address is None:
        address = entry.get("hostIP")
    return str(address or "")


def _host_ports(entries: list) -> list:
    ports = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        port = _mapped_port(entry)
        if isinstance(port, int) and port > 0:
            ports.add(port)
    return sorted(ports)


def _host_bindings(entries: list, *, is_address_kept: bool = True) -> list:
    bindings = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        port = _mapped_port(entry)
        protocol = str(entry.get("protocol", "") or "tcp").lower()
        if not isinstance(port, int) or port <= 0 or protocol not in ("tcp", "udp"):
            continue
        address = _mapped_address(entry) if is_address_kept else ""
        binding = {
            "address": address,
            "port": port,
            "protocol": protocol,
            "detected": "",
        }
        if binding not in bindings:
            bindings.append(binding)
    return bindings


def _probed_bindings(entry: dict, bindings: list) -> list:
    """The TCP bindings of one running container, each with its probe key."""
    start = (str(entry.get("Id", "") or ""), str(entry.get("StartedAt", "") or ""))
    return [
        (start + (binding["address"], binding["port"]), binding)
        for binding in bindings
        if binding["protocol"] == PODMAN_PROTOCOL_TCP
    ]


def _probe_address(address: str) -> str:
    """Where a port published on one address is probed: loopback for every
    address, the address itself otherwise."""
    try:
        if ipaddress.ip_address(address).is_unspecified:
            return PODMAN_PROBE_ADDRESS
    except ValueError:
        return PODMAN_PROBE_ADDRESS
    return address


def _read(path: str) -> "str | None":
    try:
        with open(path, "r", encoding="utf-8") as stream:
            return stream.read()
    except OSError:
        return None


def _marked_files(directory: str, suffix: str) -> list:
    """The files with a suffix in a directory that start with the generated marker, sorted."""
    if not os.path.isdir(directory):
        return []
    names = []
    for file_name in sorted(os.listdir(directory)):
        if not file_name.endswith(suffix):
            continue
        held = _read(os.path.join(directory, file_name))
        if held is not None and held.startswith(PODMAN_GENERATED_MARKER):
            names.append(file_name)
    return names


def _write_changed(path: str, text: str, *, mode: int, kept_keys=()) -> bool:
    """Write one file with a mode when its text differs from the one there.

    Args:
        path: The file.
        text: What it holds.
        mode: Its mode.
        kept_keys: Variables whose values alone differing keep the file.

    Returns:
        True when the file was written.

    Raises:
        OSError: When the file cannot be written.
    """
    held = _read(path)
    if held == text:
        return False
    if held is not None and kept_keys:
        if source_neutral(held, kept_keys) == source_neutral(text, kept_keys):
            return False
    temporary = path + ".new"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        os.fchmod(descriptor, mode)
        os.write(descriptor, text.encode("utf-8"))
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    return True
