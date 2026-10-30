"""The hub containers: what each container module a machine has runs on Containers.

A container module composes its containers as :class:`HubContainer`
values, through its entry in :data:`HUB_CONTAINER_COMPOSERS`. The one
composer here turns them into the ``hub_containers`` of the Containers
module's state: each with its module, its image as the digest and sources
its module's manifest entry pins for the machine's platform, the source
sets that entry lists, and started with the box while the module's
``want`` is ``running``. A module's containers are composed while its
``want`` is anything but ``absent``. A composition a module gets wrong is
refused, so the suite fails on it.

Pure apart from reading the manifests and the source sets.
"""

import re
from dataclasses import dataclass

from neutrino_hub.modules.channel.constants import (
    CHANNEL_MODULE_STATE_ABSENT,
    CHANNEL_MODULE_STATE_RUNNING,
)
from neutrino_hub.modules.devices.constants import (
    DEVICE_HUB_CONTAINER_EXIT_CODE_MAX,
    DEVICE_HUB_CONTAINER_PREFIX,
    DEVICE_HUB_CONTAINER_STOP_MAX_S,
    DEVICE_METHOD_CONTAINER,
)
from neutrino_hub.modules.devices.manifests import (
    entry_method,
    entry_params,
    load_module_manifests,
    manifest_methods,
    resolve_platform_entry,
)
from neutrino_hub.modules.devices.source_sets import load_source_sets, placeholders_in

# A hub container's name, and a named volume of its module.
NAME_PATTERN = r"[a-z0-9][a-z0-9_-]{0,63}"


@dataclass(frozen=True)
class HubContainer:
    """One container a container module runs, as the module composes it.

    Attributes:
        name: The container's name, ``neutrino_<module>`` or one that starts
            ``neutrino_<module>_``.
        image: The name of the ``image`` artifact it runs, in the module's
            manifest.
        ports: Published ports, ``host:container`` each.
        volumes: Named volumes, ``neutrino_<module>_<volume>:<path>`` each.
        environment: ``KEY=value`` lines; a value ``{<set>}`` is the fastest
            source of a set the module's entry lists.
        command: What runs instead of the image's own command.
        services: The service type of each published host port.
        after: The module's containers it starts after, by name.
        page_port: The container's port the module's forwarder serves; 0
            for none.
        stop_timeout_s: The seconds ``podman stop`` gives it before
            SIGKILL; 0 for Podman's own 10.
        success_exit_codes: The exit codes beside 143 its unit counts as a
            clean stop.
    """

    name: str
    image: str
    ports: tuple = ()
    volumes: tuple = ()
    environment: tuple = ()
    command: str = ""
    services: tuple = ()
    after: tuple = ()
    page_port: int = 0
    stop_timeout_s: int = 0
    success_exit_codes: tuple = ()


@dataclass(frozen=True)
class HubContainerRequest:
    """What a module's composition is asked with.

    Attributes:
        store: The :class:`~neutrino_hub.modules.devices.desired_state.DesiredStateStore`,
            whose files hold the module's configuration.
        key: The device.
        platform: The tuple the machine reported.
        is_hub_machine: Whether the device is the hub's own machine.
        models: The names the AI gateway serves now.
    """

    store: object
    key: str
    platform: dict
    is_hub_machine: bool = False
    models: tuple = ()


# Each container module's composition, by module name: called with a
# :class:`HubContainerRequest`, it returns the module's containers.
HUB_CONTAINER_COMPOSERS: dict = {}


def container_modules(wants: dict) -> list:
    """The container modules among the modules a machine is asked for.

    Args:
        wants: Module name to ``{want, is_settled}``, as ``modules.json``
            holds them.

    Returns:
        The names whose manifest names the ``container`` method and whose
        ``want`` is not ``absent``, in ``wants``' order.
    """
    manifests = load_module_manifests()
    return [
        name
        for name, entry in wants.items()
        if entry.get("want") != CHANNEL_MODULE_STATE_ABSENT
        and name in manifests
        and DEVICE_METHOD_CONTAINER in manifest_methods(manifests[name])
    ]


def compose_hub_containers(
    store,
    key: str,
    platform: dict,
    *,
    is_hub_machine: bool = False,
    models: "list | tuple" = (),
    releases=None,
    wanted: "dict | None" = None,
) -> list:
    """The ``hub_containers`` the Containers module's state carries for one machine.

    Args:
        store: The desired state store.
        key: The device.
        platform: The tuple the machine reported.
        is_hub_machine: Whether the device is the hub's own machine.
        models: The names the AI gateway serves now.
        releases: The publishers' feeds as last read, as a
            :class:`~neutrino_hub.modules.devices.module_releases.ModuleReleaseStore`;
            None takes every image's tested digest.
        wanted: The modules ``modules.json`` names, as the state's one
            read gave them; None reads the file.

    Returns:
        ``{module, name, image: {digest, sources}, ports, volumes,
        environment, command, is_autostart, services, source_sets, after,
        page_port}``, and ``stop_timeout_s`` and ``success_exit_codes``
        where a container names them, for each container of each container
        module the machine has with an entry for its platform, in
        ``modules.json``'s order and each module's own. Each image's digest is the one the recipe of the
        machine's chosen version names.

    Raises:
        ValueError: For a composition :func:`check_composition` refuses.
    """
    wants = store.modules(key) if wanted is None else wanted
    manifests = load_module_manifests()
    request = HubContainerRequest(
        store=store,
        key=key,
        platform=dict(platform),
        is_hub_machine=is_hub_machine,
        models=tuple(models),
    )
    composed = []
    for module in container_modules(wants):
        _, entry = resolve_platform_entry(manifests[module], platform)
        compose = HUB_CONTAINER_COMPOSERS.get(module)
        if entry_method(entry) != DEVICE_METHOD_CONTAINER or compose is None:
            continue
        params = entry_params(entry)
        containers = tuple(compose(request))
        check_composition(module, containers, params)
        artifacts = {
            artifact["name"]: artifact
            for artifact in _chosen_artifacts(
                module, params, wants[module], platform, releases
            )
        }
        is_running = wants[module]["want"] == CHANNEL_MODULE_STATE_RUNNING
        for container in containers:
            artifact = artifacts[container.image]
            held = {
                "module": module,
                "name": container.name,
                "image": {
                    "digest": artifact["digest"],
                    "sources": list(artifact["sources"]),
                },
                "ports": list(container.ports),
                "volumes": list(container.volumes),
                "environment": list(container.environment),
                "command": container.command,
                "is_autostart": is_running,
                "services": [dict(service) for service in container.services],
                "source_sets": list(params.get("source_sets") or []),
                "after": list(container.after),
                "page_port": container.page_port,
            }
            if container.stop_timeout_s:
                held["stop_timeout_s"] = container.stop_timeout_s
            if container.success_exit_codes:
                held["success_exit_codes"] = list(container.success_exit_codes)
            composed.append(held)
    return composed


def _chosen_artifacts(
    module: str, params: dict, want: dict, platform: dict, releases
) -> list:
    """The image artifacts of the version a machine chose, the tested ones while it chose none."""
    version = str(want.get("version", "") or "")
    if version and releases is not None:
        recipe = releases.recipe(module, platform, version)
        if recipe:
            return list((recipe.get("params") or {}).get("artifacts") or [])
    return list(params["artifacts"])


def check_composition(module: str, containers: tuple, params: dict) -> None:
    """Refuse a module's composition the agent could not run.

    Args:
        module: The container module.
        containers: Its containers, as it composed them.
        params: Its manifest entry's ``params`` for the machine's platform.

    Raises:
        ValueError: For a name that is not ``neutrino_<module>`` or does not
            start ``neutrino_<module>_``, a name given twice, an image no
            ``image`` artifact names, a volume that is not one of the
            module's named volumes, a placeholder naming a set the source
            sets do not define or the module's entry does not list, an
            ``after`` naming no other container of the module, a
            ``page_port`` outside 0 to 65535, a ``stop_timeout_s`` outside 0
            to 3600, or a success exit code outside 0 to 255.
    """
    prefix = DEVICE_HUB_CONTAINER_PREFIX + module
    images = {artifact.get("name") for artifact in params.get("artifacts") or []}
    listed = list(params.get("source_sets") or [])
    defined = load_source_sets()
    names = [container.name for container in containers]
    for container in containers:
        where = f"hub container {container.name!r} of {module}"
        is_named = re.fullmatch(NAME_PATTERN, container.name) is not None and (
            container.name == prefix or container.name.startswith(prefix + "_")
        )
        if not is_named:
            raise ValueError(f"{where}: its name must start {prefix}")
        if names.count(container.name) > 1:
            raise ValueError(f"{where}: is composed twice")
        if container.image not in images:
            raise ValueError(f"{where}: names no image artifact, {container.image!r}")
        for volume in container.volumes:
            source, _, destination = volume.partition(":")
            is_sound = (
                re.fullmatch(NAME_PATTERN, source) is not None
                and source.startswith(prefix + "_")
                and destination.startswith("/")
            )
            if not is_sound:
                raise ValueError(f"{where}: {volume!r} is no named volume of {module}")
        for line in container.environment:
            for name in placeholders_in(line):
                if name not in defined:
                    raise ValueError(f"{where}: {{{name}}} names no source set")
                if name not in listed:
                    raise ValueError(f"{where}: {{{name}}} is a set {module} lists not")
        for other in container.after:
            if other == container.name or other not in names:
                raise ValueError(f"{where}: starts after no container, {other!r}")
        if not 0 <= container.page_port <= 65535:
            raise ValueError(f"{where}: page_port {container.page_port} is no port")
        if not 0 <= container.stop_timeout_s <= DEVICE_HUB_CONTAINER_STOP_MAX_S:
            raise ValueError(
                f"{where}: stop_timeout_s {container.stop_timeout_s} is out of range"
            )
        for code in container.success_exit_codes:
            if not 0 <= code <= DEVICE_HUB_CONTAINER_EXIT_CODE_MAX:
                raise ValueError(f"{where}: exit code {code} is out of range")


def is_hub_container(name: str, details: dict, composed: list) -> bool:
    """Whether one container is run by a container module, by the owner rule.

    Args:
        name: The container's name.
        details: The Containers module's last reported ``details``.
        composed: The machine's ``hub_containers``, as composed now.

    Returns:
        True when the report gives the container a module's label, or the
        composition names it.
    """
    for container in details.get("containers") or []:
        if isinstance(container, dict) and container.get("name") == name:
            if container.get("module"):
                return True
    return any(container.get("name") == name for container in composed)
