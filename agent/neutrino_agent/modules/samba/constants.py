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
# The server binary, which says Samba is on the machine when no package is named.
SAMBA_BINARY_NAME = "smbd"

# The verbs a ``command {module: samba}`` names, beside ``validate``.
SAMBA_COMMAND_SET_PASSWORD = "set_password"

# On Windows and macOS the module drives the system's own SMB server. What
# it made there is listed in this file under the agent's work root, and
# only what is both listed and marked is ever changed or removed.
SAMBA_NATIVE_RECORD_NAME = "samba_native.json"
# How long one reading of the server's state is believed.
SAMBA_NATIVE_STATUS_TTL_S = 30.0

# Windows: the start of the description of every share the module made,
# which is also the description of every account it made.
SAMBA_WINDOWS_MARKER = "neutrino:"
# The firewall rule that blocks SMB from every address outside the allowed
# subnets, by its name and the title the firewall shows.
SAMBA_WINDOWS_FENCE_RULE = "neutrino_smb_fence"
SAMBA_WINDOWS_FENCE_TITLE = "Neutrino file share fence"
# The rights that keep a share account off the console and off RDP.
SAMBA_WINDOWS_DENIED_RIGHTS = (
    "SeDenyInteractiveLogonRight",
    "SeDenyRemoteInteractiveLogonRight",
)
# A share's rights as the SMB server and as the folder's ACL name them.
SAMBA_WINDOWS_SHARE_CHANGE = "Change"
SAMBA_WINDOWS_SHARE_READ = "Read"
SAMBA_WINDOWS_FOLDER_CHANGE = "(OI)(CI)M"
SAMBA_WINDOWS_FOLDER_READ = "(OI)(CI)RX"
# The account a share with no users is granted to, so the server never
# falls back to granting Everyone.
SAMBA_WINDOWS_SHARE_OWNER = "BUILTIN\\Administrators"

# macOS: smbd's launchd job and the plist it loads from.
SAMBA_DARWIN_SMBD_TARGET = "system/com.apple.smbd"
SAMBA_DARWIN_SMBD_PLIST = "/System/Library/LaunchDaemons/com.apple.smbd.plist"
# The start of the record name of every share point the module made.
SAMBA_DARWIN_SHARE_PREFIX = "neutrino_"
# The full name of every account the module made.
SAMBA_DARWIN_ACCOUNT_NAME = "neutrino file share"
# The group macOS limits SMB to, where the system has one.
SAMBA_DARWIN_ACCESS_GROUP = "com.apple.access_smb"
# The pf anchor the fence lives in; /etc/pf.conf evaluates com.apple/*.
SAMBA_DARWIN_PF_ANCHOR = "com.apple/neutrino_smb"
# The fence's rules, kept under the work root and loaded again at start.
SAMBA_DARWIN_PF_RULES_NAME = "samba_pf.conf"
SAMBA_DARWIN_PF_TABLE = "neutrino_smb_allowed"
# The access-control entries a share grants an account.
SAMBA_DARWIN_ACL_CHANGE = (
    "list,add_file,search,delete,add_subdirectory,delete_child,readattr,"
    "writeattr,readextattr,writeextattr,readsecurity,read,write,append,execute,"
    "file_inherit,directory_inherit"
)
SAMBA_DARWIN_ACL_READ = (
    "list,search,readattr,readextattr,readsecurity,read,execute,"
    "file_inherit,directory_inherit"
)
# An account's login shell: none.
SAMBA_DARWIN_SHELL = "/usr/bin/false"
SAMBA_DARWIN_HOME = "/var/empty"


def samba_unit(family: str) -> str:
    """The unit this family's Samba runs as.

    Args:
        family: The distribution family.

    Returns:
        The unit name, with its suffix.
    """
    return f"{SAMBA_SERVICES.get(family, SAMBA_DEFAULT_SERVICE)}.service"
