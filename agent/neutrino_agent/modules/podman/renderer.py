"""Rendering declared containers into systemd units.

Quadlet turns a ``.container`` file into an ordinary systemd unit, so a
declared container is supervised, journalled and comes back with the
machine. Quadlet arrived in podman 4.4; :class:`PodmanUnitRenderer` writes
the unit Quadlet would have generated for an older podman. The unit is
called ``<name>.service`` either way. On Windows and macOS the same files
go into a Podman machine, carried by one root script that
:class:`PodmanMachineScriptRenderer` writes.

Pure: config in, one file's text per container out.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import base64

from neutrino_agent.modules.podman.config import PodmanConfig, PodmanContainer
from neutrino_agent.modules.podman.constants import (
    PODMAN_BINARY,
    PODMAN_CONTAINER_ACTIONS,
    PODMAN_GENERATED_MARKER,
    PODMAN_MACHINE_CGROUPS_LINE,
    PODMAN_MACHINE_QUADLET_DIRS,
    PODMAN_REGISTRIES_CONF_PATH,
)
from neutrino_agent.modules.podman.machine_paths import to_machine

# What every root script begins with: where the files go, how a generated
# file is told apart, and ``put``, which writes one file from its base64
# text when it differs and prints ``changed:`` for it.
_MACHINE_SCRIPT_HEAD = """{marker_comment}
quadlet={quadlet}
mirrors={mirrors}
marker={marker}
restart=''
changed=''
status=0
put() {{
    printf '%s' "$2" | base64 -d > "$1.new" || exit 1
    if cmp -s "$1.new" "$1"; then
        rm -f "$1.new"
        return 1
    fi
    mv -f "$1.new" "$1" || exit 1
    echo "changed: $1"
}}
mkdir -p "$quadlet" || exit 1
"""

# Every generated file the configuration no longer names is stopped and
# removed; a file a person wrote there is left.
_MACHINE_SCRIPT_STALE = """for file in "$quadlet"/*.container; do
    [ -f "$file" ] || continue
    name=$(basename "$file" .container)
    case {declared} in
    *" $name "*) continue ;;
    esac
    [ "$(head -n 1 "$file")" = "$marker" ] || continue
    systemctl stop "$name.service"
    rm -f "$file"
    echo "changed: -$file"
done
"""

_MACHINE_SCRIPT_MIRRORS_PUT = """mkdir -p "$(dirname "$mirrors")" || exit 1
put "$mirrors" {encoded} || :
"""

_MACHINE_SCRIPT_MIRRORS_REMOVE = """if [ -f "$mirrors" ]; then
    rm -f "$mirrors"
    echo "changed: -$mirrors"
fi
"""

# A changed container that is not started at boot is restarted only while
# it runs, as on Linux.
_MACHINE_SCRIPT_TAIL = """systemctl daemon-reload || exit 1
for name in $changed; do
    if systemctl is-active --quiet "$name.service"; then
        restart="$restart $name"
    fi
done
for name in $restart; do
    systemctl restart "$name.service" || status=1
done
exit "$status"
"""

_MACHINE_SCRIPT_STOP = """quadlet={quadlet}
marker={marker}
for file in "$quadlet"/*.container; do
    [ -f "$file" ] || continue
    [ "$(head -n 1 "$file")" = "$marker" ] || continue
    systemctl stop "$(basename "$file" .container).service"
done
"""


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


def machine_stop_script(*, os_name: str, root: str = "") -> str:
    """The root script that stops every generated container in a machine.

    Args:
        os_name: The computer's system, ``windows`` or ``darwin``.
        root: A directory every path in the machine is under; empty is the
            machine's own ``/``.

    Returns:
        The POSIX sh text; the files stay.

    Raises:
        KeyError: For a system with no Podman machine.
    """
    return _MACHINE_SCRIPT_STOP.format(
        quadlet=_shell_quoted(root + PODMAN_MACHINE_QUADLET_DIRS[os_name]),
        marker=_shell_quoted(PODMAN_GENERATED_MARKER),
    )


def machine_control_script(name: str, action: str) -> str:
    """The root script that starts, stops or restarts one declared container.

    Args:
        name: The container's name, already checked against
            ``CONTAINER_NAME_PATTERN``.
        action: One of :data:`PODMAN_CONTAINER_ACTIONS`.

    Returns:
        The POSIX sh text.

    Raises:
        ValueError: For an action outside the list.
    """
    if action not in PODMAN_CONTAINER_ACTIONS:
        raise ValueError(action)
    return f"systemctl {action} {name}.service\n"


def machine_journal_script(name: str, lines: int) -> str:
    """The root script that prints the tail of one container unit's journal.

    Args:
        name: The container's name, already checked against
            ``CONTAINER_NAME_PATTERN``.
        lines: How many lines to print.

    Returns:
        The POSIX sh text.
    """
    return (
        f"journalctl -u {name}.service -n {int(lines)} --no-pager "
        "--output short-iso\n"
    )


class PodmanQuadletRenderer:
    """Builds one Quadlet ``.container`` file per declared container."""

    def __init__(self, *, config: PodmanConfig, machine_os_name: str = ""):
        """
        Args:
            config: The parsed container declarations.
            machine_os_name: The computer's system when the files go into
                a Podman machine, which writes each volume's folder as the
                machine names it and adds the machine's cgroups line; empty
                renders this machine's own files.
        """
        self._config = config
        self._machine_os_name = machine_os_name

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
        for port in container.publish_ports:
            lines.append(f"PublishPort={port}")
        for volume in container.volumes:
            if self._machine_os_name:
                volume = to_machine(volume, os_name=self._machine_os_name)
            lines.append(f"Volume={volume}")
        for entry in container.environment:
            lines.append(f"Environment={entry}")
        if container.command:
            lines.append(f"Exec={container.command}")
        if self._machine_os_name:
            lines.append(PODMAN_MACHINE_CGROUPS_LINE)
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
        for port in container.publish_ports:
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


class PodmanMachineScriptRenderer:
    """Builds the one root script that makes the declared containers true in a Podman machine.

    The script carries every Quadlet file and the mirrors drop-in
    base64-encoded, writes the ones that differ, removes the generated files
    the configuration no longer names, reloads systemd and restarts each
    changed container that starts at boot or runs. It prints one ``changed:
    <file>`` line per change, ``-<file>`` for a removal, and exits non-zero
    when systemd refuses.
    """

    def __init__(self, *, config: PodmanConfig, os_name: str, root: str = ""):
        """
        Args:
            config: The parsed configuration.
            os_name: The computer's system, ``windows`` or ``darwin``.
            root: A directory every path in the machine is under; empty is
                the machine's own ``/``.
        """
        self._config = config
        self._os_name = os_name
        self._root = root

    def render(self) -> str:
        """Render the script.

        Returns:
            The POSIX sh text, read by ``sh -s`` as root in the machine.

        Raises:
            KeyError: For a system with no Podman machine.
        """
        rendered = PodmanQuadletRenderer(
            config=self._config, machine_os_name=self._os_name
        ).render()
        parts = [
            _MACHINE_SCRIPT_HEAD.format(
                marker_comment=PODMAN_GENERATED_MARKER,
                quadlet=_shell_quoted(
                    self._root + PODMAN_MACHINE_QUADLET_DIRS[self._os_name]
                ),
                mirrors=_shell_quoted(self._root + PODMAN_REGISTRIES_CONF_PATH),
                marker=_shell_quoted(PODMAN_GENERATED_MARKER),
            )
        ]
        for container in self._config.containers:
            text = rendered[f"{container.name}.container"]
            variable = "restart" if container.is_autostart else "changed"
            parts.append(
                f'if put "$quadlet/{container.name}.container" {_encoded(text)}; then\n'
                f'    {variable}="${variable} {container.name}"\n'
                "fi\n"
            )
        declared = " ".join(["", *self._config.declared_names, ""])
        parts.append(_MACHINE_SCRIPT_STALE.format(declared=_shell_quoted(declared)))
        mirrors = PodmanRegistriesRenderer(config=self._config).render()
        if mirrors:
            parts.append(_MACHINE_SCRIPT_MIRRORS_PUT.format(encoded=_encoded(mirrors)))
        else:
            parts.append(_MACHINE_SCRIPT_MIRRORS_REMOVE)
        parts.append(_MACHINE_SCRIPT_TAIL)
        return "".join(parts)


def _encoded(text: str) -> str:
    """One file's text as the script carries it: base64 in single quotes."""
    return "'" + base64.b64encode(text.encode("utf-8")).decode("ascii") + "'"


def _shell_quoted(text: str) -> str:
    """One word for sh, single-quoted."""
    return "'" + text.replace("'", "'\\''") + "'"


def _quoted(value: str) -> str:
    """One argument of a unit's command line, quoted if systemd needs it."""
    if not any(character.isspace() for character in value) and '"' not in value:
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
