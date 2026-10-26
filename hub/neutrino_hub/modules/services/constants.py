"""Fixed values of the services module."""

SERVICES_DECLARED_PATH = "services/declared.json"

SERVICES_KIND_SAMBA = "samba"
SERVICES_KIND_HTTP = "http"
SERVICES_KIND_GENERIC_TCP = "generic_tcp"
SERVICES_KIND_GENERIC_UDP = "generic_udp"
SERVICES_DECLARED_KINDS = (
    SERVICES_KIND_SAMBA,
    SERVICES_KIND_HTTP,
    SERVICES_KIND_GENERIC_TCP,
    SERVICES_KIND_GENERIC_UDP,
)

# The two protocols a port entry states, the one a payload with none reads
# as first, the declared kind each is stored as, and what a UDP container
# entry's id ends with.
SERVICES_PROTOCOL_TCP = "tcp"
SERVICES_PROTOCOL_UDP = "udp"
SERVICES_PORT_PROTOCOLS = (SERVICES_PROTOCOL_TCP, SERVICES_PROTOCOL_UDP)
SERVICES_PORT_KIND_BY_PROTOCOL = {
    SERVICES_PROTOCOL_TCP: SERVICES_KIND_GENERIC_TCP,
    SERVICES_PROTOCOL_UDP: SERVICES_KIND_GENERIC_UDP,
}
SERVICES_UDP_ID_SUFFIX = "_udp"

# A container's service type per host port, as its declaration names it; a
# port it does not name is auto, listed by what the agent detected on it.
SERVICES_CONTAINER_AUTO = "auto"
SERVICES_CONTAINER_WEB = "web"

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
# ``share_unverified`` is a healthy answer: the server answers but hides its
# exports from an anonymous asker, so the share itself cannot be checked.
SERVICES_PROBE_CONNECT_FAILED = "connect_failed"
SERVICES_PROBE_SERVER_ERROR = "server_error"
SERVICES_PROBE_SHARE_MISSING = "share_missing"
SERVICES_PROBE_TOOL_MISSING = "tool_missing"
SERVICES_PROBE_LIST_REFUSED = "list_refused"
SERVICES_PROBE_SHARE_UNVERIFIED = "share_unverified"
SERVICES_PROBE_DETAIL_CODES = (
    SERVICES_PROBE_CONNECT_FAILED,
    SERVICES_PROBE_SERVER_ERROR,
    SERVICES_PROBE_SHARE_MISSING,
    SERVICES_PROBE_TOOL_MISSING,
    SERVICES_PROBE_LIST_REFUSED,
    SERVICES_PROBE_SHARE_UNVERIFIED,
)

# Listing a server's exports with samba's own client: the column its table of
# shares opens with, the rule under that header, and the suffix marking the
# administrative exports every server carries.
SERVICES_SMBCLIENT_BINARY = "smbclient"
SERVICES_SHARE_TABLE_HEADER = "Sharename"
SERVICES_SHARE_TABLE_RULE = "---"
SERVICES_SHARE_ADMINISTRATIVE_SUFFIX = "$"
# What a server prints when it turns an anonymous session away rather than
# being unreachable.
SERVICES_SMB_REFUSAL_MARKERS = (
    "NT_STATUS_ACCESS_DENIED",
    "NT_STATUS_LOGON_FAILURE",
)

# The typed service list: six types, closed; a seventh is a row in
# protocol.md's table in the same change.
SERVICES_TYPE_WEB = "web"
SERVICES_TYPE_PORT = "port"
SERVICES_TYPE_SSH = "ssh"
SERVICES_TYPE_AI = "ai"
SERVICES_TYPE_FILE = "file"
SERVICES_TYPE_RDP = "rdp"
SERVICES_TYPES = (
    SERVICES_TYPE_WEB,
    SERVICES_TYPE_PORT,
    SERVICES_TYPE_SSH,
    SERVICES_TYPE_AI,
    SERVICES_TYPE_FILE,
    SERVICES_TYPE_RDP,
)
# The types whose entries belong to an app and carry a local port.
SERVICES_APP_ENTRY_TYPES = (SERVICES_TYPE_WEB, SERVICES_TYPE_PORT, SERVICES_TYPE_SSH)
# The types a declared app's entries take.
SERVICES_DECLARED_ENTRY_TYPES = (
    SERVICES_TYPE_WEB,
    SERVICES_TYPE_PORT,
    SERVICES_TYPE_FILE,
)

# The stored kind each declarable type maps to; the ai type is never declared
# by hand, and neither is the rdp type — only a machine's own agent declares
# that it is sharing its desktop.
SERVICES_TYPE_TO_KIND = {
    SERVICES_TYPE_WEB: SERVICES_KIND_HTTP,
    SERVICES_TYPE_PORT: SERVICES_KIND_GENERIC_TCP,
    SERVICES_TYPE_FILE: SERVICES_KIND_SAMBA,
}
SERVICES_KIND_TO_TYPE = {
    **{kind: type_ for type_, kind in SERVICES_TYPE_TO_KIND.items()},
    SERVICES_KIND_GENERIC_UDP: SERVICES_TYPE_PORT,
}

# Where an entry or an app comes from: a hub module, a person's declaration,
# a container a person started by hand, or a managed machine saying it is
# sharing its desktop.
SERVICES_SOURCE_MODULE = "module"
SERVICES_SOURCE_DECLARED = "declared"
SERVICES_SOURCE_MANUAL = "manual"
SERVICES_SOURCE_DEVICE = "device"
# The order the Services page lists the apps' sources in.
SERVICES_APP_SOURCE_ORDER = (
    SERVICES_SOURCE_MODULE,
    SERVICES_SOURCE_DECLARED,
    SERVICES_SOURCE_MANUAL,
)

# An app's local name and an entry's fixed local port (protocol.md, "The
# local name and the local port"): the slug's length and the suffix two
# equal slugs take, the name's ending, the port range 24000 to 31999, and
# the forwarder's login cookie, named per entry.
SERVICES_SLUG_CHARS_MAX = 63
SERVICES_SLUG_SUFFIX_CHARS = 6
SERVICES_APP_SLUG_FALLBACK = "app"
SERVICES_MACHINE_SLUG_FALLBACK = "machine"
SERVICES_LOCAL_NAME_SUFFIX = ".localhost"
SERVICES_LOCAL_PORT_MIN = 24000
SERVICES_LOCAL_PORT_COUNT = 8000
SERVICES_COOKIE_NAME_PREFIX = "neutrino_"
SERVICES_COOKIE_NAME_CHARS = 12
# The entry names inside an app: a module's one page, Gitea's own SSH
# server, a declared app's entries by type and port, and a UDP port's ending.
SERVICES_ENTRY_WEB = "web"
SERVICES_ENTRY_SSH = "ssh"
SERVICES_ENTRY_DECLARED_WEB = "web_{port}"
SERVICES_ENTRY_DECLARED_PORT = "port_{port}"
SERVICES_ENTRY_DECLARED_FILE = "file_{share}"
# The SSH server app of a machine: its id's start and its title.
SERVICES_SSH_SERVER_ID = "ssh_server"
SERVICES_SSH_SERVER_TITLE = "SSH"

# Hosts that always mean the hub itself, beside the addresses it holds.
SERVICES_HUB_SELF_HOSTS = ("127.0.0.1", "0.0.0.0", "::1", "localhost")

# The scope a caller arrived from, beside the served LANs, each of which is
# its own scope named by its network CIDR.
SERVICES_SCOPE_OVERLAY = "overlay"
SERVICES_SCOPE_LINK = "link"

# The way a client's socket reached the hub, beside each overlay engine's
# own key: a peer on a frp vendor's loopback listener came through that
# vendor's node, a peer on loopback at the agent port through the SSH relay,
# a peer inside a network one of the hub's interfaces holds an address in
# through the LAN, and any other from outside the hub's networks, straight
# to its port.
SERVICES_REACHED_LAN = "lan"
SERVICES_REACHED_SSH_RELAY = "ssh_relay"
SERVICES_REACHED_DIRECT = "direct"

SERVICES_FILE_PROTOCOL = "smb"
SERVICES_AI_PROTOCOL = "openai"
# What an ssh entry's host key fingerprint starts with.
SERVICES_SSH_FINGERPRINT_PREFIX = "SHA256:"
SERVICES_RDP_PROTOCOL = "rustdesk"
# The port a shared desktop answers on. RustDesk dials a bare address at
# this port without a rendezvous server, and the agent writes it into
# direct-access-port; the agent's own constant is the same number.
SERVICES_RDP_PORT = 21118

# The device-hosted modules the list is composed from: a desired state written
# for one of these composes a different list.
SERVICES_PUBLISHED_MODULES = (
    "samba",
    "gitea",
    "podman",
    "vscode",
    "code_server",
    "cloudcli",
    "codeg",
    "hermes_webui",
    "ssh_server",
)

SERVICES_LIST_TTL_S = 10.0

# The provenance line each module-declared entry carries. A description is
# data the declarer words, so these live beside the entries they describe.
# The English sentence still travels for a page too old to know the codes.
SERVICES_GITEA_DESCRIPTION = "published by the gitea module on {host}"
SERVICES_SAMBA_DESCRIPTION = "published by the samba module on {host}"
SERVICES_AI_DESCRIPTION = "published by the AI gateway"
SERVICES_PODMAN_DESCRIPTION = "published by container {name} ({image}) on {host}"
SERVICES_RDP_DESCRIPTION = "shared from {hostname}"
SERVICES_SSH_SERVER_DESCRIPTION = (
    "published by the ssh_server module on {host} for {account}"
)

# Where an entry comes from, as the code a page words in its own language.
# A declared record the person gave a line of their own carries that line and
# no code, because those are already their words.
SERVICES_DESCRIPTION_AI_GATEWAY = "ai_gateway"
SERVICES_DESCRIPTION_CONTAINER = "container"
SERVICES_DESCRIPTION_DECLARED = "declared"
SERVICES_DESCRIPTION_DEVICE_SHARE = "device_share"
SERVICES_DESCRIPTION_GITEA_MODULE = "gitea_module"
SERVICES_DESCRIPTION_SAMBA_MODULE = "samba_module"
SERVICES_DESCRIPTION_VSCODE_MODULE = "vscode_module"
SERVICES_DESCRIPTION_CLOUDCLI_MODULE = "cloudcli_module"
SERVICES_DESCRIPTION_CODE_SERVER_MODULE = "code_server_module"
SERVICES_DESCRIPTION_CODEG_MODULE = "codeg_module"
SERVICES_DESCRIPTION_HERMES_WEBUI_MODULE = "hermes_webui_module"
SERVICES_DESCRIPTION_SSH_SERVER_MODULE = "ssh_server_module"
SERVICES_DESCRIPTION_CODES = (
    SERVICES_DESCRIPTION_AI_GATEWAY,
    SERVICES_DESCRIPTION_CONTAINER,
    SERVICES_DESCRIPTION_DECLARED,
    SERVICES_DESCRIPTION_DEVICE_SHARE,
    SERVICES_DESCRIPTION_GITEA_MODULE,
    SERVICES_DESCRIPTION_SAMBA_MODULE,
    SERVICES_DESCRIPTION_VSCODE_MODULE,
    SERVICES_DESCRIPTION_CLOUDCLI_MODULE,
    SERVICES_DESCRIPTION_CODE_SERVER_MODULE,
    SERVICES_DESCRIPTION_CODEG_MODULE,
    SERVICES_DESCRIPTION_HERMES_WEBUI_MODULE,
    SERVICES_DESCRIPTION_SSH_SERVER_MODULE,
)

SERVICES_GITEA_TITLE = "Gitea"
SERVICES_AI_TITLE = "AI gateway"
SERVICES_AI_ID = "ai"
SERVICES_GITEA_ID = "gitea"
# One web entry per instance of a program run as a person's account, its id
# ``<module>_<device id>_<account>`` and its title the description table's,
# opened by a client through its own forward with the token the ``service``
# stream hands.
SERVICES_INSTANCE_DESCRIPTION = (
    "published by the {module} module on {host} for {account}"
)
# Hermes WebUI's one web entry per device, ``hermes_webui_<device id>``,
# opened the same way while the device reports the module running.
SERVICES_HERMES_WEBUI_ID = "hermes_webui"
SERVICES_HERMES_WEBUI_TITLE = "Hermes WebUI"
SERVICES_HERMES_WEBUI_DESCRIPTION = "published by the hermes_webui module on {host}"
