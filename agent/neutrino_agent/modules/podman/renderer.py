"""Rendering declared containers and hub containers into systemd units.

Each container is one unit, ``<name>.service``, whose ``ExecStart`` runs
``podman run`` with the flags Podman 3.4 already has, and one root-only
environment file, ``<name>.env``, which the unit reads with ``--env-file``,
so no value of the environment is in the unit or on a command line. A hub
container is rendered the same way with its module's label and network, the
units it starts after, the image reference the store holds and its page
port on loopback. On Windows and macOS the same files go into a Podman
machine, carried by one root script that :class:`PodmanMachineScriptRenderer`
writes.

Pure: config in, one file's text per container out.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field

from neutrino_agent.modules.podman.config import (
    PodmanConfig,
    PodmanContainer,
    PodmanHubContainer,
)
from neutrino_agent.modules.podman.constants import (
    PODMAN_BINARY,
    PODMAN_CGROUPS,
    PODMAN_CID_FILE,
    PODMAN_CONTAINER_ACTIONS,
    PODMAN_DEFAULT_NETWORK,
    PODMAN_ENV_DIR,
    PODMAN_ENV_SUFFIX,
    PODMAN_GENERATED_MARKER,
    PODMAN_HOST_ALIAS,
    PODMAN_MACHINE_CGROUPS,
    PODMAN_MODULE_LABEL,
    PODMAN_PAGE_ADDRESS,
    PODMAN_QUADLET_DIRS,
    PODMAN_QUADLET_SUFFIX,
    PODMAN_REGISTRIES_CONF_PATH,
    PODMAN_RM_BINARY,
    PODMAN_RUNTIME,
    PODMAN_STOP_EXIT_CODE,
    PODMAN_STOP_TIMEOUT_S,
    PODMAN_UNIT_DIR,
    PODMAN_UNIT_START_TIMEOUT_S,
    PODMAN_UNIT_STOP_MARGIN_S,
    PODMAN_UNIT_SUFFIX,
)
from neutrino_agent.modules.podman.machine_paths import split_volume, to_machine

# What every root script begins with: where the files go, how a generated
# file is told apart, and ``put``, which writes one file from its base64
# text with a mode when it differs and prints ``changed:`` for it. A fourth
# argument is a sed expression that blanks the source sets' values: a file
# whose only change is one of them is kept.
_MACHINE_SCRIPT_HEAD = """{marker_comment}
units={units}
envs={envs}
mirrors={mirrors}
marker={marker}
restart=''
changed=''
start=''
status=0
put() {{
    printf '%s' "$2" | base64 -d > "$1.new" || exit 1
    chmod "$3" "$1.new" || exit 1
    if cmp -s "$1.new" "$1"; then
        rm -f "$1.new"
        return 1
    fi
    if [ -n "$4" ] && [ -f "$1" ] && [ "$(sed -E "$4" "$1.new")" = "$(sed -E "$4" "$1")" ]; then
        rm -f "$1.new"
        return 1
    fi
    mv -f "$1.new" "$1" || exit 1
    echo "changed: $1"
}}
umask 077
mkdir -p "$units" "$envs" || exit 1
chmod 700 "$envs" || exit 1
"""

# Each marked Quadlet file an earlier build wrote is stopped and removed; a
# declared container whose unit was active is started again at the end.
_MACHINE_SCRIPT_QUADLET = """for file in {files}; do
    [ -f "$file" ] || continue
    [ "$(head -n 1 "$file")" = "$marker" ] || continue
    name=$(basename "$file" {suffix})
    if systemctl is-active --quiet "$name.service"; then
        case {declared} in
        *" $name "*) start="$start $name" ;;
        esac
    fi
    systemctl stop "$name.service"
    rm -f "$file"
    echo "changed: -$file"
done
"""

# Every marked unit and environment file the configuration no longer names
# is stopped, disabled and removed; a file a person wrote there is left.
_MACHINE_SCRIPT_STALE = """for file in "$units"/*.service; do
    [ -f "$file" ] || continue
    name=$(basename "$file" .service)
    case {declared} in
    *" $name "*) continue ;;
    esac
    [ "$(head -n 1 "$file")" = "$marker" ] || continue
    systemctl stop "$name.service"
    systemctl disable --no-reload "$name.service"
    rm -f "$file" "$envs/$name.env"
    echo "changed: -$file"
done
for file in "$envs"/*.env; do
    [ -f "$file" ] || continue
    name=$(basename "$file" .env)
    case {declared} in
    *" $name "*) continue ;;
    esac
    [ "$(head -n 1 "$file")" = "$marker" ] || continue
    rm -f "$file"
    echo "changed: -$file"
done
"""

_MACHINE_SCRIPT_MIRRORS_PUT = """mkdir -p "$(dirname "$mirrors")" || exit 1
put "$mirrors" {encoded} 644 || :
"""

_MACHINE_SCRIPT_MIRRORS_REMOVE = """if [ -f "$mirrors" ]; then
    rm -f "$mirrors"
    echo "changed: -$mirrors"
fi
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
_MACHINE_SCRIPT_DROP = """units={units}
envs={envs}
marker={marker}
for name in {names}; do
    file="$units/$name.service"
    [ -f "$file" ] || continue
    [ "$(head -n 1 "$file")" = "$marker" ] || continue
    systemctl stop "$name.service"
    systemctl disable --no-reload "$name.service"
    rm -f "$file" "$envs/$name.env"
    echo "changed: -$file"
done
systemctl daemon-reload
"""

# Stops and disables every marked unit with one systemctl call. systemd stops
# them in the order their After= names.
_MACHINE_SCRIPT_STOP = """units={units}
marker={marker}
names=''
for file in "$units"/*.service; do
    [ -f "$file" ] || continue
    [ "$(head -n 1 "$file")" = "$marker" ] || continue
    names="$names $(basename "$file")"
done
[ -z "$names" ] || systemctl disable --now $names
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


def environment_path(name: str) -> str:
    """Where one container's environment file is, on Linux and in a Podman machine.

    Args:
        name: The container's name.

    Returns:
        ``<env dir>/<name>.env``.
    """
    return f"{PODMAN_ENV_DIR}/{name}{PODMAN_ENV_SUFFIX}"


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
    """An environment file with the values of the given variables blanked.

    Two files that read the same through this differ only in what the
    source sets chose, and the older one is kept.

    Args:
        text: An environment file.
        keys: The variables whose values are blanked.

    Returns:
        The text, each ``KEY=value`` line of those variables ending at its
        ``=``.
    """
    for key in keys:
        text = re.sub(rf"(?m)^({re.escape(key)}=).*$", r"\1", text)
    return text


def source_sed(keys) -> str:
    """The sed expression the root script blanks the given variables with.

    Args:
        keys: The variables, each a plain environment name.

    Returns:
        ``s/^((K1|K2)=).*/\\1/``; empty for no variable.
    """
    if not keys:
        return ""
    return "s/^((" + "|".join(keys) + r")=).*/\1/"


def machine_stop_script(*, root: str = "") -> str:
    """The root script that stops and disables every generated container in a machine.

    Args:
        root: A directory every path in the machine is under; empty is the
            machine's own ``/``.

    Returns:
        The POSIX sh text; the files stay.
    """
    return _MACHINE_SCRIPT_STOP.format(
        units=_shell_quoted(root + PODMAN_UNIT_DIR),
        marker=_shell_quoted(PODMAN_GENERATED_MARKER),
    )


def machine_drop_script(names: list, *, root: str = "") -> str:
    """The root script that stops some containers and removes their generated files.

    Args:
        names: The containers, each already checked against
            ``CONTAINER_NAME_PATTERN``.
        root: A directory every path in the machine is under; empty is the
            machine's own ``/``.

    Returns:
        The POSIX sh text; a unit without the generated marker stays.
    """
    return _MACHINE_SCRIPT_DROP.format(
        units=_shell_quoted(root + PODMAN_UNIT_DIR),
        envs=_shell_quoted(root + PODMAN_ENV_DIR),
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
            network it does not name gets no ``--add-host``.
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
    """One container as the renderer writes it: the declared knobs and what a hub container adds.

    Attributes:
        container: The knobs a declared container has.
        image: The image reference the unit names.
        environment: The ``KEY=value`` lines, source sets filled in.
        add_host: The gateway ``host.containers.internal`` names; empty
            for none.
        label: ``neutrino.module=<module>`` for a hub container, else empty.
        network: The network it joins; empty for Podman's default.
        after: The units it requires and starts after.
        page_publish: ``127.0.0.1:<host>:<page_port>``; empty for none.
        stop_timeout_s: The seconds ``podman stop`` gives it.
        success_exit_codes: The exit codes its unit counts as a clean stop.
    """

    container: PodmanContainer
    image: str
    environment: list
    add_host: str = ""
    label: str = ""
    network: str = ""
    after: tuple = ()
    page_publish: str = ""
    stop_timeout_s: int = PODMAN_STOP_TIMEOUT_S
    success_exit_codes: tuple = (PODMAN_STOP_EXIT_CODE,)


class PodmanUnitRenderer:
    """Builds one systemd unit and one environment file per declared and hub container."""

    def __init__(
        self,
        *,
        config: PodmanConfig,
        machine_os_name: str = "",
        context: "PodmanRenderContext | None" = None,
    ):
        """
        Args:
            config: The declared containers and the hub containers.
            machine_os_name: The computer's system when the files go into
                a Podman machine, which writes each volume's folder as the
                machine names it, runs the machine's cgroups mode and adds
                no host; empty renders this machine's own files.
            context: What the apply found; None renders with nothing found.
        """
        self._config = config
        self._machine_os_name = machine_os_name
        self._context = context if context is not None else PodmanRenderContext()

    def render(self) -> dict:
        """Render the unit of every declared container and every hub container.

        Returns:
            File contents keyed by file name, ``<name>.service``.
        """
        return {
            f"{held.container.name}{PODMAN_UNIT_SUFFIX}": self._render_unit(held)
            for held in self._rendered()
        }

    def environment_files(self) -> dict:
        """Render the environment file of every declared and hub container.

        Returns:
            File contents keyed by file name, ``<name>.env``: the generated
            marker, then one ``KEY=value`` line per variable.
        """
        return {
            f"{held.container.name}{PODMAN_ENV_SUFFIX}": "\n".join(
                [PODMAN_GENERATED_MARKER, *held.environment, ""]
            )
            for held in self._rendered()
        }

    def source_keys(self) -> dict:
        """The variables a source set fills in, by the container whose file holds them.

        Returns:
            Container name to its variables; a container whose environment
            no set fills in is left out.
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
                    after=tuple(f"{name}{PODMAN_UNIT_SUFFIX}" for name in hub.after),
                    page_publish=(
                        f"{PODMAN_PAGE_ADDRESS}:{page}:{hub.page_port}"
                        if hub.page_port and page
                        else ""
                    ),
                    stop_timeout_s=hub.stop_timeout_s or PODMAN_STOP_TIMEOUT_S,
                    success_exit_codes=(
                        PODMAN_STOP_EXIT_CODE,
                        *hub.success_exit_codes,
                    ),
                )
            )
        return rendered

    def _gateway(self, network: str) -> str:
        """The gateway ``host.containers.internal`` names on one network, empty for none."""
        if self._machine_os_name:
            return ""
        return str(self._context.gateways.get(network, "") or "")

    def _volumes(self, container: PodmanContainer) -> list:
        """The container's volumes, each folder as the machine names it."""
        if not self._machine_os_name:
            return list(container.volumes)
        return [
            to_machine(volume, os_name=self._machine_os_name)
            for volume in container.volumes
        ]

    def _render_unit(self, held: _RenderedContainer) -> str:
        container = held.container
        volumes = self._volumes(container)
        lines = [
            PODMAN_GENERATED_MARKER,
            "",
            "[Unit]",
            f"Description={container.name} container",
            "Wants=network-online.target",
            "After=network-online.target",
        ]
        for unit in held.after:
            lines += [f"Requires={unit}", f"After={unit}"]
        for volume in volumes:
            source, _ = split_volume(volume, os_name="linux")
            if source.startswith("/"):
                lines.append(f"RequiresMountsFor={_mount_word(source)}")
        cid = PODMAN_CID_FILE
        lines += [
            "",
            "[Service]",
            "Environment=PODMAN_SYSTEMD_UNIT=%n",
            "Type=notify",
            "NotifyAccess=all",
            "Delegate=yes",
            "KillMode=mixed",
            "Restart=on-failure",
            # A container that ends on the stop's SIGTERM exits 143; SIGKILL
            # from outside stays a failure, which Restart answers.
            "SuccessExitStatus="
            + " ".join(str(code) for code in held.success_exit_codes),
            # A first pull of a large image takes longer than the default
            # start timeout allows.
            f"TimeoutStartSec={PODMAN_UNIT_START_TIMEOUT_S}",
            f"TimeoutStopSec={held.stop_timeout_s + PODMAN_UNIT_STOP_MARGIN_S}",
            # Podman 3.4's run fails on a cid file that is already there.
            f"ExecStartPre=-{PODMAN_RM_BINARY} -f {cid}",
            f"ExecStart={' '.join(self._run_command(held, volumes))}",
            f"ExecStop={PODMAN_BINARY} stop --ignore -t {held.stop_timeout_s} "
            f"--cidfile={cid}",
            f"ExecStopPost=-{PODMAN_BINARY} rm -f --ignore --cidfile={cid}",
            "",
            "[Install]",
            "WantedBy=multi-user.target",
            "",
        ]
        return "\n".join(lines)

    def _run_command(self, held: _RenderedContainer, volumes: list) -> list:
        container = held.container
        cgroups = PODMAN_MACHINE_CGROUPS if self._machine_os_name else PODMAN_CGROUPS
        command = [
            PODMAN_BINARY,
            "run",
            f"--cidfile={PODMAN_CID_FILE}",
            f"--cgroups={cgroups}",
        ]
        if not self._machine_os_name:
            command += ["--runtime", PODMAN_RUNTIME]
        command += [
            "--sdnotify=conmon",
            "-d",
            "--replace",
            "--rm",
            "--name",
            container.name,
        ]
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
        for volume in volumes:
            command += ["-v", _unit_word(volume)]
        command += ["--env-file", environment_path(container.name)]
        command.append(_unit_word(held.image))
        if container.command:
            # Passed through, so systemd splits it into the container's
            # command and its arguments.
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

    The script carries every unit, every environment file and the mirrors
    drop-in base64-encoded. It stops and removes the Quadlet files an
    earlier build wrote, writes the files that differ with their modes,
    keeping an environment file whose only change is a source set's value,
    removes the generated files the configuration no longer names, enables
    and disables the units, reloads systemd, restarts each changed
    container that starts at boot or runs, and starts each unchanged one
    that starts at boot and does not run. It prints one ``changed: <file>``
    line per change, ``-<file>`` for a removal, and exits non-zero when
    systemd refuses.
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
        """
        renderer = PodmanUnitRenderer(
            config=self._config, machine_os_name=self._os_name, context=self._context
        )
        units = renderer.render()
        environments = renderer.environment_files()
        source_keys = renderer.source_keys()
        containers = [*self._config.containers, *self._config.hub_containers]
        names = [container.name for container in containers]
        declared = _shell_quoted(" ".join(["", *names, ""]))
        parts = [
            _MACHINE_SCRIPT_HEAD.format(
                marker_comment=PODMAN_GENERATED_MARKER,
                units=_shell_quoted(self._root + PODMAN_UNIT_DIR),
                envs=_shell_quoted(self._root + PODMAN_ENV_DIR),
                mirrors=_shell_quoted(self._root + PODMAN_REGISTRIES_CONF_PATH),
                marker=_shell_quoted(PODMAN_GENERATED_MARKER),
            ),
            _MACHINE_SCRIPT_QUADLET.format(
                files=" ".join(
                    f"{_shell_quoted(self._root + directory)}/*{PODMAN_QUADLET_SUFFIX}"
                    for directory in PODMAN_QUADLET_DIRS
                ),
                suffix=PODMAN_QUADLET_SUFFIX,
                declared=declared,
            ),
        ]
        for container in containers:
            name = container.name
            sed = source_sed(source_keys.get(name, ()))
            kept = f" {_shell_quoted(sed)}" if sed else ""
            variable = "restart" if container.is_autostart else "changed"
            verb = "enable" if container.is_autostart else "disable"
            parts.append(
                "is_changed=''\n"
                f'put "$units/{name}{PODMAN_UNIT_SUFFIX}" '
                f"{_encoded(units[name + PODMAN_UNIT_SUFFIX])} 644 && is_changed=1\n"
                f'put "$envs/{name}{PODMAN_ENV_SUFFIX}" '
                f"{_encoded(environments[name + PODMAN_ENV_SUFFIX])} 600{kept} "
                "&& is_changed=1\n"
                'if [ -n "$is_changed" ]; then\n'
                f'    {variable}="${variable} {name}"\n'
            )
            if container.is_autostart:
                parts.append(f'else\n    start="$start {name}"\n')
            parts.append(
                f"fi\nsystemctl {verb} --no-reload {name}{PODMAN_UNIT_SUFFIX} || exit 1\n"
            )
        parts.append(_MACHINE_SCRIPT_STALE.format(declared=declared))
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


def _unit_word(value: str) -> str:
    """One argument of a unit's command line: specifiers and variables
    escaped, and quoted where systemd would split it."""
    escaped = value.replace("%", "%%").replace("$", "$$")
    if escaped and not any(
        character.isspace() or character in "\"'\\;" for character in escaped
    ):
        return escaped
    return '"' + escaped.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _mount_word(path: str) -> str:
    """One path of ``RequiresMountsFor=``: specifiers escaped, and quoted
    where systemd would split it."""
    escaped = path.replace("%", "%%")
    if not any(character.isspace() or character in "\"'\\" for character in escaped):
        return escaped
    return '"' + escaped.replace("\\", "\\\\").replace('"', '\\"') + '"'
