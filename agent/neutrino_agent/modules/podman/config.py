"""The declared containers: what this machine runs, as configuration.

A container declared here becomes a systemd unit, so it survives reboots
and appears to systemd like any other service. The knobs are few: image,
ports, volumes, environment, a command, whether it starts at boot, and the
service type of each host port.

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
class PodmanConfig:
    """Everything the module's desired configuration holds.

    Attributes:
        containers: The declared containers.
        mirrors: Registry mirrors for docker.io, tried in order.
    """

    containers: list = field(default_factory=list)
    mirrors: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "PodmanConfig":
        return cls(
            containers=[
                PodmanContainer.from_dict(entry) for entry in data.get("containers", [])
            ],
            mirrors=[str(mirror) for mirror in data.get("mirrors", [])],
        )

    def to_dict(self) -> dict:
        return {
            "containers": [container.to_dict() for container in self.containers],
            "mirrors": list(self.mirrors),
        }

    @property
    def declared_names(self) -> list:
        """The declared containers' names, in order."""
        return [container.name for container in self.containers]

    def validate(self) -> None:
        """Check the configuration holds together.

        Raises:
            ModuleApplyError: Naming the first problem found.
        """
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
                self._validate_volume(name, volume)
            for line in container.environment:
                if not ENVIRONMENT_PATTERN.match(line):
                    raise ModuleApplyError(
                        "environment_invalid", {"name": name, "entry": line}
                    )
            if "\n" in container.command:
                raise ModuleApplyError("command_invalid", {"name": name})
            self._validate_services(container)
        for mirror in self.mirrors:
            if not MIRROR_PATTERN.match(mirror):
                raise ModuleApplyError("mirror_invalid", {"mirror": mirror})

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
                    "port_mapping_invalid",
                    {"name": container.name, "port": str(service.port)},
                )
            seen.add(service.port)
            if service.kind == PODMAN_SERVICE_PORT and not service.protocols:
                raise ModuleApplyError("service_protocol_none", {"port": service.port})

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
