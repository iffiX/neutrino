"""The declared containers: what this machine runs, as configuration.

A container declared here becomes a systemd unit, so it survives reboots
and appears to systemd like any other service. The knobs are few: image,
ports, volumes, environment, a command, and whether it starts at boot.

Pure: parsing and validation only.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import re
from dataclasses import dataclass, field

from neutrino_agent.modules.base import ModuleApplyError

# A container's name becomes a systemd unit name and a shell argument.
CONTAINER_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}\Z")

# host:container, an optional /udp, ports in range.
PORT_MAPPING_PATTERN = re.compile(r"^\d{1,5}:\d{1,5}(/(tcp|udp))?\Z")

# KEY=value with a sane key; the value may hold anything printable.
ENVIRONMENT_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=[^\n]*\Z")

# A registry mirror is a host, optionally with a port and path, never a URL.
MIRROR_PATTERN = re.compile(r"^[A-Za-z0-9.-]+(:[0-9]+)?(/[A-Za-z0-9._/-]*)?\Z")


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
    """

    name: str
    image: str
    ports: list = field(default_factory=list)
    volumes: list = field(default_factory=list)
    environment: list = field(default_factory=list)
    command: str = ""
    is_autostart: bool = True

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
        }


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
        for mirror in self.mirrors:
            if not MIRROR_PATTERN.match(mirror):
                raise ModuleApplyError("mirror_invalid", {"mirror": mirror})

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
