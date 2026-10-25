"""Fixed values of the Hermes WebUI module."""

# The module's name on the wire, which names its record's directory and file.
HERMES_WEBUI_NAME = "hermes_webui"

# The forwarder's port: 8787 unless the person sets another, within these.
HERMES_WEBUI_DEFAULT_PORT = 8787
HERMES_WEBUI_PORT_MIN = 1024
HERMES_WEBUI_PORT_MAX = 65535

# The module's two hub containers, as the hub composes them.
HERMES_WEBUI_AGENT_CONTAINER = "neutrino_hermes_webui_agent"
HERMES_WEBUI_WEBUI_CONTAINER = "neutrino_hermes_webui"

# The two volumes a version change makes again; ``home`` and ``workspace``
# are kept.
HERMES_WEBUI_CACHE_VOLUMES = (
    "neutrino_hermes_webui_agent",
    "neutrino_hermes_webui_app",
)

# How the agent writes the gateway keys: as the agent image's user, with its
# home on the ``home`` volume, through the agent image's own command.
HERMES_WEBUI_EXEC_USER = "hermes"
HERMES_WEBUI_EXEC_HOME = "HERMES_HOME=/opt/data"
HERMES_WEBUI_CONFIG_FILE = "/opt/data/config.yaml"
HERMES_WEBUI_CONFIG_COMMAND = ("hermes", "config", "set")
# The variables the hub composes into both containers, and what the agent
# writes into config.yaml from them; ``model.default`` stays the person's.
HERMES_WEBUI_GATEWAY_URL_VARIABLE = "NEUTRINO_GATEWAY_URL"
HERMES_WEBUI_GATEWAY_KEY_VARIABLE = "NEUTRINO_GATEWAY_KEY"
# The variable in the reference form the webui expands, which it reads a
# bare ``custom`` provider's key from when it lists the gateway's models.
HERMES_WEBUI_GATEWAY_KEY_REFERENCE = "${NEUTRINO_GATEWAY_KEY}"
HERMES_WEBUI_BASE_URL_SUFFIX = "/v1"
HERMES_WEBUI_PROVIDER = "custom"
# How long one podman call the hooks make may take; ``hermes config set``
# starts a Python program in the container.
HERMES_WEBUI_PODMAN_TIMEOUT_S = 120

# The webui on its published port: the address, the health page that answers
# with no login once its first start has ended, its login route, and the
# cookie that login sets.
HERMES_WEBUI_UPSTREAM_HOST = "127.0.0.1"
HERMES_WEBUI_HEALTH_PATH = "/health"
HERMES_WEBUI_LOGIN_PATH = "/api/auth/login"
HERMES_WEBUI_COOKIE = "hermes_session"
HERMES_WEBUI_HEALTH_TIMEOUT_S = 3.0

# What the module keeps, root-only, in its record: the forwarder's port and
# secrets, the loopback port the webui is published at, the pair it last
# installed, the base URL the keys were written with, whether its first
# start has ended, and whether it was stopped.
HERMES_WEBUI_RECORD_FIELDS = (
    "account",
    "port",
    "secret",
    "password",
    "upstream_port",
    "version",
    "base_url",
    "is_ready",
    "is_stopped",
)
# The fields whose change starts the forwarder again.
HERMES_WEBUI_FORWARDER_FIELDS = ("port", "secret", "password", "upstream_port")
# What the module waits on while its first start runs.
HERMES_WEBUI_PENDING = "hermes_webui_first_start"
