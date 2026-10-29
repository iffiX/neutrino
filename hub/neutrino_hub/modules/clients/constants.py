import string

from neutrino_hub.modules.services.constants import (
    SERVICES_TYPE_AI,
    SERVICES_TYPE_SSH,
    SERVICES_TYPES,
)

# Where the enrolled clients live under config/. Real file gitignored; the
# example beside it in data/examples documents the shape.
CLIENTS_CONFIG_PATH = "clients/clients.json"
# The key the file carries once the first 0.6.0 start added ``ssh`` to every
# stored permission that names ``terminal``; a file without it is a 0.5 one.
CLIENT_SSH_GRANTED_KEY = "is_ssh_granted"
CLIENT_TOKEN_BYTES = 24

# The gateway key label every client's key carries: the prefix, then its name.
CLIENT_AI_KEY_LABEL_PREFIX = "client/"
# The gateway key of a device whose AI tools setting is on.
CLIENT_AI_DEVICE_KEY_LABEL_PREFIX = "device/"
# Where a managed machine's AI tools reach the gateway: its agent's AI gateway
# forward, on that machine's own loopback.
CLIENT_AI_DEVICE_FORWARD_URL = "http://127.0.0.1:8317"

# What an rdp entry's id starts with in the published list.
CLIENT_RDP_SERVICE_PREFIX = "rdp_"
# What a managed machine's row id starts with under the ``terminal`` kind.
CLIENT_TERMINAL_ROW_PREFIX = "terminal_"

# The codes a client is answered with.
CLIENT_CODE_DISABLED = "client_disabled"
CLIENT_CODE_SERVICE_UNKNOWN = "service_unknown"
CLIENT_CODE_RDP_NOT_SHARED = "rdp_not_shared"
CLIENT_CODE_UNKNOWN = "client_unknown"
CLIENT_CODE_NAME_REQUIRED = "client_name_required"
CLIENT_CODE_PERMISSION_DENIED = "permission_denied"
CLIENT_CODE_PERMISSION_KIND_UNKNOWN = "permission_kind_unknown"

# What a client may be allowed, one switch per kind: each published service
# type, joining the hub's overlay, opening a shell or running one command on a
# managed machine, and opening the hub's own panel. A client follows the
# default set unless it has a set of its own.
CLIENT_PERMISSION_OVERLAY = "overlay"
CLIENT_PERMISSION_TERMINAL = "terminal"
CLIENT_PERMISSION_PANEL = "panel"
CLIENT_PERMISSION_SSH = SERVICES_TYPE_SSH
CLIENT_PERMISSION_KINDS = SERVICES_TYPES + (
    CLIENT_PERMISSION_OVERLAY,
    CLIENT_PERMISSION_TERMINAL,
    CLIENT_PERMISSION_PANEL,
)
# What a client is allowed when the clients file names no default: every kind
# but the panel, which signs a client in without the panel password and is
# named for one client at a time.
CLIENT_DEFAULT_PERMISSION_KINDS = tuple(
    kind for kind in CLIENT_PERMISSION_KINDS if kind != CLIENT_PERMISSION_PANEL
)
# The kinds a permission may narrow to the entries of some devices; the
# overlay and the panel are the hub's own and belong to no device.
CLIENT_PERMISSION_FILTERED_KINDS = SERVICES_TYPES + (CLIENT_PERMISSION_TERMINAL,)
# The kinds whose things are rows of the fine mode, in the order a form lists
# them. The AI gateway, the overlay and the panel have none.
CLIENT_PERMISSION_ROW_KINDS = tuple(
    kind for kind in CLIENT_PERMISSION_FILTERED_KINDS if kind != SERVICES_TYPE_AI
)
CLIENT_CODE_PERMISSION_DEVICE_UNKNOWN = "permission_device_unknown"

# --- Web shares ---
# Where the Web shares live under config/. Real file gitignored.
WEB_SHARES_CONFIG_PATH = "clients/web_shares.json"
# The sites that serve the share page, each {url, title}.
WEB_SHARE_SITES = ({"url": "https://share.neutrinohub.net", "title": "Neutrino"},)
# The path of the share page under its site.
WEB_SHARE_PAGE_PATH = "/__neutrino/"
# The link's form, the ``v`` of its JSON.
WEB_SHARE_LINK_VERSION = 1
# The lives a share may have, in days; None lasts until it is revoked.
WEB_SHARE_DAYS = (1, 7, 30)
WEB_SHARE_DAY_S = 24 * 60 * 60
# Seconds between two sweeps of the expired shares.
WEB_SHARE_SWEEP_INTERVAL_S = 60
# A share's ticket as secrets.token_urlsafe makes it, its ufrag and pwd as
# hex, each in random bytes.
WEB_SHARE_TICKET_BYTES = 18
WEB_SHARE_UFRAG_BYTES = 12
WEB_SHARE_PWD_BYTES = 16
WEB_SHARE_PWD_AAD = b"web_share:pwd"
# A share's guest account: guest- and 4 characters, an e-mail on a domain no
# mail reaches, its password and its token secret, each in random bytes.
WEB_SHARE_GUEST_PREFIX = "guest-"
WEB_SHARE_GUEST_ALPHABET = string.ascii_lowercase + string.digits
WEB_SHARE_GUEST_CHARS = 4
WEB_SHARE_GUEST_DOMAIN = "share.neutrino"
WEB_SHARE_GUEST_PASSWORD_BYTES = 18
WEB_SHARE_GUEST_SECRET_BYTES = 32
WEB_SHARE_GUEST_PASSWORD_AAD = b"web_share:guest_password"
WEB_SHARE_GUEST_SECRET_AAD = b"web_share:guest_secret"
# The states a share is in.
WEB_SHARE_STATE_ACTIVE = "active"
WEB_SHARE_STATE_PREPARING = "preparing"
WEB_SHARE_STATE_UNAVAILABLE = "unavailable"
WEB_SHARE_STATE_FAILED = "failed"
# The codes a share's routes and a visitor are answered with.
WEB_SHARE_CODE_SHARE_UNKNOWN = "share_unknown"
WEB_SHARE_CODE_ENTRY_INVALID = "web_share_entry_invalid"
WEB_SHARE_CODE_SITE_INVALID = "web_share_site_invalid"
WEB_SHARE_CODE_UNKNOWN = "web_share_unknown"
