"""Making the declared and hub containers true on the machine, and reading what runs.

Declared and hub containers live as unit files and are driven through
systemd; containers someone started by hand at a shell are still listed and
still controllable, through podman directly. Each container's owner is read
in one order: the label ``neutrino.module`` makes it a hub container of that
module, a declared name makes it declared, and any other is a person's own.

Not pure: writes unit files, runs podman and drives systemd.
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
    PODMAN_ADD_HOST_VERSION,
    PODMAN_BINARY,
    PODMAN_CNI_DIR,
    PODMAN_CNI_SUFFIX,
    PODMAN_CNI_VERSION,
    PODMAN_CONTAINER_ACTIONS,
    PODMAN_GENERATED_MARKER,
    PODMAN_MODULE_LABEL,
    PODMAN_PROBE_ADDRESS,
    PODMAN_PROTOCOL_TCP,
    PODMAN_QUADLET_DIR,
    PODMAN_QUADLET_VERSION,
    PODMAN_REGISTRIES_CONF_PATH,
    PODMAN_SOURCE_DECLARED,
    PODMAN_SOURCE_HUB,
    PODMAN_SOURCE_MANUAL,
    PODMAN_UNIT_DIR,
)
from neutrino_agent.modules.podman.renderer import (
    PodmanQuadletRenderer,
    PodmanRenderContext,
    PodmanUnitRenderer,
    source_neutral,
)
from neutrino_agent.modules.shared import source_fetch
from neutrino_agent.modules.shared.subprocess_run import run, unit_state

VERSION_NUMBER_PATTERN = re.compile(r"\d+")

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
        environment: The container's environment, ``KEY=value`` each.
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


def is_version_at_least(version: str, floor: str) -> bool:
    """Whether a version string reaches a floor, comparing numeric parts.

    Args:
        version: What ``podman --version`` printed last, distribution
            suffixes allowed.
        floor: The version to reach.

    Returns:
        True when ``version`` is the floor or above.
    """
    have = [int(part) for part in VERSION_NUMBER_PATTERN.findall(version.split("-")[0])]
    want = [int(part) for part in VERSION_NUMBER_PATTERN.findall(floor)]
    if not have:
        return False
    width = max(len(have), len(want))
    have += [0] * (width - len(have))
    want += [0] * (width - len(want))
    return have >= want


def is_quadlet_supported() -> bool:
    """Whether the installed podman turns a ``.container`` file into a unit.

    Returns:
        True from podman 4.6, the first Quadlet that adds a host; False
        below it or when podman cannot run.
    """
    try:
        result = run([PODMAN_BINARY, "--version"], is_checked=False, timeout_s=30)
    except (OSError, subprocess.SubprocessError):
        return False
    if not result.is_success:
        return False
    words = result.stdout.split()
    return is_version_at_least(words[-1] if words else "", PODMAN_QUADLET_VERSION)


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


def container_renderer(
    config: PodmanConfig, context: "PodmanRenderContext | None" = None
):
    """The renderer whose output this machine's podman understands.

    Args:
        config: The containers to render.
        context: What the apply found; None renders with nothing found.

    Returns:
        A :class:`PodmanQuadletRenderer` from podman 4.6, writing the host
        as ``AddHost=`` from 5.3; else a :class:`PodmanUnitRenderer`.
    """
    version = podman_version()
    if is_version_at_least(version, PODMAN_QUADLET_VERSION):
        return PodmanQuadletRenderer(
            config=config,
            context=context,
            is_add_host_key=is_version_at_least(version, PODMAN_ADD_HOST_VERSION),
        )
    return PodmanUnitRenderer(config=config, context=context)


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


def container_applier() -> "PodmanUnitApplier":
    """The applier for whichever files :func:`container_renderer` produced."""
    if is_quadlet_supported():
        return PodmanUnitApplier(directory=PODMAN_QUADLET_DIR, suffix=".container")
    return PodmanUnitApplier(
        directory=PODMAN_UNIT_DIR, suffix=".service", is_enabled_by_systemctl=True
    )


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
        section holds; a set none of whose sources answers names its first.
    """
    sources = {}
    variables = {}
    for name in names:
        held = source_sets.get(name)
        if not isinstance(held, dict) or not held.get("sources"):
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
    """Installs rendered container units and reconciles systemd with them."""

    def __init__(
        self, *, directory: str, suffix: str, is_enabled_by_systemctl: bool = False
    ):
        """
        Args:
            directory: Where the files are written.
            suffix: What the rendered files are called, ``.container`` for
                Quadlet and ``.service`` without it.
            is_enabled_by_systemctl: Whether a unit that starts with the
                box is turned on with ``systemctl enable``: a plain unit;
                Quadlet's generator links a ``.container`` file itself.
        """
        self._directory = directory
        self._suffix = suffix
        self._is_enabled_by_systemctl = is_enabled_by_systemctl

    @property
    def directory(self) -> str:
        """Where this applier writes."""
        return self._directory

    def apply(
        self,
        rendered: dict,
        *,
        autostart_names: list,
        source_keys: "dict | None" = None,
    ) -> str:
        """Write the rendered files, drop stale ones, recreate what changed,
        and start what starts with the box.

        Only files carrying the generated marker are ever removed: a file a
        person wrote by hand beside these is theirs. A plain unit is
        enabled when its container starts with the box and disabled when
        it does not. A file whose only change is a source set's value is
        kept as it is.

        Args:
            rendered: File contents keyed by file name.
            autostart_names: Containers that should be running; a changed
                one of these is restarted even if it was stopped, and an
                unchanged one that is not active is started.
            source_keys: Container name to the variables a source set fills
                in; None or a name it does not hold has none.

        Returns:
            A short summary of what changed.

        Raises:
            subprocess.CalledProcessError: If systemd refuses a unit.
        """
        os.makedirs(self._directory, exist_ok=True)
        keys = dict(source_keys or {})
        changed = []
        for file_name, text in rendered.items():
            path = os.path.join(self._directory, file_name)
            held = _read(path)
            name_keys = keys.get(file_name[: -len(self._suffix)], ())
            if held is not None and name_keys:
                if source_neutral(held, name_keys) == source_neutral(text, name_keys):
                    continue
            if held != text:
                with open(path, "w", encoding="utf-8") as stream:
                    stream.write(text)
                changed.append(file_name)
        for file_name in self.generated_names():
            if file_name in rendered:
                continue
            self._retire_unit(f"{file_name[: -len(self._suffix)]}.service")
            os.unlink(os.path.join(self._directory, file_name))
            changed.append(f"-{file_name}")
        if self._is_enabled_by_systemctl:
            for file_name in rendered:
                name = file_name[: -len(self._suffix)]
                verb = "enable" if name in autostart_names else "disable"
                run(["systemctl", verb, "--no-reload", f"{name}.service"])
        run(["systemctl", "daemon-reload"])
        for file_name in rendered:
            name = file_name[: -len(self._suffix)]
            unit = f"{name}.service"
            if file_name in changed:
                if name in autostart_names or unit_state(unit) == "active":
                    run(["systemctl", "restart", unit], timeout_s=900)
            elif name in autostart_names and unit_state(unit) != "active":
                run(["systemctl", "start", unit], timeout_s=900)
        if not changed:
            return "containers unchanged"
        return f"containers: {', '.join(sorted(changed))}"

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
            if f"{name}{self._suffix}" in owned:
                run(["systemctl", action, f"{name}.service"], timeout_s=900)

    def remove(self, names: list) -> list:
        """Stop the units of some containers and delete their generated files.

        Args:
            names: The containers.

        Returns:
            The names whose file was removed.
        """
        owned = set(self.generated_names())
        removed = []
        for name in names:
            file_name = f"{name}{self._suffix}"
            if file_name not in owned:
                continue
            self._retire_unit(f"{name}.service")
            with contextlib.suppress(OSError):
                os.unlink(os.path.join(self._directory, file_name))
            removed.append(name)
        if removed:
            run(["systemctl", "daemon-reload"], is_checked=False)
        return removed

    def stop_all(self) -> None:
        """Stop every generated unit, leaving its file in place."""
        for file_name in self.generated_names():
            unit = f"{file_name[: -len(self._suffix)]}.service"
            run(["systemctl", "stop", unit], is_checked=False)

    def remove_all(self) -> None:
        """Stop every generated unit, disable a plain one, and delete its file."""
        self.stop_all()
        for file_name in self.generated_names():
            if self._is_enabled_by_systemctl:
                unit = f"{file_name[: -len(self._suffix)]}.service"
                run(["systemctl", "disable", "--no-reload", unit], is_checked=False)
            with contextlib.suppress(OSError):
                os.unlink(os.path.join(self._directory, file_name))

    def generated_names(self) -> list:
        """The rendered files this applier owns in its directory."""
        if not os.path.isdir(self._directory):
            return []
        names = []
        for file_name in sorted(os.listdir(self._directory)):
            if not file_name.endswith(self._suffix):
                continue
            text = _read(os.path.join(self._directory, file_name))
            if text is not None and text.startswith(PODMAN_GENERATED_MARKER):
                names.append(file_name)
        return names

    def _retire_unit(self, unit: str) -> None:
        """Stop one unit whose file goes, and disable it where it is a plain unit.

        systemd refuses to disable a unit Quadlet generates, and stops
        nothing when a disable with ``--now`` is refused.
        """
        run(["systemctl", "stop", unit], is_checked=False)
        if self._is_enabled_by_systemctl:
            run(["systemctl", "disable", "--no-reload", unit], is_checked=False)


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
                    environment=_inspected_environment(detail),
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
    """Whether a rendered unit stands for one container, Quadlet or plain.

    Args:
        name: The container's name.

    Returns:
        True when either directory holds its file.
    """
    return os.path.isfile(
        os.path.join(PODMAN_QUADLET_DIR, f"{name}.container")
    ) or os.path.isfile(os.path.join(PODMAN_UNIT_DIR, f"{name}.service"))


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
    """Every mount of one inspect object as ``source:destination``, the
    source passed through ``host_volume`` when one is given."""
    volumes = []
    for mount in detail.get("Mounts") or []:
        if not isinstance(mount, dict):
            continue
        source = str(mount.get("Source", "") or mount.get("Name", "") or "")
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


def _host_ports(entries: list) -> list:
    ports = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        port = entry.get("host_port")
        if isinstance(port, int) and port > 0:
            ports.add(port)
    return sorted(ports)


def _host_bindings(entries: list, *, is_address_kept: bool = True) -> list:
    bindings = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        port = entry.get("host_port")
        protocol = str(entry.get("protocol", "") or "tcp").lower()
        if not isinstance(port, int) or port <= 0 or protocol not in ("tcp", "udp"):
            continue
        address = str(entry.get("host_ip", "") or "") if is_address_kept else ""
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
