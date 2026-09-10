# Where the enrolled clients live under config/. Real file gitignored; the
# example beside it in data/examples documents the shape.
CLIENTS_CONFIG_PATH = "clients/clients.json"
CLIENT_TOKEN_BYTES = 24

# The client channel's one socket, on the agent TLS port beside the agent's.
CLIENT_WS_PATH = "/api/client/ws"
# What an enrollment link carries so the program that opens it knows which
# kind of enrollment it is.
CLIENT_ENROLLMENT_KIND = "client"

# The gateway key label every client's key carries: the prefix, then its name.
CLIENT_AI_KEY_LABEL_PREFIX = "client/"

# The asks a client may put to the hub over its socket.
CLIENT_ASK_RDP_CONNECT = "rdp_connect"
# What an rdp entry's id starts with in the published list.
CLIENT_RDP_SERVICE_PREFIX = "rdp_"

# The codes a client is answered with.
CLIENT_CODE_DISABLED = "client_disabled"
CLIENT_CODE_ASK_UNKNOWN = "ask_unknown"
CLIENT_CODE_SERVICE_UNKNOWN = "service_unknown"
CLIENT_CODE_RDP_NOT_SHARED = "rdp_not_shared"
CLIENT_CODE_NEWER_THAN_HUB = "client_newer_than_hub"
CLIENT_CODE_ENROLLMENT_UNKNOWN = "enrollment_unknown"
CLIENT_CODE_UNKNOWN = "client_unknown"
CLIENT_CODE_NAME_REQUIRED = "client_name_required"
