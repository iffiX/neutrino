"""Fixed values of the file share module."""

# The whole of smb.conf is generated: the stock file ships printer shares a
# managed machine has no business serving.
SAMBA_CONF_PATH = "/etc/samba/smb.conf"

# Every panel-created account joins this group; share directories are owned
# by it with setgid, so files members create stay writable to the others.
# Debian ships the group; the RHEL family does not, and the runner creates it.
SAMBA_GROUP = "sambashare"

# Debian names the unit after the binary; the RHEL family ships one
# smb.service.
SAMBA_SERVICES = {"debian": "smbd", "rhel": "smb", "arch": "smb"}
SAMBA_DEFAULT_SERVICE = "smbd"

SAMBA_COMMAND_SET_PASSWORD = "samba_set_password"


def samba_unit(family: str) -> str:
    """The unit this family's Samba runs as.

    Args:
        family: The distribution family.

    Returns:
        The unit name, with its suffix.
    """
    return f"{SAMBA_SERVICES.get(family, SAMBA_DEFAULT_SERVICE)}.service"
