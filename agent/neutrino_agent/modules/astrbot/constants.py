"""Fixed values of the AstrBot module."""

# The module's name on the wire, which names its record's directory and file.
ASTRBOT_NAME = "astrbot"

# The port the agent takes the forwarder's port from, the first free one up.
ASTRBOT_BASE_PORT = 6185

# The module's hub container and the volume that holds AstrBot's data.
ASTRBOT_CONTAINER = "neutrino_astrbot"
ASTRBOT_VOLUME = "neutrino_astrbot_data"
# The settings file in the volume, and the folder Python reads the plugins'
# requirements from, by the major and minor version of the image's Python.
ASTRBOT_CONFIG_FILE = "cmd_config.json"
ASTRBOT_USER_SITE = "python_user/lib/python{version}/site-packages"
# The variable the image names its Python's version in.
ASTRBOT_PYTHON_VARIABLE = "PYTHON_VERSION"

# The dashboard's one user, and how AstrBot hashes its password.
ASTRBOT_USERNAME = "astrbot"
ASTRBOT_PBKDF2_ITERATIONS = 600000
ASTRBOT_PBKDF2_SALT_BYTES = 16
ASTRBOT_JWT_SECRET_BYTES = 32

# The gateway's source in AstrBot, the variable its key is read from at
# load, and the suffix its address takes.
ASTRBOT_SOURCE_ID = "neutrino_gateway"
ASTRBOT_GATEWAY_URL_VARIABLE = "NEUTRINO_GATEWAY_URL"
ASTRBOT_GATEWAY_KEY_REFERENCE = "$NEUTRINO_GATEWAY_KEY"
ASTRBOT_BASE_URL_SUFFIX = "/v1"
ASTRBOT_SOURCE_TIMEOUT_S = 120
# The profile AstrBot reads its chat model from, and the key that names the
# provider.
ASTRBOT_PROFILE = "default"
ASTRBOT_PROFILE_PROVIDER_PATH = ("agent_runner", "config", "model", "provider_id")

# AstrBot on its published port: the address, the page that answers 200 with
# no login once its core has started, and its API.
ASTRBOT_UPSTREAM_HOST = "127.0.0.1"
ASTRBOT_HEALTH_PATH = "/"
ASTRBOT_HEALTH_TIMEOUT_S = 3.0
ASTRBOT_LOGIN_PATH = "/api/auth/login"
ASTRBOT_SOURCES_PATH = "/api/v1/provider-sources"
ASTRBOT_SOURCE_PROVIDERS_PATH = "/api/v1/provider-sources/neutrino_gateway/providers"
ASTRBOT_PROVIDERS_PATH = "/api/v1/providers"
# The key of a chat provider that holds the window AstrBot compresses a
# conversation at.
ASTRBOT_WINDOW_KEY = "max_context_tokens"
ASTRBOT_PROFILE_PATH = "/api/v1/config-profiles/default"
# How long a call to AstrBot's API may take, and how long a start waits for
# AstrBot to answer before it changes the gateway's provider.
ASTRBOT_API_TIMEOUT_S = 30.0
ASTRBOT_START_WAIT_S = 90.0
ASTRBOT_START_POLL_S = 2.0

# The forwarder's own page that stores AstrBot's login in the browser, and
# the page it then opens; the token and the user are inserted as JSON
# strings.
ASTRBOT_KEEP_LOGIN_PATH = "/neutrino_login"
ASTRBOT_LOGIN_PAGE = (
    '<!doctype html><meta charset="utf-8"><title>AstrBot</title>'
    "<script>localStorage.setItem('token', %s);"
    "localStorage.setItem('user', %s);location.replace('/');</script>"
)
# The forwarder's login cookie: its key derived from the module's secret,
# and its lifetime, seven days, as AstrBot's own token's.
ASTRBOT_COOKIE_LABEL = b"neutrino astrbot cookie"
ASTRBOT_LOGIN_LIFETIME_S = 7 * 24 * 3600

# The routes the forwarder refuses whatever a request holds: the login, the
# setup and the account, the second factor, and the self-update.
ASTRBOT_REFUSED_PATHS = (
    "/api/auth/login",
    "/api/v1/auth/login",
    "/api/auth/desktop-session",
    "/api/v1/auth/desktop-session",
    "/api/auth/setup",
    "/api/v1/auth/setup",
    "/api/auth/setup-authenticated",
    "/api/auth/account/edit",
    "/api/v1/auth/account",
    "/api/auth/totp/setup",
    "/api/v1/auth/totp/setup",
    "/api/auth/totp/recovery",
    "/api/v1/auth/totp/recovery",
    "/api/update/do",
    "/api/update/dashboard",
    "/api/v1/updates/core",
    "/api/v1/updates/dashboard",
)
# A save of AstrBot's settings, by method and path, whose ``dashboard`` the
# forwarder reads; a profile's path is this prefix and its id.
ASTRBOT_SYSTEM_CONFIG_PATH = "/api/v1/system-config"
ASTRBOT_PROFILES_PREFIX = "/api/v1/config-profiles/"
ASTRBOT_LEGACY_SAVE_PATH = "/api/config/astrbot/update"
# The dashboard as the forwarder reaches it: its port and its host.
ASTRBOT_DASHBOARD_PORT = 6185
ASTRBOT_DASHBOARD_HOST = "0.0.0.0"

# What the module keeps, root-only, in its record: the forwarder's port and
# secrets, the login cookie's name, the app's local name, the loopback port
# AstrBot is published at, the version it last installed, the password
# written into the settings file, the Python version whose requirements
# folder was made, the gateway's address, model and the model's context
# length AstrBot was given, the agent's provider and whether the agent wrote
# or added it, a provider the
# agent added whose default has not taken yet, whether the first start has
# ended, and whether it was stopped.
ASTRBOT_RECORD_FIELDS = (
    "account",
    "port",
    "secret",
    "password",
    "cookie_name",
    "local_name",
    "upstream_port",
    "version",
    "written_password",
    "python",
    "base_url",
    "model",
    "context_length",
    "provider",
    "is_provider_own",
    "added_provider",
    "is_ready",
    "is_stopped",
)
# The fields whose change starts the forwarder again.
ASTRBOT_FORWARDER_FIELDS = (
    "port",
    "secret",
    "password",
    "cookie_name",
    "local_name",
    "upstream_port",
)
# What the module waits on while its first start runs.
ASTRBOT_PENDING = "astrbot_first_start"
# The module's steps: the settings file before the container starts, and its
# first start after.
ASTRBOT_STEP_FIRST_START = "first_start"
