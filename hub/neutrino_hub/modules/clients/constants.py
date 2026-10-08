from neutrino_hub.modules.services.constants import SERVICES_TYPES

# Where the enrolled clients live under config/. Real file gitignored; the
# example beside it in data/examples documents the shape.
CLIENTS_CONFIG_PATH = "clients/clients.json"
CLIENT_TOKEN_BYTES = 24

# The gateway key label every client's key carries: the prefix, then its name.
CLIENT_AI_KEY_LABEL_PREFIX = "client/"
# The gateway key of a device whose CloudCLI module is enabled.
CLIENT_AI_DEVICE_KEY_LABEL_PREFIX = "device/"

# What an rdp entry's id starts with in the published list.
CLIENT_RDP_SERVICE_PREFIX = "rdp_"

# The codes a client is answered with.
CLIENT_CODE_DISABLED = "client_disabled"
CLIENT_CODE_SERVICE_UNKNOWN = "service_unknown"
CLIENT_CODE_RDP_NOT_SHARED = "rdp_not_shared"
CLIENT_CODE_UNKNOWN = "client_unknown"
CLIENT_CODE_NAME_REQUIRED = "client_name_required"
CLIENT_CODE_PERMISSION_DENIED = "permission_denied"
CLIENT_CODE_PERMISSION_KIND_UNKNOWN = "permission_kind_unknown"

# What a client may be allowed, one switch per kind: each published service
# type, joining the hub's overlay, opening a shell on a managed machine,
# running one command on a managed machine, and opening the hub's own panel.
# A client follows the default set unless it has a set of its own.
CLIENT_PERMISSION_OVERLAY = "overlay"
CLIENT_PERMISSION_TERMINAL = "terminal"
CLIENT_PERMISSION_EXEC = "exec"
CLIENT_PERMISSION_PANEL = "panel"
CLIENT_PERMISSION_KINDS = SERVICES_TYPES + (
    CLIENT_PERMISSION_OVERLAY,
    CLIENT_PERMISSION_TERMINAL,
    CLIENT_PERMISSION_EXEC,
    CLIENT_PERMISSION_PANEL,
)
# What a client is allowed when the clients file names no default: every kind
# but the panel, which signs a client in without the panel password and is
# named for one client at a time, and a command, which a script runs as root
# with nobody watching it.
CLIENT_DEFAULT_PERMISSION_KINDS = tuple(
    kind
    for kind in CLIENT_PERMISSION_KINDS
    if kind not in (CLIENT_PERMISSION_PANEL, CLIENT_PERMISSION_EXEC)
)
# The kinds a permission may narrow to the entries of some devices; the
# overlay and the panel are the hub's own and belong to no device.
CLIENT_PERMISSION_FILTERED_KINDS = SERVICES_TYPES + (
    CLIENT_PERMISSION_TERMINAL,
    CLIENT_PERMISSION_EXEC,
)
CLIENT_CODE_PERMISSION_DEVICE_UNKNOWN = "permission_device_unknown"
