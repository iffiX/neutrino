"""The declared containers: what this machine runs, as configuration.

A container declared here becomes a systemd unit, so it survives reboots
and appears to systemd like any other service. The knobs are few: image,
ports, volumes, environment, a command, whether it starts at boot, and the
service type of each host port. On Windows and macOS the containers run in
one account's Podman machine, which the Run settings, ``machine``, name.

Pure: parsing and validation only.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import re
from dataclasses import dataclass, field

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.podman.constants import (
    PODMAN_PROTOCOL_TCP,
    PODMAN_PROTOCOL_UDP,
    PODMAN_PROTOCOLS,
    PODMAN_SERVICE_AUTO,
    PODMAN_SERVICE_KINDS,
    PODMAN_SERVICE_PORT,
    PODMAN_SERVICE_SCHEMES,
    PODMAN_SERVICE_WEB,
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
class PodmanMachineSettings:
    """The Run settings: whose Podman machine runs the containers, and its size.

    Attributes:
        account: The account whose default machine runs them.
        cpus: Its processors; 0 is half the computer's.
        memory_gib: Its memory in GiB; 0 is 2.
        disk_gib: Its disk in GiB; 0 is 100 at an init and leaves a machine
            taken over as it is.
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
    """

    containers: list = field(default_factory=list)
    mirrors: list = field(default_factory=list)
    machine: "PodmanMachineSettings | None" = None

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
        )

    def to_dict(self) -> dict:
        data = {
            "containers": [container.to_dict() for container in self.containers],
            "mirrors": list(self.mirrors),
        }
        if self.machine is not None:
            data["machine"] = self.machine.to_dict()
        return data

    @property
    def declared_names(self) -> list:
        """The declared containers' names, in order."""
        return [container.name for container in self.containers]

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
        published on UDP, which WSL does not forward.

        Args:
            os_name: The computer's system.
            host_cpus: The computer's logical processors; 0 checks none.
            host_memory_gib: Its memory in GiB; 0 checks none.
            disk_gib_now: The size of the machine's disk now in GiB; 0
                checks none.

        Raises:
            ModuleApplyError: Naming the first problem found.
        """
        is_machine = os_name in ("windows", "darwin")
        seen: set = set()
        for container in self.containers:
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
                if is_machine:
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
        for mirror in self.mirrors:
            if not MIRROR_PATTERN.match(mirror):
                raise ModuleApplyError("mirror_invalid", {"mirror": mirror})
        if is_machine:
            self._validate_machine(
                host_cpus=host_cpus,
                host_memory_gib=host_memory_gib,
                disk_gib_now=disk_gib_now,
            )

    def _validate_machine(
        self, *, host_cpus: int, host_memory_gib: int, disk_gib_now: int
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
        if settings.disk_gib < 0 or (
            settings.disk_gib and settings.disk_gib < disk_gib_now
        ):
            raise ModuleApplyError(
                "machine_disk_shrink",
                {"disk_gib": settings.disk_gib, "current_gib": disk_gib_now},
            )
        if self.containers and not settings.account:
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
