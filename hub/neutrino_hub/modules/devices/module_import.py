"""What a machine's own module amounts to as the hub's configuration.

Each import is a pure function of the ``details`` a module's report
carries. The report path runs one at a machine's first report on a socket,
and a module's ``import`` route runs the same one when a person presses
**Configure** on a module the hub holds no configuration for. A module
with no import here is never taken over.
"""

import math

# The ``testparm -s`` parameters a share's fields are read from.
SAMBA_PARAM_COMMENT = "comment"
SAMBA_PARAM_READ_ONLY = "read only"
SAMBA_PARAM_VALID_USERS = "valid users"
SAMBA_PARAM_YES_VALUES = ("yes", "true", "1")


def samba_import_config(details: dict) -> dict:
    """The configuration a Samba already on the machine amounts to: nothing.

    The module is adopted with an empty configuration; the shares and users
    the person set up stay theirs, uncopied and unmanaged (agent.md,
    "Parallel, never take over").

    Args:
        details: What the agent last reported; not read.

    Returns:
        ``{"shares": [], "users": []}``.
    """
    return {"shares": [], "users": []}


def gitea_import_config(details: dict) -> dict:
    """Nothing: the hub manages only the instance it installs itself.

    Args:
        details: What the agent last reported; a hand-installed Gitea
            says it runs and on which port, and stays its owner's.

    Returns:
        An empty configuration, so the block's defaults stand.
    """
    del details
    return {}


def podman_import_config(details: dict) -> dict:
    """The declarations the machine's own containers amount to.

    Args:
        details: What the agent last reported: ``containers`` from
            ``podman ps`` and ``podman inspect``, each ``{name, image,
            ports, volumes, environment, has_unit}`` and ``services`` where
            the machine reports them, ``mirrors``, and on Windows and macOS
            the Podman machine, ``machine``, with its ``account``.

    Returns:
        ``{"containers", "mirrors"}`` in the hub's shape, and ``machine``,
        the Run settings naming the reported account with its disk's size
        now, rounded up to whole GiB, and Podman's default CPUs and memory,
        where a machine is reported; a container comes up with the machine
        where a unit already stands for it, and keeps its ``services``
        where they are reported. A container with a module's label is a
        hub container and is left out: :func:`labelled_containers` takes
        it over when its module is not named.
    """
    containers = [
        imported_container(container)
        for container in details.get("containers") or []
        if isinstance(container, dict)
        and container.get("name")
        and not container.get("module")
    ]
    config = {
        "containers": containers,
        "mirrors": [str(mirror) for mirror in details.get("mirrors") or []],
    }
    machine = details.get("machine")
    if isinstance(machine, dict) and machine.get("account"):
        config["machine"] = {
            "account": str(machine["account"]),
            "login_id": "",
            "cpus": 0,
            "memory_gib": 0,
            "disk_gib": _whole_gib(machine.get("disk_gib")),
        }
    return config


def imported_container(container: dict) -> dict:
    """One reported container as a declared one in the hub's shape.

    Args:
        container: The container as the Podman report's ``details`` give it.

    Returns:
        ``{name, image, ports, volumes, environment, command, is_autostart}``
        and its ``services`` where they are reported; it comes up with the
        machine where a unit stands for it.
    """
    imported = {
        "name": str(container.get("name", "")),
        "image": str(container.get("image", "")),
        "ports": [str(port) for port in container.get("ports") or []],
        "volumes": [str(mount) for mount in container.get("volumes") or []],
        "environment": [str(line) for line in container.get("environment") or []],
        "command": "",
        "is_autostart": bool(container.get("has_unit", False)),
    }
    if isinstance(container.get("services"), list):
        imported["services"] = _imported_services(container["services"])
    return imported


def labelled_containers(details: dict, named_modules, declared_names) -> list:
    """The hub containers whose module the hub no longer names, as declared containers.

    Args:
        details: The Podman report's ``details``.
        named_modules: The modules ``modules.json`` names with a ``want``
            other than a settled ``absent``.
        declared_names: The declared containers ``podman.json`` holds.

    Returns:
        Each container with the label ``neutrino.module`` of a module not
        named and a name not declared, in the declared shape with its name,
        image, ports, volumes and environment.
    """
    return [
        imported_container(container)
        for container in details.get("containers") or []
        if isinstance(container, dict)
        and container.get("name")
        and container.get("module")
        and container["module"] not in named_modules
        and container["name"] not in declared_names
    ]


def _whole_gib(value) -> int:
    """A reported size in GiB as a whole number, rounded up; 0 for none."""
    try:
        return max(0, math.ceil(float(value or 0)))
    except (TypeError, ValueError, OverflowError):
        return 0


# The modules with an import, by name.
MODULE_IMPORTS = {
    "samba": samba_import_config,
    "gitea": gitea_import_config,
    "podman": podman_import_config,
}


def import_module_config(module: str, details: dict) -> dict:
    """One module's import, by name.

    Args:
        module: The module name.
        details: What the agent last reported for it.

    Returns:
        The configuration the details amount to; empty for a module with
        no import, and for one whose import finds nothing to take over.
    """
    importer = MODULE_IMPORTS.get(module)
    if importer is None:
        return {}
    return dict(importer(details))


def _imported_services(services: list) -> list:
    """A container's reported services in the hub's shape, one per host port."""
    return [
        {
            "port": service.get("port", 0),
            "kind": str(service.get("kind", "") or "auto"),
            "scheme": str(service.get("scheme", "") or "http"),
            "protocols": [str(name) for name in service.get("protocols") or []],
        }
        for service in services
        if isinstance(service, dict)
    ]
