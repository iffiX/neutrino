"""Fixed values of the cliproxyapi module."""

from neutrino_hub.utils.constants import UTILS_STATE_ROOT, UTILS_STATIC_ROOT

# What the hub's package carries. The packaging pins the same version in
# hub/packaging/venv_tree.py; this is what the panel reports and what the
# provisioner would fetch on a machine running from a checkout.
CLIPROXYAPI_VERSION = "7.2.146"
# Carried by the hub's package, under the hub's own prefix rather than
# /usr/local, which belongs to whoever administers the machine.
CLIPROXYAPI_BINARY_PATH = UTILS_STATIC_ROOT / "bin" / "cli-proxy-api"
CLIPROXYAPI_DIR = UTILS_STATE_ROOT / "cliproxyapi"
CLIPROXYAPI_AUTH_DIR = CLIPROXYAPI_DIR / "auth"

CLIPROXYAPI_UNIT = "neutrino_hub_cliproxyapi.service"
CLIPROXYAPI_DEFAULT_PORT = 8317
CLIPROXYAPI_GENERATED_NAME = "cliproxyapi.yaml"

CLIPROXYAPI_CLIENT_KEY_BYTES = 24
CLIPROXYAPI_ID_BYTES = 8

# The management API: served by the gateway on its own port, loopback callers
# only, unlocked by a key of the hub's own. The sealed key travels with a
# config backup like the agent channel's; the working copy is state. Both
# paths are resolved per call in management_key.py, against the roots as
# they are right now.
CLIPROXYAPI_MANAGEMENT_SEALED_KEY_RELATIVE = "cliproxyapi/management_key.sealed"
CLIPROXYAPI_MANAGEMENT_KEY_RELATIVE = "cliproxyapi/management.key"
CLIPROXYAPI_MANAGEMENT_KEY_AAD = b"cliproxyapi:management_key"

CLIPROXYAPI_SUPPORTED_ARCHITECTURES = ("amd64", "arm64")
# The vendor's release assets name arm64 the kernel way.
CLIPROXYAPI_ASSET_ARCHITECTURES = {"amd64": "amd64", "arm64": "aarch64"}

CLIPROXYAPI_DOWNLOAD_URL = (
    "https://github.com/router-for-me/CLIProxyAPI/releases/download/"
    "v{version}/CLIProxyAPI_{version}_linux_{asset_arch}.tar.gz"
)
