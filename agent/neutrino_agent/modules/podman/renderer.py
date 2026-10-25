"""Rendering declared containers and hub containers into systemd units.

Quadlet turns a ``.container`` file into an ordinary systemd unit, so a
declared container is supervised, journalled and comes back with the
machine. From podman 4.6 Quadlet can add a host to a container;
:class:`PodmanUnitRenderer` writes the unit Quadlet would have generated for
an older podman. The unit is
called ``<name>.service`` either way. A hub container is rendered the same
way with its module's label and network, the units it starts after, the
image reference the store holds and its page port on loopback. On Windows
and macOS the same files go into a Podman machine, carried by one root
script that :class:`PodmanMachineScriptRenderer` writes.

Pure: config in, one file's text per container out.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import base64
import re
import textwrap
from dataclasses import dataclass, field

from neutrino_agent.modules.podman.config import (
    PodmanConfig,
    PodmanContainer,
    PodmanHubContainer,
)
from neutrino_agent.modules.podman.constants import (
    PODMAN_BINARY,
    PODMAN_CONTAINER_ACTIONS,
    PODMAN_DEFAULT_NETWORK,
    PODMAN_GENERATED_MARKER,
    PODMAN_HOST_ALIAS,
    PODMAN_MACHINE_BOOT_UNIT_LINK,
    PODMAN_MACHINE_BOOT_UNIT_NAME,
    PODMAN_MACHINE_BOOT_UNIT_PATH,
    PODMAN_MACHINE_CGROUPS_LINE,
    PODMAN_MACHINE_CONFIG_MOUNT_POINT,
    PODMAN_MACHINE_CONFIG_MOUNT_UNIT,
    PODMAN_MACHINE_QUADLET_DIRS,
    PODMAN_MODULE_LABEL,
    PODMAN_PAGE_ADDRESS,
    PODMAN_REGISTRIES_CONF_PATH,
)
from neutrino_agent.modules.podman.machine_paths import to_machine

# What every root script begins with: where the files go, how a generated
# file is told apart, and ``put``, which writes one file from its base64
# text when it differs and prints ``changed:`` for it. A third argument is a
# sed expression that blanks the source sets' values: a file whose only
# change is one of them is kept.
_MACHINE_SCRIPT_HEAD = """{marker_comment}
quadlet={quadlet}
mirrors={mirrors}
marker={marker}
restart=''
changed=''
start=''
status=0
put() {{
    printf '%s' "$2" | base64 -d > "$1.new" || exit 1
    if cmp -s "$1.new" "$1"; then
        rm -f "$1.new"
        return 1
    fi
    if [ -n "$3" ] && [ -f "$1" ] && [ "$(sed -E "$3" "$1.new")" = "$(sed -E "$3" "$1")" ]; then
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

# The boot unit is written and turned on while the machine's own mount unit
# puts the computer's folder on /etc/containers, and removed otherwise.
_MACHINE_SCRIPT_BOOT_REMOVE = """if [ -f {unit} ] && [ "$(head -n 1 {unit})" = "$marker" ]; then
    rm -f {unit} {link}
    echo "changed: -"{unit}
fi
"""

_MACHINE_SCRIPT_BOOT_PUT = """if [ -f {mount_unit} ]; then
    mkdir -p "$(dirname {link})" || exit 1
    put {unit} {encoded} || :
    if [ ! -L {link} ]; then
        ln -s ../{name} {link} || exit 1
        echo "changed: "{link}
    fi
else
{remove}fi
"""

# The boot unit: after the mount, systemd reads the Quadlet folder again and
# starts what multi-user.target wants, which a reload alone does not.
_MACHINE_BOOT_UNIT = """{marker}

[Unit]
Description=Start the declared containers after {mount_point} is mounted
RequiresMountsFor={mount_point}
After=local-fs.target

[Service]
Type=oneshot
ExecStart=/usr/bin/systemctl daemon-reload
ExecStart=/usr/bin/systemctl start --no-block multi-user.target

[Install]
WantedBy=multi-user.target
"""

# A changed container that is not started at boot is restarted only while
# it runs, and an unchanged one started at boot is started when it does not
# run, as on Linux.
_MACHINE_SCRIPT_TAIL = """systemctl daemon-reload || exit 1
for name in $changed; do
    if systemctl is-active --quiet "$name.service"; then
        restart="$restart $name"
    fi
done
for name in $restart; do
    systemctl restart "$name.service" || status=1
done
for name in $start; do
    if ! systemctl is-active --quiet "$name.service"; then
        systemctl start "$name.service" || status=1
    fi
done
exit "$status"
"""

# Stops the named containers and removes their generated files.
_MACHINE_SCRIPT_DROP = """quadlet={quadlet}
marker={marker}
for name in {names}; do
    file="$quadlet/$name.container"
    [ -f "$file" ] || continue
    [ "$(head -n 1 "$file")" = "$marker" ] || continue
    systemctl stop "$name.service"
    rm -f "$file"
    echo "changed: -$file"
done
systemctl daemon-reload
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


def hub_environment(
    container: PodmanHubContainer, context: PodmanRenderContext
) -> list:
    """A hub container's environment with its source sets filled in.

    Args:
        container: The hub container.
        context: What the apply found, whose ``sources`` holds each set's
            fastest source and ``variables`` each set's variables.

    Returns:
        Its own ``KEY=value`` lines, each ``{<set>}`` of a set it lists and
        the context knows replaced by that set's fastest source, then
        every variable of each such set with that source.
    """
    known = [name for name in container.source_sets if name in context.sources]
    lines = []
    for entry in container.environment:
        key, _, value = entry.partition("=")
        for name in known:
            value = value.replace("{" + name + "}", context.sources[name])
        lines.append(f"{key}={value}")
    for name in known:
        for variable in context.variables.get(name, ()):
            lines.append(f"{variable}={context.sources[name]}")
    return lines


def hub_source_keys(
    container: PodmanHubContainer, context: PodmanRenderContext
) -> list:
    """The variables of a hub container whose values come from a source set.

    Args:
        container: The hub container.
        context: What the apply found.

    Returns:
        Each variable of its own environment that names a set it lists, then
        each variable of those sets, in the order :func:`hub_environment`
        writes them.
    """
    known = [name for name in container.source_sets if name in context.sources]
    keys = []
    for entry in container.environment:
        key, _, value = entry.partition("=")
        if any("{" + name + "}" in value for name in known):
            keys.append(key)
    for name in known:
        keys += list(context.variables.get(name, ()))
    return keys


def source_neutral(text: str, keys) -> str:
    """A rendered file with the values of the given variables blanked.

    Two files that read the same through this differ only in what the
    source sets chose, and the older one is kept.

    Args:
        text: A Quadlet file or a plain unit.
        keys: The variables whose values are blanked.

    Returns:
        The text, each ``Environment=KEY=value`` line and each ``-e
        KEY=value`` argument of those variables ending at its ``=``.
    """
    for key in keys:
        name = re.escape(key)
        text = re.sub(rf"(?m)^(Environment={name}=).*$", r"\1", text)
        text = re.sub(rf'(-e "?{name}=)[^"\s]*"?', r"\1", text)
    return text


def source_sed(keys) -> str:
    """The sed expression the root script blanks the given variables with.

    Args:
        keys: The variables, each a plain environment name.

    Returns:
        ``s/^(Environment=(K1|K2)=).*/\\1/``; empty for no variable.
    """
    if not keys:
        return ""
    return "s/^(Environment=(" + "|".join(keys) + r")=).*/\1/"


def machine_boot_unit() -> str:
    """The unit that starts a machine's containers at boot after its ``/etc/containers`` is mounted.

    Returns:
        The systemd unit's text, the generated marker first.
    """
    return _MACHINE_BOOT_UNIT.format(
        marker=PODMAN_GENERATED_MARKER,
        mount_point=PODMAN_MACHINE_CONFIG_MOUNT_POINT,
    )


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


def machine_drop_script(names: list, *, os_name: str, root: str = "") -> str:
    """The root script that stops some containers and removes their generated files.

    Args:
        names: The containers, each already checked against
            ``CONTAINER_NAME_PATTERN``.
        os_name: The computer's system, ``windows`` or ``darwin``.
        root: A directory every path in the machine is under; empty is the
            machine's own ``/``.

    Returns:
        The POSIX sh text; a file without the generated marker stays.

    Raises:
        KeyError: For a system with no Podman machine.
    """
    return _MACHINE_SCRIPT_DROP.format(
        quadlet=_shell_quoted(root + PODMAN_MACHINE_QUADLET_DIRS[os_name]),
        marker=_shell_quoted(PODMAN_GENERATED_MARKER),
        names=" ".join(names),
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


@dataclass(frozen=True)
class PodmanRenderContext:
    """What an apply found on the machine that the rendered files name.

    Attributes:
        gateways: Network name to its gateway address; a container on a
            network it does not name gets no ``AddHost``.
        images: Hub container name to the image reference Podman's store
            holds with its digest.
        page_ports: Hub container name to the loopback port its
            ``page_port`` is published at.
        sources: Source set name to the fastest of its sources.
        variables: Source set name to the variables it writes.
    """

    gateways: dict = field(default_factory=dict)
    images: dict = field(default_factory=dict)
    page_ports: dict = field(default_factory=dict)
    sources: dict = field(default_factory=dict)
    variables: dict = field(default_factory=dict)


@dataclass(frozen=True)
class _RenderedContainer:
    """One container as both renderers write it: the declared knobs and what a hub container adds.

    Attributes:
        container: The knobs a declared container has.
        image: The image reference the file names.
        environment: The ``KEY=value`` lines, source sets filled in.
        add_host: The gateway ``host.containers.internal`` names; empty
            for none.
        label: ``neutrino.module=<module>`` for a hub container, else empty.
        network: The network it joins; empty for Podman's default.
        after: The units it requires and starts after.
        page_publish: ``127.0.0.1:<host>:<page_port>``; empty for none.
    """

    container: PodmanContainer
    image: str
    environment: list
    add_host: str = ""
    label: str = ""
    network: str = ""
    after: tuple = ()
    page_publish: str = ""


class _PodmanContainerFiles:
    """What both renderers share: every container as a :class:`_RenderedContainer`."""

    def __init__(
        self,
        *,
        config: PodmanConfig,
        context: "PodmanRenderContext | None" = None,
        is_host_added: bool = True,
    ):
        """
        Args:
            config: The declared containers and the hub containers to render.
            context: What the apply found; None renders with nothing found.
            is_host_added: Whether each container gets ``AddHost`` for the
                gateway of its network, as on Linux.
        """
        self._config = config
        self._context = context if context is not None else PodmanRenderContext()
        self._is_host_added = is_host_added

    def source_keys(self) -> dict:
        """The variables a source set fills in, by the file that holds them.

        Returns:
            File name, without its suffix, to its variables; a container
            whose environment no set fills in is left out.
        """
        keys = {}
        for container in self._config.hub_containers:
            held = hub_source_keys(container, self._context)
            if held:
                keys[container.name] = held
        return keys

    def _rendered(self) -> list:
        """Every declared container, then every hub container, ready to write."""
        rendered = [
            _RenderedContainer(
                container=container,
                image=qualified_image(container.image),
                environment=list(container.environment),
                add_host=self._gateway(PODMAN_DEFAULT_NETWORK),
            )
            for container in self._config.containers
        ]
        for hub in self._config.hub_containers:
            image = self._context.images.get(hub.name) or (
                f"{hub.sources[0]}@{hub.digest}" if hub.sources else hub.digest
            )
            page = self._context.page_ports.get(hub.name, 0)
            rendered.append(
                _RenderedContainer(
                    container=hub.as_container(),
                    image=image,
                    environment=hub_environment(hub, self._context),
                    add_host=self._gateway(hub.network),
                    label=f"{PODMAN_MODULE_LABEL}={hub.module}",
                    network=hub.network,
                    after=tuple(f"{name}.service" for name in hub.after),
                    page_publish=(
                        f"{PODMAN_PAGE_ADDRESS}:{page}:{hub.page_port}"
                        if hub.page_port and page
                        else ""
                    ),
                )
            )
        return rendered

    def _gateway(self, network: str) -> str:
        """The gateway ``host.containers.internal`` names on one network, empty for none."""
        if not self._is_host_added:
            return ""
        return str(self._context.gateways.get(network, "") or "")


class PodmanQuadletRenderer(_PodmanContainerFiles):
    """Builds one Quadlet ``.container`` file per declared and hub container."""

    def __init__(
        self,
        *,
        config: PodmanConfig,
        machine_os_name: str = "",
        context: "PodmanRenderContext | None" = None,
        is_add_host_key: bool = True,
    ):
        """
        Args:
            config: The declared containers and the hub containers.
            machine_os_name: The computer's system when the files go into
                a Podman machine, which writes each volume's folder as the
                machine names it, adds the machine's cgroups line and writes
                no host; empty renders this machine's own files.
            context: What the apply found; None renders with nothing found.
            is_add_host_key: Whether Quadlet reads ``AddHost=``, from
                Podman 5.3; otherwise the host goes into ``PodmanArgs=``.
        """
        super().__init__(
            config=config, context=context, is_host_added=not machine_os_name
        )
        self._machine_os_name = machine_os_name
        self._is_add_host_key = is_add_host_key

    def render(self) -> dict:
        """Render every declared container and every hub container.

        Returns:
            File contents keyed by file name, ``<name>.container``.
        """
        return {
            f"{held.container.name}.container": self._render_container(held)
            for held in self._rendered()
        }

    def _render_container(self, held: _RenderedContainer) -> str:
        container = held.container
        lines = [
            PODMAN_GENERATED_MARKER,
            "",
            "[Unit]",
            f"Description={container.name} container",
            "After=network-online.target",
        ]
        for unit in held.after:
            lines += [f"Requires={unit}", f"After={unit}"]
        lines += [
            "",
            "[Container]",
            f"ContainerName={container.name}",
            f"Image={held.image}",
        ]
        if held.label:
            lines.append(f"Label={held.label}")
        if held.network:
            lines.append(f"Network={held.network}")
        if held.add_host and self._is_add_host_key:
            lines.append(f"AddHost={PODMAN_HOST_ALIAS}:{held.add_host}")
        elif held.add_host:
            lines.append(f"PodmanArgs=--add-host={PODMAN_HOST_ALIAS}:{held.add_host}")
        for port in container.publish_ports:
            lines.append(f"PublishPort={port}")
        if held.page_publish:
            lines.append(f"PublishPort={held.page_publish}")
        for volume in container.volumes:
            if self._machine_os_name:
                volume = to_machine(volume, os_name=self._machine_os_name)
            lines.append(f"Volume={volume}")
        for entry in held.environment:
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


class PodmanUnitRenderer(_PodmanContainerFiles):
    """Builds one systemd ``.service`` file per declared and hub container.

    For a podman too old for Quadlet: the container is described on the
    ``podman run`` command line, and the same properties carry across.
    """

    def __init__(
        self, *, config: PodmanConfig, context: "PodmanRenderContext | None" = None
    ):
        """
        Args:
            config: The declared containers and the hub containers.
            context: What the apply found; None renders with nothing found.
        """
        super().__init__(config=config, context=context)

    def render(self) -> dict:
        """Render every declared container and every hub container.

        Returns:
            File contents keyed by file name, ``<name>.service``.
        """
        return {
            f"{held.container.name}.service": self._render_container(held)
            for held in self._rendered()
        }

    def _render_container(self, held: _RenderedContainer) -> str:
        container = held.container
        lines = [
            PODMAN_GENERATED_MARKER,
            "",
            "[Unit]",
            f"Description={container.name} container",
            "After=network-online.target",
        ]
        for unit in held.after:
            lines += [f"Requires={unit}", f"After={unit}"]
        lines += [
            "",
            "[Service]",
            "TimeoutStartSec=900",
            "Restart=on-failure",
            # A container left behind by a hard stop would make the next
            # start fail on the name alone.
            f"ExecStartPre=-{PODMAN_BINARY} rm -f {container.name}",
            f"ExecStart={' '.join(self._run_command(held))}",
            f"ExecStop={PODMAN_BINARY} stop -t 10 {container.name}",
        ]
        if container.is_autostart:
            lines += ["", "[Install]", "WantedBy=multi-user.target"]
        lines.append("")
        return "\n".join(lines)

    def _run_command(self, held: _RenderedContainer) -> list:
        container = held.container
        command = [PODMAN_BINARY, "run", "--rm", "--name", container.name]
        if held.label:
            command += ["--label", held.label]
        if held.network:
            command += ["--network", held.network]
        if held.add_host:
            command += ["--add-host", f"{PODMAN_HOST_ALIAS}:{held.add_host}"]
        for port in container.publish_ports:
            command += ["-p", port]
        if held.page_publish:
            command += ["-p", held.page_publish]
        for volume in container.volumes:
            command += ["-v", volume]
        for entry in held.environment:
            command += ["-e", _quoted(entry)]
        command.append(held.image)
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
    """Builds the one root script that makes the declared and hub containers true in a Podman machine.

    The script carries every Quadlet file and the mirrors drop-in
    base64-encoded, writes the ones that differ, keeping a file whose only
    change is a source set's value, removes the generated files
    the configuration no longer names, reloads systemd, restarts each
    changed container that starts at boot or runs, and starts each unchanged
    one that starts at boot and does not run. Where the Quadlet folder
    is under ``/etc/containers``, it also writes the boot unit while the
    machine mounts that folder. It prints one ``changed: <file>`` line per
    change, ``-<file>`` for a removal, and exits non-zero when systemd
    refuses.
    """

    def __init__(
        self,
        *,
        config: PodmanConfig,
        os_name: str,
        root: str = "",
        context: "PodmanRenderContext | None" = None,
    ):
        """
        Args:
            config: The parsed configuration, its hub containers those the
                apply renders.
            os_name: The computer's system, ``windows`` or ``darwin``.
            root: A directory every path in the machine is under; empty is
                the machine's own ``/``.
            context: What the apply found; None renders with nothing found.
        """
        self._config = config
        self._os_name = os_name
        self._root = root
        self._context = context

    def render(self) -> str:
        """Render the script.

        Returns:
            The POSIX sh text, read by ``sh -s`` as root in the machine.

        Raises:
            KeyError: For a system with no Podman machine.
        """
        quadlet = PodmanQuadletRenderer(
            config=self._config, machine_os_name=self._os_name, context=self._context
        )
        rendered = quadlet.render()
        source_keys = quadlet.source_keys()
        quadlet_dir = PODMAN_MACHINE_QUADLET_DIRS[self._os_name]
        parts = [
            _MACHINE_SCRIPT_HEAD.format(
                marker_comment=PODMAN_GENERATED_MARKER,
                quadlet=_shell_quoted(self._root + quadlet_dir),
                mirrors=_shell_quoted(self._root + PODMAN_REGISTRIES_CONF_PATH),
                marker=_shell_quoted(PODMAN_GENERATED_MARKER),
            )
        ]
        containers = [*self._config.containers, *self._config.hub_containers]
        for container in containers:
            text = rendered[f"{container.name}.container"]
            sed = source_sed(source_keys.get(container.name, ()))
            kept = f" {_shell_quoted(sed)}" if sed else ""
            variable = "restart" if container.is_autostart else "changed"
            parts.append(
                f'if put "$quadlet/{container.name}.container" '
                f"{_encoded(text)}{kept}; then\n"
                f'    {variable}="${variable} {container.name}"\n'
            )
            if container.is_autostart:
                parts.append(f'else\n    start="$start {container.name}"\n')
            parts.append("fi\n")
        names = [container.name for container in containers]
        declared = " ".join(["", *names, ""])
        parts.append(_MACHINE_SCRIPT_STALE.format(declared=_shell_quoted(declared)))
        mirrors = PodmanRegistriesRenderer(config=self._config).render()
        if mirrors:
            parts.append(_MACHINE_SCRIPT_MIRRORS_PUT.format(encoded=_encoded(mirrors)))
        else:
            parts.append(_MACHINE_SCRIPT_MIRRORS_REMOVE)
        if quadlet_dir.startswith(PODMAN_MACHINE_CONFIG_MOUNT_POINT + "/"):
            parts.append(self._boot_unit_part())
        parts.append(_MACHINE_SCRIPT_TAIL)
        return "".join(parts)

    def _boot_unit_part(self) -> str:
        """The script's lines that write or remove the boot unit."""
        paths = {
            "unit": _shell_quoted(self._root + PODMAN_MACHINE_BOOT_UNIT_PATH),
            "link": _shell_quoted(self._root + PODMAN_MACHINE_BOOT_UNIT_LINK),
        }
        remove = _MACHINE_SCRIPT_BOOT_REMOVE.format(**paths)
        if not self._config.containers and not self._config.hub_containers:
            return remove
        return _MACHINE_SCRIPT_BOOT_PUT.format(
            mount_unit=_shell_quoted(self._root + PODMAN_MACHINE_CONFIG_MOUNT_UNIT),
            name=PODMAN_MACHINE_BOOT_UNIT_NAME,
            encoded=_encoded(machine_boot_unit()),
            remove=textwrap.indent(remove, "    "),
            **paths,
        )


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
