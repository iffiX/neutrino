"""Making the stored EasyTier network true on this box, and reading it back.

The engine is asked only for its peer table. Its other read, ``node``, prints
the running configuration with the network secret in it, and a secret that
reaches a log or a panel is a network anybody can join.
"""

import json
import re
from dataclasses import dataclass

from neutrino_hub.modules.easytier.config import EasyTierConfig
from neutrino_hub.modules.easytier.constants import (
    EASYTIER_CLI_PATH,
    EASYTIER_CORE_PATH,
    EASYTIER_GENERATED_NAME,
    EASYTIER_RPC_PORTAL,
    EASYTIER_STATUS_TIMEOUT_S,
    EASYTIER_UNIT,
)
from neutrino_hub.modules.easytier.renderer import render_config
from neutrino_hub.utils.constants import UTILS_GENERATED_DIR
from neutrino_hub.utils.json_file import read_config, write_generated
from neutrino_hub.utils.subprocess_run import run

# Where the panel stores the network. A box that has never had one has no
# file, which reads as no network rather than as a failure: the file is
# written the first time somebody applies a network on the Overlay page.
EASYTIER_CONFIG_NAME = "easytier/easytier.json"

# How the engine words a path to a peer: its own row, a direct tunnel, or
# somebody forwarding for it.
EASYTIER_LINK_LOCAL = "local"
EASYTIER_LINK_DIRECT = "direct"
EASYTIER_LINK_RELAYED = "relayed"
EASYTIER_LINK_UNKNOWN = "unknown"

# The peer table prints sizes the way a person reads them.
SIZE_PATTERN = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z]*)\s*$")
SIZE_UNITS = {
    "": 1,
    "b": 1,
    "k": 1000,
    "kb": 1000,
    "kib": 1024,
    "m": 1000**2,
    "mb": 1000**2,
    "mib": 1024**2,
    "g": 1000**3,
    "gb": 1000**3,
    "gib": 1024**3,
    "t": 1000**4,
    "tb": 1000**4,
    "tib": 1024**4,
}


def read_stored() -> EasyTierConfig:
    """The network this box is a member of, as stored.

    Returns:
        The configuration, empty on a box that has never had one.

    Raises:
        ValueError: If the file is there and is not JSON.
    """
    try:
        return EasyTierConfig.from_dict(read_config(EASYTIER_CONFIG_NAME))
    except FileNotFoundError:
        return EasyTierConfig()


@dataclass
class EasyTierPeer:
    """One node on the network, as this box sees it.

    Attributes:
        hostname: What the node calls itself.
        address: Its overlay address, empty for a node that only forwards.
        link: ``local``, ``direct``, ``relayed`` or ``unknown``.
        protocol: The tunnel it is reached over, the engine's own word.
        latency_ms: Round trip, when known.
        loss_ratio: Share of packets lost, 0 to 1, when known.
        rx_bytes: Received from this peer, when known.
        tx_bytes: Sent to it, when known.
        nat_type: What kind of NAT it is behind, the engine's own word.
        version: The engine it runs.
        is_connected: Whether there is a path to it right now.
    """

    hostname: str
    address: str
    link: str
    protocol: str
    latency_ms: "float | None"
    loss_ratio: "float | None"
    rx_bytes: "int | None"
    tx_bytes: "int | None"
    nat_type: str
    version: str
    is_connected: bool


class EasyTierStatusReader:
    """Reads the peer table the running engine keeps."""

    def peers(self) -> list:
        """Every node this box can see, its own row first.

        Returns:
            The peers, empty when the engine is not running or answers with
            something that is not a table.
        """
        if not EASYTIER_CLI_PATH.is_file():
            return []
        result = run(
            [
                str(EASYTIER_CLI_PATH),
                "-p",
                EASYTIER_RPC_PORTAL,
                "-o",
                "json",
                "peer",
            ],
            is_checked=False,
            timeout_s=EASYTIER_STATUS_TIMEOUT_S,
        )
        if not result.is_success:
            return []
        try:
            rows = json.loads(result.stdout)
        except json.JSONDecodeError:
            return []
        if not isinstance(rows, list):
            return []
        peers = [_peer(row) for row in rows if isinstance(row, dict)]
        peers.sort(key=lambda peer: (peer.link != EASYTIER_LINK_LOCAL, peer.hostname))
        return peers


class EasyTierConfigApplier:
    """Renders the configuration file and restarts the engine on it."""

    def apply(self, config: EasyTierConfig, *, hostname: str) -> str:
        """Write what the panel stored and make the engine run on it.

        Args:
            config: What the panel stored.
            hostname: What this box is called when the configuration names
                none.

        Returns:
            A one-line summary of what happened.

        Raises:
            ValueError: If there is no network to render, or the stored secret
                does not open.
            subprocess.CalledProcessError: If the engine refuses to restart.
        """
        rendered = render_config(config, secret=config.secret(), hostname=hostname)
        # The file carries the network's secret, so it is root-only like every
        # other rendered file that holds key material.
        write_generated(
            UTILS_GENERATED_DIR / EASYTIER_GENERATED_NAME, rendered, mode=0o600
        )
        if not self.is_installed:
            return "rendered; the engine is not installed yet"
        run(["systemctl", "restart", EASYTIER_UNIT])
        return f"applied network {config.network_name} and restarted"

    @property
    def is_installed(self) -> bool:
        """Whether the engine is on the box."""
        return EASYTIER_CORE_PATH.is_file()


def _peer(row: dict) -> EasyTierPeer:
    """One peer table row, reshaped for the page.

    Args:
        row: The engine's own object.

    Returns:
        The peer.
    """
    cost = str(row.get("cost", "")).strip().lower()
    link = EASYTIER_LINK_UNKNOWN
    if cost == "local":
        link = EASYTIER_LINK_LOCAL
    elif cost == "p2p":
        link = EASYTIER_LINK_DIRECT
    elif cost:
        link = EASYTIER_LINK_RELAYED
    return EasyTierPeer(
        hostname=str(row.get("hostname", "")),
        address=str(row.get("ipv4", "")),
        link=link,
        protocol=str(row.get("tunnel_proto", "")),
        latency_ms=_number(row.get("lat_ms")),
        loss_ratio=_ratio(row.get("loss_rate")),
        rx_bytes=_bytes(row.get("rx_bytes")),
        tx_bytes=_bytes(row.get("tx_bytes")),
        nat_type=str(row.get("nat_type", "")),
        version=str(row.get("version", "")),
        is_connected=link != EASYTIER_LINK_UNKNOWN,
    )


def _number(value) -> "float | None":
    """A float the engine printed as a string.

    Args:
        value: What the row carried.

    Returns:
        The number, None when there is none to read.
    """
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _ratio(value) -> "float | None":
    """A percentage the engine printed as a string.

    Args:
        value: What the row carried, for example ``0.0%``.

    Returns:
        The share as 0 to 1, None when there is none to read.
    """
    number = _number(str(value).replace("%", "")) if value is not None else None
    return None if number is None else number / 100


def _bytes(value) -> "int | None":
    """A size the engine printed for a person to read.

    Args:
        value: What the row carried, for example ``917 B`` or ``1.2 MiB``.

    Returns:
        The size in bytes, None when there is none to read.
    """
    match = SIZE_PATTERN.match(str(value or ""))
    if match is None:
        return None
    unit = SIZE_UNITS.get(match.group(2).lower())
    if unit is None:
        return None
    return int(float(match.group(1)) * unit)
