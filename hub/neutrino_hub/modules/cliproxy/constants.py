"""Fixed values of the cliproxy module."""

from pathlib import Path

CLIPROXY_VERSION = "7.2.145"
CLIPROXY_BINARY_PATH = Path("/usr/local/bin/cli-proxy-api")
CLIPROXY_DIR = Path("/var/lib/neutrino_cliproxy")
CLIPROXY_AUTH_DIR = CLIPROXY_DIR / "auth"

CLIPROXY_UNIT = "neutrino_cliproxy.service"
CLIPROXY_DEFAULT_PORT = 8317
CLIPROXY_GENERATED_NAME = "cliproxy.yaml"

CLIPROXY_CLIENT_KEY_BYTES = 24
CLIPROXY_ID_BYTES = 8

CLIPROXY_SUPPORTED_ARCHITECTURES = ("amd64", "arm64")
# The vendor's release assets name arm64 the kernel way.
CLIPROXY_ASSET_ARCHITECTURES = {"amd64": "amd64", "arm64": "aarch64"}

CLIPROXY_DOWNLOAD_URL = (
    "https://github.com/router-for-me/CLIProxyAPI/releases/download/"
    "v{version}/CLIProxyAPI_{version}_linux_{asset_arch}.tar.gz"
)
