"""The declared containers and the hub containers: what this machine runs, as configuration.

A container declared here becomes a systemd unit, so it survives reboots
and appears to systemd like any other service. The knobs are few: image,
ports, volumes, environment, a command, whether it starts at boot, and the
service type of each host port. A hub container is one a container module
runs: the hub composes it with its module, its image by digest and sources,
the source sets its tools fetch from, the containers it starts after and the
port its module's forwarder serves. On Windows and macOS the containers run
in one account's Podman machine, which the Run settings, ``machine``, name.

Pure: parsing and validation only.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import re
from dataclasses import dataclass, field

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.podman.constants import (
    PODMAN_DIGEST_PATTERN,
    PODMAN_EXIT_CODE_MAX,
    PODMAN_HUB_PREFIX,
    PODMAN_PROTOCOL_TCP,
    PODMAN_PROTOCOL_UDP,
    PODMAN_PROTOCOLS,
    PODMAN_SERVICE_AUTO,
    PODMAN_SERVICE_KINDS,
    PODMAN_SERVICE_PORT,
    PODMAN_SERVICE_SCHEMES,
    PODMAN_SERVICE_WEB,
    PODMAN_STOP_TIMEOUT_MAX_S,
)
from neutrino_agent.modules.podman.machine_paths import is_shared_source, split_volume

# A container's name becomes a systemd unit name and a shell argument.
CONTAINER_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}\Z")

# host:container, an optional /udp, ports in range.
PORT_MAPPING_PATTERN = re.compile(r"^\d{1,5}:\d{1,5}(/(tcp|udp))?\Z")

# KEY=value with a sane key; the value may hold anything printable.
ENVIRONMENT_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=[^\n]*\Z")

# A registry mirror is a host, optionally with a port and path, never a URL.
MIRROR_PATTERN = re.compile(r"^[A-Za-z0-9.-]+(:[0-9]+)?(/[A-Za-z0-9._/-]*)?\Z")

# A module's name, which names its label, its network and its volumes.
MODULE_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,47}\Z")

# A hub container's image: a digest, and each source an image reference
# with no tag and no digest.
DIGEST_PATTERN = re.compile(PODMAN_DIGEST_PATTERN + r"\Z")
IMAGE_SOURCE_PATTERN = re.compile(r"^[a-z0-9.-]+(:[0-9]+)?(/[a-z0-9._-]+)+\Z")

# A source set's name, as a hub container lists it.
SOURCE_SET_PATTERN = re.compile(r"^[a-z][a-z0-9_]*\Z")


def _tcp_only() -> list:
    """The protocols of a ``port`` service that names none."""
    return [PODMAN_PROTOCOL_TCP]


def _count(value) -> int:
    """A whole number from the configuration; -1 for one that is not."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


@dataclass
class PodmanService:
    """The service type of one host port of a container.

    Attributes:
        port: The host port.
        kind: ``auto``, ``web`` or ``port``.
        scheme: ``http`` or ``https``, for ``web``.
        protocols: ``tcp`` and ``udp``, each published, for ``port``.
    """

    port: int
    kind: str = PODMAN_SERVICE_AUTO
    scheme: str = "http"
    protocols: list = field(default_factory=_tcp_only)

    @classmethod
    def from_dict(cls, data: dict) -> "PodmanService":
        try:
            port = int(data.get("port", 0))
        except (TypeError, ValueError):
            port = 0
        return cls(
            port=port,
            kind=str(data.get("kind", PODMAN_SERVICE_AUTO) or PODMAN_SERVICE_AUTO),
            scheme=str(data.get("scheme", "http") or "http"),
            protocols=[
                str(protocol) for protocol in data.get("protocols", _tcp_only()) or []
            ],
        )

    def to_dict(self) -> dict:
        return {
            "port": self.port,
            "kind": self.kind,
            "scheme": self.scheme,
            "protocols": list(self.protocols),
        }


@dataclass
class PodmanContainer:
    """One declared container.

    Attributes:
        name: The container's and its systemd unit's name.
        image: The image reference, short or qualified.
        ports: Published ports as ``host:container`` or ``host:container/udp``.
        volumes: Mounts as ``source:destination``.
        environment: Variables as ``KEY=value`` lines.
        command: What to run instead of the image's own command.
        is_autostart: Whether it comes up with the machine.
        services: One :class:`PodmanService` per host port it names; a
            host port it does not name is ``auto``.
    """

    name: str
    image: str
    ports: list = field(default_factory=list)
    volumes: list = field(default_factory=list)
    environment: list = field(default_factory=list)
    command: str = ""
    is_autostart: bool = True
    services: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "PodmanContainer":
        return cls(
            name=str(data.get("name", "")),
            image=str(data.get("image", "")),
            ports=[str(port) for port in data.get("ports", [])],
            volumes=[str(volume) for volume in data.get("volumes", [])],
            environment=[str(entry) for entry in data.get("environment", [])],
            command=str(data.get("command", "") or ""),
            is_autostart=bool(data.get("is_autostart", True)),
            services=[
                PodmanService.from_dict(entry)
                for entry in data.get("services") or []
                if isinstance(entry, dict)
            ],
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "image": self.image,
            "ports": list(self.ports),
            "volumes": list(self.volumes),
            "environment": list(self.environment),
            "command": self.command,
            "is_autostart": self.is_autostart,
            "services": [service.to_dict() for service in self.services],
        }

    @property
    def publish_ports(self) -> list:
        """What the unit publishes: ``ports`` as each port's service has it.

        Returns:
            ``host:container`` or ``host:container/udp`` each, in the order
            of ``ports``, once each: a ``web`` port on TCP, a ``port`` port
            on each of its protocols, any other as ``ports`` writes it.
        """
        services = {service.port: service for service in self.services}
        published = []
        for mapping in self.ports:
            host, _, rest = mapping.partition(":")
            inside = rest.partition("/")[0]
            service = services.get(int(host)) if host.isdigit() else None
            if service is None or service.kind == PODMAN_SERVICE_AUTO:
                forms = [mapping]
            elif service.kind == PODMAN_SERVICE_WEB:
                forms = [f"{host}:{inside}"]
            else:
                forms = []
                if PODMAN_PROTOCOL_TCP in service.protocols:
                    forms.append(f"{host}:{inside}")
                if PODMAN_PROTOCOL_UDP in service.protocols:
                    forms.append(f"{host}:{inside}/udp")
            for form in forms:
                if form not in published:
                    published.append(form)
        return published


@dataclass
class PodmanHubContainer:
    """One container a container module runs on Containers.

    Attributes:
        module: The container module that runs it.
        name: The container's and its systemd unit's name.
        digest: The digest of its image, the index of every architecture.
        sources: The image references that serve the image, with no tag.
        ports: Published ports, as a declared container writes them.
        volumes: Named volumes as ``name:destination``.
        environment: Variables as ``KEY=value`` lines; a value ``{<set>}``
            of a set the container lists is that set's fastest source.
        command: What to run instead of the image's own command.
        is_autostart: Whether it comes up with the machine.
        services: One :class:`PodmanService` per host port it names.
        source_sets: The source sets whose variables its environment gets.
        after: The containers of its module it starts after, by name.
        page_port: The container's port its module's forwarder serves; 0
            for none.
        stop_timeout_s: The seconds ``podman stop`` gives it before
            SIGKILL; 0 for Podman's own 10.
        success_exit_codes: The exit codes beside 143 its unit counts as a
            clean stop.
    """

    module: str
    name: str
    digest: str
    sources: list = field(default_factory=list)
    ports: list = field(default_factory=list)
    volumes: list = field(default_factory=list)
    environment: list = field(default_factory=list)
    command: str = ""
    is_autostart: bool = True
    services: list = field(default_factory=list)
    source_sets: list = field(default_factory=list)
    after: list = field(default_factory=list)
    page_port: int = 0
    stop_timeout_s: int = 0
    success_exit_codes: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "PodmanHubContainer":
        image = data.get("image") if isinstance(data.get("image"), dict) else {}
        return cls(
            module=str(data.get("module", "") or ""),
            name=str(data.get("name", "") or ""),
            digest=str(image.get("digest", "") or ""),
            sources=[str(source) for source in image.get("sources") or []],
            ports=[str(port) for port in data.get("ports") or []],
            volumes=[str(volume) for volume in data.get("volumes") or []],
            environment=[str(entry) for entry in data.get("environment") or []],
            command=str(data.get("command", "") or ""),
            is_autostart=bool(data.get("is_autostart", True)),
            services=[
                PodmanService.from_dict(entry)
                for entry in data.get("services") or []
                if isinstance(entry, dict)
            ],
            source_sets=[str(name) for name in data.get("source_sets") or []],
            after=[str(name) for name in data.get("after") or []],
            page_port=_count(data.get("page_port", 0)),
            stop_timeout_s=_count(data.get("stop_timeout_s", 0)),
            success_exit_codes=[
                _count(code) for code in data.get("success_exit_codes") or []
            ],
        )

    def to_dict(self) -> dict:
        held = {
            "module": self.module,
            "name": self.name,
            "image": {"digest": self.digest, "sources": list(self.sources)},
            "ports": list(self.ports),
            "volumes": list(self.volumes),
            "environment": list(self.environment),
            "command": self.command,
            "is_autostart": self.is_autostart,
            "services": [service.to_dict() for service in self.services],
            "source_sets": list(self.source_sets),
            "after": list(self.after),
            "page_port": self.page_port,
        }
        if self.stop_timeout_s:
            held["stop_timeout_s"] = self.stop_timeout_s
        if self.success_exit_codes:
            held["success_exit_codes"] = list(self.success_exit_codes)
        return held

    @property
    def network(self) -> str:
        """The network the containers of its module join, ``neutrino_<module>``."""
        return PODMAN_HUB_PREFIX + self.module

    def as_container(self) -> PodmanContainer:
        """The knobs a hub container shares with a declared one.

        Returns:
            Its name, ports, volumes, environment, command, autostart and
            services; ``image`` holds the digest, since the reference is
            the one found in Podman's store.
        """
        return PodmanContainer(
            name=self.name,
            image=self.digest,
            ports=list(self.ports),
            volumes=list(self.volumes),
            environment=list(self.environment),
            command=self.command,
            is_autostart=self.is_autostart,
            services=list(self.services),
        )


@dataclass
class PodmanMachineSettings:
    """The Run settings: whose Podman machine runs the containers, and its size.

    Attributes:
        account: The account whose default machine runs them.
        cpus: Its processors; 0 is half the computer's.
        memory_gib: Its memory in GiB; 0 is half the computer's, at most 4.
        disk_gib: Its disk in GiB, at least 1 on Windows; on macOS 0 is 100
            at an init and leaves a machine taken over as it is.
        password: The account's login, which Windows runs the account's
            commands with; empty elsewhere.
    """

    account: str = ""
    cpus: int = 0
    memory_gib: int = 0
    disk_gib: int = 0
    password: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "PodmanMachineSettings":
        return cls(
            account=str(data.get("account", "") or ""),
            cpus=_count(data.get("cpus", 0)),
            memory_gib=_count(data.get("memory_gib", 0)),
            disk_gib=_count(data.get("disk_gib", 0)),
            password=str(data.get("password", "") or ""),
        )

    def to_dict(self) -> dict:
        return {
            "account": self.account,
            "cpus": self.cpus,
            "memory_gib": self.memory_gib,
            "disk_gib": self.disk_gib,
            "password": self.password,
        }


@dataclass
class PodmanConfig:
    """Everything the module's desired configuration holds.

    Attributes:
        containers: The declared containers.
        mirrors: Registry mirrors for docker.io, tried in order.
        machine: The Run settings on Windows and macOS; None where the
            state names none, which a Linux state never does.
        hub_containers: The hub containers the container modules compose,
            one :class:`PodmanHubContainer` each.
    """

    containers: list = field(default_factory=list)
    mirrors: list = field(default_factory=list)
    machine: "PodmanMachineSettings | None" = None
    hub_containers: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "PodmanConfig":
        machine = data.get("machine")
        return cls(
            containers=[
                PodmanContainer.from_dict(entry) for entry in data.get("containers", [])
            ],
            mirrors=[str(mirror) for mirror in data.get("mirrors", [])],
            machine=(
                PodmanMachineSettings.from_dict(machine)
                if isinstance(machine, dict)
                else None
            ),
            hub_containers=[
                PodmanHubContainer.from_dict(entry)
                for entry in data.get("hub_containers") or []
                if isinstance(entry, dict)
            ],
        )

    def to_dict(self) -> dict:
        data = {
            "containers": [container.to_dict() for container in self.containers],
            "mirrors": list(self.mirrors),
            "hub_containers": [
                container.to_dict() for container in self.hub_containers
            ],
        }
        if self.machine is not None:
            data["machine"] = self.machine.to_dict()
        return data

    @property
    def declared_names(self) -> list:
        """The declared containers' names, in order."""
        return [container.name for container in self.containers]

    def hub_names(self) -> dict:
        """The hub containers' names by module, each module's in order.

        Returns:
            Module name to its containers' names.
        """
        names: dict = {}
        for container in self.hub_containers:
            names.setdefault(container.module, []).append(container.name)
        return names

    def hub_containers_of(self, module: str) -> list:
        """One module's hub containers, in order.

        Args:
            module: The container module.

        Returns:
            Its :class:`PodmanHubContainer` entries.
        """
        return [
            container for container in self.hub_containers if container.module == module
        ]

    def without_refused(self, *, os_name: str = "linux") -> tuple:
        """The configuration without each declared container its checks refuse.

        The hub containers' names are taken first. A declared container
        with a hub container's name is refused ``container_name_duplicate``.

        Args:
            os_name: The computer's system.

        Returns:
            ``(config, refused)``: a new configuration with the other
            declared containers, the hub containers, the mirrors and the Run
            settings, and ``(name, error)`` for each declared container left
            out, in order.
        """
        seen = {container.name for container in self.hub_containers}
        kept = []
        refused = []
        for container in self.containers:
            try:
                self._validate_declared(container, seen, os_name=os_name)
            except ModuleApplyError as error:
                refused.append((container.name, error))
                continue
            kept.append(container)
        config = PodmanConfig(
            containers=kept,
            mirrors=list(self.mirrors),
            machine=self.machine,
            hub_containers=list(self.hub_containers),
        )
        return config, refused

    def with_hub_containers(self, hub_containers: list) -> "PodmanConfig":
        """The same configuration with another list of hub containers.

        Args:
            hub_containers: The hub containers it holds instead.

        Returns:
            A new configuration; this one is left as it is.
        """
        return PodmanConfig(
            containers=list(self.containers),
            mirrors=list(self.mirrors),
            machine=self.machine,
            hub_containers=list(hub_containers),
        )

    def validate(
        self,
        *,
        os_name: str = "linux",
        host_cpus: int = 0,
        host_memory_gib: int = 0,
        disk_gib_now: int = 0,
    ) -> None:
        """Check the configuration holds together on one system.

        Linux checks the containers and the mirrors alone. Windows and macOS
        also check each volume's folder against what the machine reaches,
        and the Run settings against the computer; Windows refuses a port
        published on UDP, which WSL does not forward, and Run settings with
        a disk of 0.

        Args:
            os_name: The computer's system.
            host_cpus: The computer's logical processors; 0 checks none.
            host_memory_gib: Its memory in GiB; 0 checks none.
            disk_gib_now: The size of the machine's disk now in GiB; 0
                checks none.

        Raises:
            ModuleApplyError: Naming the first problem found.
        """
        seen: set = set()
        for container in self.containers:
            self._validate_declared(container, seen, os_name=os_name)
        for container in self.hub_containers:
            self._validate_hub_container(container, seen, os_name=os_name)
        for mirror in self.mirrors:
            if not MIRROR_PATTERN.match(mirror):
                raise ModuleApplyError("mirror_invalid", {"mirror": mirror})
        if os_name in ("windows", "darwin"):
            self._validate_machine(
                os_name=os_name,
                host_cpus=host_cpus,
                host_memory_gib=host_memory_gib,
                disk_gib_now=disk_gib_now,
            )

    def _validate_declared(
        self, container: PodmanContainer, seen: set, *, os_name: str
    ) -> None:
        """Refuse a declared container the agent cannot render; its name joins ``seen``."""
        name = container.name
        if not CONTAINER_NAME_PATTERN.match(name):
            raise ModuleApplyError("container_name_invalid", {"name": name})
        if name in seen:
            raise ModuleApplyError("container_name_duplicate", {"name": name})
        seen.add(name)
        if not container.image or any(c.isspace() for c in container.image):
            raise ModuleApplyError(
                "image_invalid", {"name": name, "image": container.image}
            )
        for port in container.ports:
            if not PORT_MAPPING_PATTERN.match(port):
                raise ModuleApplyError(
                    "port_mapping_invalid", {"name": name, "port": port}
                )
        for volume in container.volumes:
            if os_name in ("windows", "darwin"):
                self._validate_machine_volume(name, volume, os_name)
            else:
                self._validate_volume(name, volume)
        for line in container.environment:
            if not ENVIRONMENT_PATTERN.match(line):
                raise ModuleApplyError(
                    "environment_invalid", {"name": name, "entry": line}
                )
        if "\n" in container.command:
            raise ModuleApplyError("command_invalid", {"name": name})
        self._validate_services(container)
        if os_name == "windows":
            self._validate_windows_ports(container)

    def _validate_hub_container(
        self, container: PodmanHubContainer, seen: set, *, os_name: str
    ) -> None:
        """Refuse a hub container the agent cannot render; its name joins ``seen``."""
        name = container.name
        module = container.module
        is_named = CONTAINER_NAME_PATTERN.match(name) is not None and (
            name == PODMAN_HUB_PREFIX + module
            or name.startswith(PODMAN_HUB_PREFIX + module + "_")
        )
        if not MODULE_NAME_PATTERN.match(module) or not is_named:
            raise ModuleApplyError("container_name_invalid", {"name": name})
        if name in seen:
            raise ModuleApplyError("container_name_duplicate", {"name": name})
        seen.add(name)
        is_image_sound = (
            DIGEST_PATTERN.match(container.digest) is not None
            and bool(container.sources)
            and all(IMAGE_SOURCE_PATTERN.match(source) for source in container.sources)
        )
        if not is_image_sound:
            raise ModuleApplyError(
                "image_invalid", {"name": name, "image": container.digest}
            )
        for port in container.ports:
            if not PORT_MAPPING_PATTERN.match(port):
                raise ModuleApplyError(
                    "port_mapping_invalid", {"name": name, "port": port}
                )
        volume_prefix = PODMAN_HUB_PREFIX + module + "_"
        for volume in container.volumes:
            source, _, destination = volume.partition(":")
            is_sound = (
                CONTAINER_NAME_PATTERN.match(source) is not None
                and source.startswith(volume_prefix)
                and destination.startswith("/")
                and "\n" not in volume
            )
            if not is_sound:
                raise ModuleApplyError(
                    "volume_invalid", {"name": name, "volume": volume}
                )
        for line in container.environment:
            if not ENVIRONMENT_PATTERN.match(line):
                raise ModuleApplyError(
                    "environment_invalid", {"name": name, "entry": line}
                )
        if "\n" in container.command:
            raise ModuleApplyError("command_invalid", {"name": name})
        self._validate_services(container.as_container())
        if os_name == "windows":
            self._validate_windows_ports(container.as_container())
        for set_name in container.source_sets:
            if not SOURCE_SET_PATTERN.match(set_name):
                raise ModuleApplyError(
                    "environment_invalid", {"name": name, "entry": set_name}
                )
        siblings = self.hub_names().get(module, [])
        for other in container.after:
            if other == name or other not in siblings:
                raise ModuleApplyError("container_unknown", {"name": other})
        if not 0 <= container.page_port <= 65535:
            raise ModuleApplyError(
                "port_mapping_invalid",
                {"name": name, "port": str(container.page_port)},
            )
        if not 0 <= container.stop_timeout_s <= PODMAN_STOP_TIMEOUT_MAX_S:
            raise ModuleApplyError("command_invalid", {"name": name})
        for code in container.success_exit_codes:
            if not 0 <= code <= PODMAN_EXIT_CODE_MAX:
                raise ModuleApplyError("command_invalid", {"name": name})

    def _validate_machine(
        self, *, os_name: str, host_cpus: int, host_memory_gib: int, disk_gib_now: int
    ) -> None:
        settings = self.machine or PodmanMachineSettings()
        if settings.cpus < 0 or (host_cpus and settings.cpus > host_cpus):
            raise ModuleApplyError(
                "machine_cpus_invalid", {"cpus": settings.cpus, "max": host_cpus}
            )
        if settings.memory_gib < 0 or (
            host_memory_gib and settings.memory_gib > host_memory_gib
        ):
            raise ModuleApplyError(
                "machine_memory_invalid",
                {"memory_gib": settings.memory_gib, "max": host_memory_gib},
            )
        if os_name == "windows" and self.machine is not None and settings.disk_gib < 1:
            raise ModuleApplyError(
                "machine_disk_invalid", {"disk_gib": settings.disk_gib}
            )
        if settings.disk_gib < 0 or (
            settings.disk_gib and settings.disk_gib < disk_gib_now
        ):
            raise ModuleApplyError(
                "machine_disk_shrink",
                {"disk_gib": settings.disk_gib, "current_gib": disk_gib_now},
            )
        if (self.containers or self.hub_containers) and not settings.account:
            raise ModuleApplyError("machine_account_missing", {})

    def _validate_machine_volume(self, name: str, volume: str, os_name: str) -> None:
        if "\n" in volume:
            raise ModuleApplyError("volume_invalid", {"name": name, "volume": volume})
        source, destination = split_volume(volume, os_name=os_name)
        if not source or not destination.startswith("/"):
            raise ModuleApplyError("volume_invalid", {"name": name, "volume": volume})
        is_named = CONTAINER_NAME_PATTERN.match(source) is not None
        if not is_named and not is_shared_source(source, os_name=os_name):
            raise ModuleApplyError(
                "volume_not_shared", {"name": name, "volume": volume}
            )

    def _validate_services(self, container: PodmanContainer) -> None:
        host_ports = {int(port.partition(":")[0]) for port in container.ports}
        seen: set = set()
        for service in container.services:
            is_sound = (
                service.port in host_ports
                and service.port not in seen
                and service.kind in PODMAN_SERVICE_KINDS
                and service.scheme in PODMAN_SERVICE_SCHEMES
                and all(protocol in PODMAN_PROTOCOLS for protocol in service.protocols)
            )
            if not is_sound:
                raise ModuleApplyError(
                    "service_invalid", {"name": container.name, "port": service.port}
                )
            seen.add(service.port)
            if service.kind == PODMAN_SERVICE_PORT and not service.protocols:
                raise ModuleApplyError("service_protocol_none", {"port": service.port})

    def _validate_windows_ports(self, container: PodmanContainer) -> None:
        for mapping in container.publish_ports:
            if mapping.endswith("/" + PODMAN_PROTOCOL_UDP):
                raise ModuleApplyError(
                    "udp_not_forwarded",
                    {"name": container.name, "port": int(mapping.partition(":")[0])},
                )

    def _validate_volume(self, name: str, volume: str) -> None:
        if "\n" in volume or ":" not in volume:
            raise ModuleApplyError("volume_invalid", {"name": name, "volume": volume})
        source, _, destination = volume.partition(":")
        if not destination.startswith("/"):
            raise ModuleApplyError("volume_invalid", {"name": name, "volume": volume})
        is_host_path = source.startswith("/")
        is_named = CONTAINER_NAME_PATTERN.match(source) is not None
        if not is_host_path and not is_named:
            raise ModuleApplyError("volume_invalid", {"name": name, "volume": volume})
