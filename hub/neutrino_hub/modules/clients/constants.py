from neutrino_hub.modules.services.constants import SERVICES_TYPES

# Where the enrolled clients live under config/. Real file gitignored; the
# example beside it in data/examples documents the shape.
CLIENTS_CONFIG_PATH = "clients/clients.json"
CLIENT_TOKEN_BYTES = 24

# The gateway key label every client's key carries: the prefix, then its name.
CLIENT_AI_KEY_LABEL_PREFIX = "client/"

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
# type, joining the hub's overlay, and opening a shell on a managed machine.
# A client follows the default set unless it has a set of its own; a file
# with no default allows every kind.
CLIENT_PERMISSION_OVERLAY = "overlay"
CLIENT_PERMISSION_TERMINAL = "terminal"
CLIENT_PERMISSION_KINDS = SERVICES_TYPES + (
    CLIENT_PERMISSION_OVERLAY,
    CLIENT_PERMISSION_TERMINAL,
)
# The kinds a permission may narrow to the entries of some devices; the
# overlay is the hub's own and belongs to no device.
CLIENT_PERMISSION_FILTERED_KINDS = SERVICES_TYPES + (CLIENT_PERMISSION_TERMINAL,)
CLIENT_CODE_PERMISSION_DEVICE_UNKNOWN = "permission_device_unknown"
