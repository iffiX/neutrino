"""Fixed values of the services module."""

SERVICES_DECLARED_PATH = "services/declared.json"

SERVICES_KIND_SAMBA = "samba"
SERVICES_KIND_HTTP = "http"
SERVICES_KIND_DOCKER_ENGINE = "docker_engine"
SERVICES_KIND_GENERIC_TCP = "generic_tcp"
SERVICES_DECLARED_KINDS = (
    SERVICES_KIND_SAMBA,
    SERVICES_KIND_HTTP,
    SERVICES_KIND_DOCKER_ENGINE,
    SERVICES_KIND_GENERIC_TCP,
)

SERVICES_HTTP_SCHEMES = ("http", "https")

SERVICES_PORT_MIN = 1
SERVICES_PORT_MAX = 65535
SERVICES_SAMBA_DEFAULT_PORT = 445

# What the API answers with when a declared service is refused or missing.
SERVICES_ERROR_INVALID = "declared_service_invalid"
SERVICES_ERROR_UNKNOWN = "declared_service_unknown"

SERVICES_PROBE_TIMEOUT_S = 2.0
SERVICES_PROBE_CACHE_TTL_S = 10.0
SERVICES_PROBE_WORKER_LIMIT = 8

# Why the last probe called a service unhealthy; None on a healthy one.
SERVICES_PROBE_CONNECT_FAILED = "connect_failed"
SERVICES_PROBE_PING_REJECTED = "ping_rejected"
SERVICES_PROBE_SERVER_ERROR = "server_error"

SERVICES_DOCKER_CACHE_TTL_S = 10.0
SERVICES_DOCKER_TIMEOUT_S = 2.0

# The container list the hub's own podman contributes is keyed by this
# rather than by a declared service id.
SERVICES_DOCKER_PODMAN_SOURCE = "hub_podman"

# What a container start or stop answers with when it fails.
SERVICES_ERROR_DOCKER_UNREACHABLE = "docker_engine_unreachable"
SERVICES_ERROR_DOCKER_REFUSED = "docker_action_refused"

# Offer kinds, the services half of the device catalog.
SERVICES_OFFER_KIND_MOUNT = "mount"
SERVICES_OFFER_KIND_LINK = "link"
SERVICES_OFFER_KIND_PORT = "port"
SERVICES_OFFER_KIND_AI = "ai"

SERVICES_OFFER_AI_ID = "ai"
SERVICES_OFFER_AI_TITLE = "AI tools"
SERVICES_OFFER_AI_DESCRIPTION = (
    "cc-switch, with this hub as a provider for Claude Code, Codex and Gemini"
)
# How each platform obtains cc-switch, the tool the AI service switches
# accounts with. The CLI shares its store with the desktop app; assets are
# published for x86_64 and aarch64 only.
SERVICES_OFFER_AI_PLATFORMS = {
    "linux-amd64": {
        "switcher": {
            "github_repo": "SaladDay/cc-switch-cli",
            "asset_pattern": "linux-x64.tar.gz",
            "package_kind": "tar_binary",
            "binary": "cc-switch",
        }
    },
    "linux-arm64": {
        "switcher": {
            "github_repo": "SaladDay/cc-switch-cli",
            "asset_pattern": "linux-arm64.tar.gz",
            "package_kind": "tar_binary",
            "binary": "cc-switch",
        }
    },
    "darwin": {
        "switcher": {
            "github_repo": "SaladDay/cc-switch-cli",
            "asset_pattern": "darwin-universal.tar.gz",
            "package_kind": "tar_binary",
            "binary": "cc-switch",
        }
    },
    "windows-amd64": {
        "switcher": {
            "github_repo": "SaladDay/cc-switch-cli",
            "asset_pattern": "windows-x64.zip",
            "package_kind": "zip_binary",
            "binary": "cc-switch.exe",
        }
    },
}
