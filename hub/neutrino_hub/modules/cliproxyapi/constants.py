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

CLIPROXYAPI_SUPPORTED_ARCHITECTURES = ("amd64", "arm64")
# The vendor's release assets name arm64 the kernel way.
CLIPROXYAPI_ASSET_ARCHITECTURES = {"amd64": "amd64", "arm64": "aarch64"}

CLIPROXYAPI_DOWNLOAD_URL = (
    "https://github.com/router-for-me/CLIProxyAPI/releases/download/"
    "v{version}/CLIProxyAPI_{version}_linux_{asset_arch}.tar.gz"
)
