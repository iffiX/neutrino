"""Fixed values of the services module."""

SERVICES_DECLARED_PATH = "services/declared.json"

SERVICES_KIND_SAMBA = "samba"
SERVICES_KIND_HTTP = "http"
SERVICES_KIND_GENERIC_TCP = "generic_tcp"
SERVICES_DECLARED_KINDS = (
    SERVICES_KIND_SAMBA,
    SERVICES_KIND_HTTP,
    SERVICES_KIND_GENERIC_TCP,
)

SERVICES_HTTP_SCHEMES = ("http", "https")

SERVICES_PORT_MIN = 1
SERVICES_PORT_MAX = 65535
SERVICES_SAMBA_DEFAULT_PORT = 445

# What the API answers with when a declared service is refused or missing.
SERVICES_ERROR_INVALID = "declared_service_invalid"
SERVICES_ERROR_UNKNOWN = "declared_service_unknown"
# What the API answers with when a host's exports could not be listed; its
# params carry the reason as one of the probe detail codes below.
SERVICES_ERROR_SHARE_SCAN = "share_scan_failed"

SERVICES_PROBE_TIMEOUT_S = 2.0
SERVICES_PROBE_CACHE_TTL_S = 10.0
SERVICES_PROBE_WORKER_LIMIT = 8

# What the last probe measured; None on a service that answered as declared.
SERVICES_PROBE_CONNECT_FAILED = "connect_failed"
SERVICES_PROBE_SERVER_ERROR = "server_error"
SERVICES_PROBE_SHARE_MISSING = "share_missing"
SERVICES_PROBE_TOOL_MISSING = "tool_missing"
SERVICES_PROBE_DETAIL_CODES = (
    SERVICES_PROBE_CONNECT_FAILED,
    SERVICES_PROBE_SERVER_ERROR,
    SERVICES_PROBE_SHARE_MISSING,
    SERVICES_PROBE_TOOL_MISSING,
)

# Listing a server's exports with samba's own client: the column its table of
# shares opens with, the rule under that header, and the suffix marking the
# administrative exports every server carries.
SERVICES_SMBCLIENT_BINARY = "smbclient"
SERVICES_SHARE_TABLE_HEADER = "Sharename"
SERVICES_SHARE_TABLE_RULE = "---"
SERVICES_SHARE_ADMINISTRATIVE_SUFFIX = "$"

# The typed service list: four types, closed until a fifth earns its place.
SERVICES_TYPE_WEB = "web"
SERVICES_TYPE_PORT = "port"
SERVICES_TYPE_AI = "ai"
SERVICES_TYPE_FILE = "file"
SERVICES_TYPES = (
    SERVICES_TYPE_WEB,
    SERVICES_TYPE_PORT,
    SERVICES_TYPE_AI,
    SERVICES_TYPE_FILE,
)

# The stored kind each declarable type maps to; the ai type is never declared
# by hand.
SERVICES_TYPE_TO_KIND = {
    SERVICES_TYPE_WEB: SERVICES_KIND_HTTP,
    SERVICES_TYPE_PORT: SERVICES_KIND_GENERIC_TCP,
    SERVICES_TYPE_FILE: SERVICES_KIND_SAMBA,
}
SERVICES_KIND_TO_TYPE = {kind: type_ for type_, kind in SERVICES_TYPE_TO_KIND.items()}

# Where an entry comes from: a hub module, or a person's declaration.
SERVICES_SOURCE_MODULE = "module"
SERVICES_SOURCE_DECLARED = "declared"

# Hosts that always mean the hub itself, beside the addresses it holds.
SERVICES_HUB_SELF_HOSTS = ("127.0.0.1", "0.0.0.0", "::1", "localhost")

SERVICES_FILE_PROTOCOL = "smb"
SERVICES_AI_PROTOCOL = "openai"

SERVICES_LIST_TTL_S = 10.0
SERVICES_ANSWER_TIMEOUT_S = 2.0

# The provenance line each module-declared entry carries. A description is
# data the declarer words, so these live beside the entries they describe.
SERVICES_GITEA_DESCRIPTION = "published by the gitea module"
SERVICES_SAMBA_DESCRIPTION = "published by the samba module"
SERVICES_AI_DESCRIPTION = "published by the AI gateway"
SERVICES_PODMAN_DESCRIPTION = "published by container {name} ({image})"

SERVICES_GITEA_TITLE = "Gitea"
SERVICES_AI_TITLE = "AI gateway"
SERVICES_AI_ID = "ai"
SERVICES_GITEA_ID = "gitea"
