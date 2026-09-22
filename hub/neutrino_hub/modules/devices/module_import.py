"""What a machine's own module amounts to as the hub's configuration.

Each import is a pure function of the ``details`` a module's report
carries. The report path runs one at a machine's first report on a socket,
and a module's ``import`` route runs the same one when a person presses
**Configure** on a module the hub holds no configuration for. A module
with no import here, ZFS among them, is never taken over.
"""

# The ``testparm -s`` parameters a share's fields are read from.
SAMBA_PARAM_COMMENT = "comment"
SAMBA_PARAM_READ_ONLY = "read only"
SAMBA_PARAM_VALID_USERS = "valid users"
SAMBA_PARAM_YES_VALUES = ("yes", "true", "1")


def samba_import_config(details: dict) -> dict:
    """The configuration the machine's own Samba amounts to.

    Args:
        details: What the agent last reported: ``shares`` as ``testparm``
            prints them, each ``{name, path, params}``, and ``users`` as
            ``pdbedit`` lists them, each ``{name, is_present,
            has_password}``.

    Returns:
        ``{"shares", "users"}`` in the hub's shape. A share without a path
        exports nothing and is left out; a share's ``valid users`` keeps
        only names the user list carries.
    """
    users = [
        str(user.get("name", ""))
        for user in details.get("users") or []
        if isinstance(user, dict) and user.get("name")
    ]
    shares = []
    for share in details.get("shares") or []:
        if not isinstance(share, dict) or not share.get("path"):
            continue
        params = share.get("params") if isinstance(share.get("params"), dict) else {}
        valid_users = [
            name
            for name in str(params.get(SAMBA_PARAM_VALID_USERS, ""))
            .replace(",", " ")
            .split()
            if name in users
        ]
        shares.append(
            {
                "name": str(share.get("name", "")),
                "path": str(share.get("path", "")),
                "comment": str(params.get(SAMBA_PARAM_COMMENT, "")),
                "is_read_only": str(params.get(SAMBA_PARAM_READ_ONLY, "")).lower()
                in SAMBA_PARAM_YES_VALUES,
                "valid_users": valid_users,
            }
        )
    return {"shares": shares, "users": users}


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
            ports, volumes, environment, has_unit}``, and ``mirrors``.

    Returns:
        ``{"containers", "mirrors"}`` in the hub's shape; a container comes
        up with the machine where a unit already stands for it.
    """
    containers = []
    for container in details.get("containers") or []:
        if not isinstance(container, dict) or not container.get("name"):
            continue
        containers.append(
            {
                "name": str(container.get("name", "")),
                "image": str(container.get("image", "")),
                "ports": [str(port) for port in container.get("ports") or []],
                "volumes": [str(mount) for mount in container.get("volumes") or []],
                "environment": [
                    str(line) for line in container.get("environment") or []
                ],
                "command": "",
                "is_autostart": bool(container.get("has_unit", False)),
            }
        )
    return {
        "containers": containers,
        "mirrors": [str(mirror) for mirror in details.get("mirrors") or []],
    }


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
