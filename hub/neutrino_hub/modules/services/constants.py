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
