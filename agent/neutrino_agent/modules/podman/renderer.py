"""Rendering declared containers into systemd units.

Quadlet turns a ``.container`` file into an ordinary systemd unit, so a
declared container is supervised, journalled and comes back with the
machine. Quadlet arrived in podman 4.4; :class:`PodmanUnitRenderer` writes
the unit Quadlet would have generated for an older podman. The unit is
called ``<name>.service`` either way.

Pure: config in, one file's text per container out.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

from neutrino_agent.modules.podman.config import PodmanConfig, PodmanContainer
from neutrino_agent.modules.podman.constants import (
    PODMAN_BINARY,
    PODMAN_GENERATED_MARKER,
)


def qualified_image(image: str) -> str:
    """The fully-qualified form of an image reference.

    A unit file must not depend on short-name resolution, which varies by
    distribution and can stop a boot-time pull to ask a question.

    Args:
        image: A reference, short or already qualified.

    Returns:
        The reference with its registry spelled out.
    """
    first = image.split("/", 1)[0]
    if "/" in image and ("." in first or ":" in first):
        return image
    if "/" not in image:
        return f"docker.io/library/{image}"
    return f"docker.io/{image}"


class PodmanQuadletRenderer:
    """Builds one Quadlet ``.container`` file per declared container."""

    def __init__(self, *, config: PodmanConfig):
        """
        Args:
            config: The parsed container declarations.
        """
        self._config = config

    def render(self) -> dict:
        """Render every declared container.

        Returns:
            File contents keyed by file name, ``<name>.container``.
        """
        return {
            f"{container.name}.container": self._render_container(container)
            for container in self._config.containers
        }

    def _render_container(self, container: PodmanContainer) -> str:
        lines = [
            PODMAN_GENERATED_MARKER,
            "",
            "[Unit]",
            f"Description={container.name} container",
            "After=network-online.target",
            "",
            "[Container]",
            f"ContainerName={container.name}",
            f"Image={qualified_image(container.image)}",
        ]
        for port in container.ports:
            lines.append(f"PublishPort={port}")
        for volume in container.volumes:
            lines.append(f"Volume={volume}")
        for entry in container.environment:
            lines.append(f"Environment={entry}")
        if container.command:
            lines.append(f"Exec={container.command}")
        lines += [
            "",
            "[Service]",
            # Pulling a large image on first start takes longer than the
            # default start timeout allows.
            "TimeoutStartSec=900",
            "Restart=on-failure",
        ]
        if container.is_autostart:
            lines += ["", "[Install]", "WantedBy=multi-user.target"]
        lines.append("")
        return "\n".join(lines)


class PodmanUnitRenderer:
    """Builds one systemd ``.service`` file per declared container.

    For a podman too old for Quadlet: the container is described on the
    ``podman run`` command line, and the same properties carry across.
    """

    def __init__(self, *, config: PodmanConfig):
        """
        Args:
            config: The declared containers.
        """
        self._config = config

    def render(self) -> dict:
        """Render every declared container.

        Returns:
            File contents keyed by file name, ``<name>.service``.
        """
        return {
            f"{container.name}.service": self._render_container(container)
            for container in self._config.containers
        }

    def _render_container(self, container: PodmanContainer) -> str:
        lines = [
            PODMAN_GENERATED_MARKER,
            "",
            "[Unit]",
            f"Description={container.name} container",
            "After=network-online.target",
            "",
            "[Service]",
            "TimeoutStartSec=900",
            "Restart=on-failure",
            # A container left behind by a hard stop would make the next
            # start fail on the name alone.
            f"ExecStartPre=-{PODMAN_BINARY} rm -f {container.name}",
            f"ExecStart={' '.join(self._run_command(container))}",
            f"ExecStop={PODMAN_BINARY} stop -t 10 {container.name}",
        ]
        if container.is_autostart:
            lines += ["", "[Install]", "WantedBy=multi-user.target"]
        lines.append("")
        return "\n".join(lines)

    def _run_command(self, container: PodmanContainer) -> list:
        command = [PODMAN_BINARY, "run", "--rm", "--name", container.name]
        for port in container.ports:
            command += ["-p", port]
        for volume in container.volumes:
            command += ["-v", volume]
        for entry in container.environment:
            command += ["-e", _quoted(entry)]
        command.append(qualified_image(container.image))
        if container.command:
            # Passed through rather than split, so systemd parses it the way
            # Quadlet's own Exec= would.
            command.append(container.command)
        return command


class PodmanRegistriesRenderer:
    """Builds the docker.io mirror drop-in."""

    def __init__(self, *, config: PodmanConfig):
        """
        Args:
            config: The declared mirrors.
        """
        self._config = config

    def render(self) -> str:
        """Render the drop-in.

        Returns:
            The registries.conf.d file, or an empty string when no mirrors
            are declared, which removes the drop-in.
        """
        if not self._config.mirrors:
            return ""
        lines = [
            PODMAN_GENERATED_MARKER,
            "",
            "[[registry]]",
            'prefix = "docker.io"',
            'location = "registry-1.docker.io"',
        ]
        for mirror in self._config.mirrors:
            lines += ["", "[[registry.mirror]]", f'location = "{mirror}"']
        lines.append("")
        return "\n".join(lines)


def _quoted(value: str) -> str:
    """One argument of a unit's command line, quoted if systemd needs it."""
    if not any(character.isspace() for character in value) and '"' not in value:
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
