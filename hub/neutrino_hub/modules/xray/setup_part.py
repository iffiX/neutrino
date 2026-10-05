"""The proxy's part of ``nhub setup``, given through the edition table.

Setup installs xray-core and the geodata, makes the proxy core's account and
directory, writes the proxy screen's answers into ``config/xray/``, and asks
the proxy screen with the defaults and the link reader below.
"""

import hashlib
import shutil
import tempfile
import zipfile
from pathlib import Path

from neutrino_hub.modules.xray.constants import (
    XRAY_GEODATA_DIR,
    XRAY_SERVICE_USER,
    XRAY_ASSET_ARCHITECTURES,
    XRAY_BINARY,
    XRAY_BINARY_NAME,
    XRAY_DOWNLOAD_URL,
    XRAY_GEODATA,
    XRAY_NODES_FILE,
    XRAY_ROUTING_FILE,
    XRAY_SHA256,
    XRAY_SOCKS_PORT,
    XRAY_SUPPORTED_ARCHITECTURES,
    XRAY_VERSION,
)
from neutrino_hub.modules.xray.node_config import XrayNodeList, parse_share_link
from neutrino_hub.modules.xray.node_secrets import store_node_secret
from neutrino_hub.platforms.detect import is_linux
from neutrino_hub.system.installation import is_packaged
from neutrino_hub.system.machine import machine_architecture, require_architecture
from neutrino_hub.utils.constants import UTILS_LOG_DIR
from neutrino_hub.utils.json_file import read_config, write_config
from neutrino_hub.utils.subprocess_run import run


def ensure_service_user() -> bool:
    """Make the proxy core's directory, and on Linux its account.

    The log directory is the account's, and so is every xray log left in it:
    anything root left behind there would be unopenable to the service.

    Returns:
        True when the account or the directory was made.

    Raises:
        subprocess.CalledProcessError: When ``useradd`` fails.
        OSError: When the directory cannot be made or handed over.
    """
    is_changed = False
    if not XRAY_GEODATA_DIR.exists():
        XRAY_GEODATA_DIR.mkdir(parents=True, exist_ok=True)
        is_changed = True
    if not is_linux():
        return is_changed
    if not run(["id", XRAY_SERVICE_USER], is_checked=False).is_success:
        run(
            [
                "useradd",
                "--system",
                "--no-create-home",
                "--shell",
                "/usr/sbin/nologin",
                XRAY_SERVICE_USER,
            ]
        )
        is_changed = True
    UTILS_LOG_DIR.mkdir(parents=True, exist_ok=True)
    shutil.chown(UTILS_LOG_DIR, user=XRAY_SERVICE_USER)
    for log_path in UTILS_LOG_DIR.glob("xray_*.log"):
        shutil.chown(log_path, user=XRAY_SERVICE_USER)
    return is_changed


def write_answers(proxy) -> None:
    """Put the proxy screen's answers into ``config/xray/``.

    Args:
        proxy: What the wizard collected, a ``WizardProxy``.

    Raises:
        FileNotFoundError: When the examples have not been copied yet.
        ValueError: When a file is not valid JSON, or a node's secret cannot
            be sealed.
    """
    # Read and replace rather than build: the list carries the measurement
    # settings, which are the example's to state and not the wizard's.
    nodes = XrayNodeList.from_dict(read_config(XRAY_NODES_FILE))
    nodes.nodes = list(proxy.nodes)
    for node in nodes.nodes:
        store_node_secret(node)
    write_config(XRAY_NODES_FILE, nodes.to_dict())
    routing = read_config(XRAY_ROUTING_FILE)
    routing["is_proxy_enabled"] = proxy.is_enabled
    routing["is_local_proxy_enabled"] = proxy.is_enabled and proxy.is_local
    if not is_linux():
        routing["is_overlay_proxy_enabled"] = routing["is_local_proxy_enabled"]
    # Two questions, one list: a listener is a port and which way what
    # arrives there leaves, and the wizard asks about one of each kind.
    ports = []
    if proxy.is_socks_proxy_enabled:
        ports.append({"port": proxy.socks_proxy_port, "is_proxied": True})
    if proxy.is_socks_direct_enabled and proxy.socks_direct_port != (
        proxy.socks_proxy_port if proxy.is_socks_proxy_enabled else 0
    ):
        ports.append({"port": proxy.socks_direct_port, "is_proxied": False})
    routing["socks_ports"] = ports
    write_config(XRAY_ROUTING_FILE, routing)


def step_xray_core(reporter) -> str:
    """Setup's step that puts xray-core and the geodata in place.

    Args:
        reporter: Where progress lines go.

    Returns:
        What was installed, or the version already there.

    Raises:
        FileNotFoundError: When a package should carry a file and does not.
        ValueError: When a download is not the pinned file.
        RuntimeError: On a machine the vendor publishes no build for.
    """
    is_changed = False
    if not Path(XRAY_BINARY).is_file():
        if is_packaged():
            raise FileNotFoundError(
                f"the package should carry xray at {XRAY_BINARY} and it is not "
                f"there; reinstall the package rather than fetching one"
            )
        reporter.note(f"downloading xray-core {XRAY_VERSION} (~15 MB)")
        fetch_xray_binary()
        is_changed = True
    for file_name, pin in XRAY_GEODATA.items():
        if (XRAY_GEODATA_DIR / file_name).is_file():
            continue
        if is_packaged():
            raise FileNotFoundError(
                f"the package should carry {file_name} in {XRAY_GEODATA_DIR} "
                f"and it is not there; reinstall the package"
            )
        reporter.note(f"downloading {file_name}")
        fetch_pinned(pin["url"], pin["sha256"], XRAY_GEODATA_DIR / file_name)
        is_changed = True
    if not is_changed:
        version = run([XRAY_BINARY, "version"], is_checked=False).stdout
        return version.splitlines()[0] if version else "present"
    return f"xray {XRAY_VERSION} and the databases"


def fetch_xray_binary() -> None:
    """Put the pinned xray release where the package would have put it.

    A checkout has no package to carry it. The vendor's install script is
    GPL-3.0 and installs under /usr/local, which is neither the hub's to use
    nor a licence it may distribute, so the release archive is taken directly.

    Raises:
        RuntimeError: On a machine the vendor publishes no build for.
        ValueError: When the download is not the pinned file.
    """
    require_architecture(XRAY_SUPPORTED_ARCHITECTURES, "xray")
    architecture = machine_architecture()
    target = Path(XRAY_BINARY)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as workdir:
        archive = Path(workdir) / "xray.zip"
        fetch_pinned(
            XRAY_DOWNLOAD_URL.format(
                version=XRAY_VERSION,
                asset_arch=XRAY_ASSET_ARCHITECTURES[architecture],
            ),
            XRAY_SHA256[architecture],
            archive,
        )
        with zipfile.ZipFile(archive) as bundle:
            # Only the binary: the databases beside it in the release are a
            # different set from the one the hub carries.
            bundle.extract(XRAY_BINARY_NAME, workdir)
        shutil.move(str(Path(workdir) / XRAY_BINARY_NAME), target)
    target.chmod(0o755)


def fetch_pinned(url: str, sha256: str, target: Path) -> None:
    """Download one file and refuse anything but the pinned bytes.

    Args:
        url: What to fetch.
        sha256: The digest the file must have.
        target: Where to write it.

    Raises:
        ValueError: If what arrives is not what was pinned.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as workdir:
        staged = Path(workdir) / target.name
        run(["curl", "-fL", "--retry", "2", "-o", str(staged), url], timeout_s=600)
        digest = hashlib.sha256(staged.read_bytes()).hexdigest()
        if digest != sha256:
            raise ValueError(f"{url} came back as {digest}, not {sha256}")
        shutil.move(str(staged), target)


class XrayWizardPart:
    """What the proxy screen asks with.

    Attributes:
        socks_port: The SOCKS port offered first.
    """

    socks_port = XRAY_SOCKS_PORT

    def parse_share_link(self, link: str):
        """Read one share link into a node.

        Args:
            link: The link as pasted.

        Returns:
            The node, an ``XrayNode``.

        Raises:
            ValueError: When the link is not one this reads.
        """
        return parse_share_link(link)


# The proxy's steps of setup, as ``(id, description, function)``, after the
# Python environment and before config/ is prepared.
SETUP_STEPS = (("xray_core", "Installing xray-core and geodata", step_xray_core),)
WIZARD_PROXY = XrayWizardPart()
