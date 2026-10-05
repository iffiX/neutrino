"""Fixed values of the cliproxyapi module."""

from neutrino_hub.utils.constants import UTILS_STATE_ROOT, carried_program

# What the hub's package carries, what the panel reports and what the
# provisioner would fetch on a machine running from a checkout. The
# packaging reads CLIPROXYAPI_ASSETS below.
CLIPROXYAPI_VERSION = "7.2.146"
# Carried by the hub's package, under the hub's own prefix rather than
# /usr/local, which belongs to whoever administers the machine.
CLIPROXYAPI_BINARY_PATH = carried_program("cli-proxy-api")
# The name the process controller knows the gateway by.
CLIPROXYAPI_SUPERVISED_NAME = "cliproxyapi"
CLIPROXYAPI_DIR = UTILS_STATE_ROOT / "cliproxyapi"
# Where the gateway keeps the accounts somebody signed in. State, not
# configuration: a backup carries ``config/`` and none of this, so a restored
# box signs in again.
CLIPROXYAPI_AUTH_RELATIVE = "cliproxyapi/auth"
CLIPROXYAPI_AUTH_DIR = CLIPROXYAPI_DIR / "auth"

CLIPROXYAPI_UNIT = "neutrino_hub_cliproxyapi.service"
CLIPROXYAPI_DEFAULT_PORT = 8317
CLIPROXYAPI_GENERATED_NAME = "cliproxyapi.yaml"

CLIPROXYAPI_CLIENT_KEY_BYTES = 24
CLIPROXYAPI_ID_BYTES = 8
# What the hub's own gateway key is named.
CLIPROXYAPI_HUB_KEY_NAME = "hub"
# Client keys are sealed under the vault's data key where they are stored, so
# config/cliproxyapi/cliproxyapi.json carries no key material.
CLIPROXYAPI_CLIENT_KEY_AAD = b"cliproxyapi:client_key"

# The management API: served by the gateway on its own port, loopback callers
# only, unlocked by a key of the hub's own. The sealed key travels with a
# config backup like the agent channel's; the working copy is state. Both
# paths are resolved per call in management_key.py, against the roots as
# they are right now.
CLIPROXYAPI_MANAGEMENT_SEALED_KEY_RELATIVE = "cliproxyapi/management_key.sealed"
CLIPROXYAPI_MANAGEMENT_KEY_RELATIVE = "cliproxyapi/management.key"
CLIPROXYAPI_MANAGEMENT_KEY_AAD = b"cliproxyapi:management_key"

# Subscription accounts: the management API's own routes, on the gateway's
# port. An account is a token file the gateway writes into the auth directory
# and reloads without a restart, so nothing here goes through an apply.
CLIPROXYAPI_MANAGEMENT_PREFIX = "/v0/management"
CLIPROXYAPI_AUTH_FILES_PATH = f"{CLIPROXYAPI_MANAGEMENT_PREFIX}/auth-files"
CLIPROXYAPI_OAUTH_CALLBACK_PATH = f"{CLIPROXYAPI_MANAGEMENT_PREFIX}/oauth-callback"
CLIPROXYAPI_AUTH_STATUS_PATH = f"{CLIPROXYAPI_MANAGEMENT_PREFIX}/get-auth-status"
CLIPROXYAPI_OAUTH_SESSION_PATH = f"{CLIPROXYAPI_MANAGEMENT_PREFIX}/oauth-session"
CLIPROXYAPI_AUTH_URL_PATH = CLIPROXYAPI_MANAGEMENT_PREFIX + "/{kind}-auth-url"
CLIPROXYAPI_ACCOUNT_TIMEOUT_S = 15
# The flows 7.2.146 starts, each named after the route that starts it. Gemini
# is absent because the binary carries no Gemini OAuth flow: a Google model is
# reached with an API key provider instead.
CLIPROXYAPI_LOGIN_KINDS = ("anthropic", "codex", "antigravity", "kimi", "xai")

# Usage metering: the collector pops the gateway's per-request queue and
# accumulates under the state root. Days are kept forever; hours carry the
# day series and the health bars; minutes carry the rpm/tpm window.
CLIPROXYAPI_USAGE_RELATIVE = "cliproxyapi/usage.json"
# The sha256 of the YAML the last apply handed the gateway, beside the usage
# store. What the panel compares a fresh render against to know whether the
# running gateway is behind the stored configuration.
CLIPROXYAPI_SERVED_FINGERPRINT_RELATIVE = "cliproxyapi/served_fingerprint.txt"
CLIPROXYAPI_USAGE_POLL_INTERVAL_S = 10
CLIPROXYAPI_USAGE_QUEUE_COUNT = 1000
CLIPROXYAPI_USAGE_HOURS_KEPT = 48
CLIPROXYAPI_USAGE_MINUTES_KEPT = 90

# How long a probed model list answers heartbeats before it is re-asked.
CLIPROXYAPI_SERVED_MODELS_TTL_S = 10.0

# A change of keys alone is written into the served file, which the gateway
# watches and reloads without a restart: how long the hub waits for it to
# accept a new key, how often it asks, and, when it never does, how long
# the restart that follows may take to listen again.
CLIPROXYAPI_RELOAD_WAIT_S = 5.0
CLIPROXYAPI_RELOAD_POLL_S = 0.2
CLIPROXYAPI_RESTART_WAIT_S = 10.0
# The answers a gateway gives a key it does not hold.
CLIPROXYAPI_KEY_REFUSED_STATUSES = (401, 403)

CLIPROXYAPI_SUPPORTED_ARCHITECTURES = ("amd64", "arm64")
# The vendor's release assets name arm64 the kernel way.
CLIPROXYAPI_ASSET_ARCHITECTURES = {"amd64": "amd64", "arm64": "aarch64"}

CLIPROXYAPI_DOWNLOAD_URL = (
    "https://github.com/router-for-me/CLIProxyAPI/releases/download/"
    "v{version}/CLIProxyAPI_{version}_linux_{asset_arch}.tar.gz"
)
# The asset each system and machine takes from that release, and its hash,
# for every system a hub package is built for.
CLIPROXYAPI_RELEASE_URL = (
    "https://github.com/router-for-me/CLIProxyAPI/releases/download/"
    "v{version}/{asset}"
)
CLIPROXYAPI_ASSETS = {
    ("linux", "amd64"): (
        "CLIProxyAPI_7.2.146_linux_amd64.tar.gz",
        "43e112686b4a5b7b818531144cd695eeaacdd54c46dced87be6fb3967c22e149",  # scan: allow
    ),
    ("linux", "arm64"): (
        "CLIProxyAPI_7.2.146_linux_aarch64.tar.gz",
        "086ae6513aa522bbd1000f4e83e5b5223df6038bd69f1c6cad56619b84c06947",  # scan: allow
    ),
    ("darwin", "amd64"): (
        "CLIProxyAPI_7.2.146_darwin_amd64.tar.gz",
        "1985f14f3a7caa40c4f7e6959c7c993db0b735317a1e690365d4c08d631849db",  # scan: allow
    ),
    ("darwin", "arm64"): (
        "CLIProxyAPI_7.2.146_darwin_aarch64.tar.gz",
        "faf4c735b289cb88344f87fd6d745cf9a11d28a231d000173d8045910503b543",  # scan: allow
    ),
    ("windows", "amd64"): (
        "CLIProxyAPI_7.2.146_windows_amd64.zip",
        "d6816c59d155bcf3d1f5f47242770d4b13c9bf68ce310ae86873bdb0b52e5a50",  # scan: allow
    ),
}
