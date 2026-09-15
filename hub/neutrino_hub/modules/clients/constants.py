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
