"""The declared containers: what this box runs, as configuration.

A container declared here becomes a Quadlet unit, so it survives reboots and
appears to systemd like any other service. Containers started by hand at a
shell still show up on the page's live list — they are just not owed a
restart after a power cut.

The knobs are deliberately few: image, ports, volumes, environment, and
whether it starts at boot. Everything on the default network; custom
networks, healthchecks and the rest of the compose surface stay out until a
real container needs them.

Pure: parsing and validation only. Rendering is :mod:`neutrino_hub.modules.podman.renderer`;
making it true on the box is :mod:`neutrino_hub.modules.podman.ops`.
"""

import re
from dataclasses import dataclass, field

# A container's name becomes a systemd unit name and a shell argument, so it
# is kept to a charset that cannot smuggle syntax into either.
CONTAINER_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}\Z")

# host:container, an optional /udp, ports in range.
PORT_MAPPING_PATTERN = re.compile(r"^\d{1,5}:\d{1,5}(/(tcp|udp))?\Z")

# KEY=value with a sane key; the value may hold anything printable.
ENVIRONMENT_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=[^\n]*\Z")

# A registry mirror is a host, optionally with a port and path — never a URL:
# registries.conf takes locations without a scheme.
MIRROR_PATTERN = re.compile(r"^[A-Za-z0-9.-]+(:[0-9]+)?(/[A-Za-z0-9._/-]*)?\Z")


@dataclass
class PodmanContainer:
    """One declared container.

    Attributes:
        name: The container's and its systemd unit's name.
        image: Fully-qualified image, for example ``docker.io/library/redis:7``.
        ports: Published ports as ``host:container`` or ``host:container/udp``.
        volumes: Mounts as ``source:destination``; an absolute source binds a
            host path, a bare name is a named volume podman manages.
        environment: Variables as ``KEY=value`` lines.
        command: What to run instead of the image's own command. Empty keeps
            the image's default — right for nginx or redis, fatal for images
            like python whose default is a REPL that exits without a
            terminal.
        is_autostart: Whether it comes up with the box.
    """

    name: str
    image: str
    ports: list[str] = field(default_factory=list)
    volumes: list[str] = field(default_factory=list)
    environment: list[str] = field(default_factory=list)
    command: str = ""
    is_autostart: bool = True

    @classmethod
    def from_dict(cls, data: dict) -> "PodmanContainer":
        return cls(
            name=data.get("name", ""),
            image=data.get("image", ""),
            ports=list(data.get("ports", [])),
            volumes=list(data.get("volumes", [])),
            environment=list(data.get("environment", [])),
            command=data.get("command", ""),
            is_autostart=bool(data.get("is_autostart", True)),
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "image": self.image,
            "ports": self.ports,
            "volumes": self.volumes,
            "environment": self.environment,
            "command": self.command,
            "is_autostart": self.is_autostart,
        }


@dataclass
class PodmanConfig:
    """Everything ``config/podman/podman.json`` holds.

    Attributes:
        containers: The declared containers.
        mirrors: Registry mirrors for docker.io, tried in order before the
            registry itself — how image pulls survive a slow or filtered path
            to Docker Hub.
    """

    containers: list[PodmanContainer] = field(default_factory=list)
    mirrors: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "PodmanConfig":
        return cls(
            containers=[
                PodmanContainer.from_dict(entry) for entry in data.get("containers", [])
            ],
            mirrors=list(data.get("mirrors", [])),
        )

    def to_dict(self) -> dict:
        return {
            "containers": [container.to_dict() for container in self.containers],
            "mirrors": self.mirrors,
        }

    def validate(self) -> None:
        """Check the configuration holds together.

        Raises:
            ValueError: Naming the first problem found. Each check stands
                between a saved form and a unit systemd refuses — or a flag
                smuggled into a command line.
        """
        seen: set[str] = set()
        for container in self.containers:
            if not CONTAINER_NAME_PATTERN.match(container.name):
                raise ValueError(
                    f"container name {container.name!r} is not usable; use "
                    f"lowercase letters, digits, '-' and '_'"
                )
            if container.name in seen:
                raise ValueError(f"two containers are both named {container.name!r}")
            seen.add(container.name)
            if not container.image or any(
                character.isspace() for character in container.image
            ):
                raise ValueError(
                    f"container {container.name!r} needs an image reference "
                    f"with no spaces, got {container.image!r}"
                )
            for port in container.ports:
                if not PORT_MAPPING_PATTERN.match(port):
                    raise ValueError(
                        f"port {port!r} on {container.name!r} is not "
                        f"host:container or host:container/udp"
                    )
            for volume in container.volumes:
                self._validate_volume(container.name, volume)
            for line in container.environment:
                if not ENVIRONMENT_PATTERN.match(line):
                    raise ValueError(
                        f"environment entry {line!r} on {container.name!r} "
                        f"is not KEY=value"
                    )
            if "\n" in container.command:
                raise ValueError(f"command on {container.name!r} cannot span lines")
        for mirror in self.mirrors:
            if not MIRROR_PATTERN.match(mirror):
                raise ValueError(
                    f"mirror {mirror!r} is not a registry host — drop the "
                    f"https:// and any trailing slash"
                )

    def _validate_volume(self, name: str, volume: str) -> None:
        if "\n" in volume or ":" not in volume:
            raise ValueError(f"volume {volume!r} on {name!r} is not source:destination")
        source, _, destination = volume.partition(":")
        if not destination.startswith("/"):
            raise ValueError(
                f"volume {volume!r} on {name!r} needs an absolute "
                f"destination inside the container"
            )
        is_host_path = source.startswith("/")
        is_named = CONTAINER_NAME_PATTERN.match(source) is not None
        if not is_host_path and not is_named:
            raise ValueError(
                f"volume source {source!r} on {name!r} is neither an "
                f"absolute host path nor a volume name"
            )
