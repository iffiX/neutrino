"""Making the stored EasyTier network true on this box, and reading it back.

The engine's ``node info`` prints the running configuration with the network
secret in it. Only the network's name is taken from that text, and nothing
else of it leaves this module: a secret that reaches a log or a panel is a
network anybody can join.
"""

import json
import re
import threading
import tomllib
from dataclasses import dataclass, field

from neutrino_hub.modules.easytier.config import EasyTierConfig
from neutrino_hub.modules.easytier.constants import (
    EASYTIER_DROPIN_DIR_NAME,
    EASYTIER_DROPIN_NAME,
    EASYTIER_STALE_ARGUMENTS_NAME,
    EASYTIER_CLI_PATH,
    EASYTIER_CORE_PATH,
    EASYTIER_GENERATED_NAME,
    EASYTIER_INSTANCE_FIELDS,
    EASYTIER_RPC_PORTAL,
    EASYTIER_STATUS_TIMEOUT_S,
    EASYTIER_UNIT,
)
from neutrino_hub.modules.easytier.provisioner import refresh_unit
from neutrino_hub.modules.easytier.renderer import (
    render_arguments,
    render_config,
    render_dropin,
)
from neutrino_hub.modules.router.link_status import device_addresses
from neutrino_hub.system.constants import SYSTEM_SYSTEMD_DIR
from neutrino_hub.utils.constants import UTILS_GENERATED_DIR, is_dev_root_set
from neutrino_hub.utils.json_file import read_config, write_generated
from neutrino_hub.utils.subprocess_run import run

# Where the panel stores the network. A box that has never had one has no
# file, which reads as no network rather than as a failure: the file is
# written the first time somebody applies a network on the Overlay page.
EASYTIER_CONFIG_NAME = "easytier/easytier.json"

# One apply at a time, each reading the file as it stands when it runs, so
# the engine ends on the configuration stored last whatever order two
# requests finish in.
EASYTIER_APPLY_LOCK = threading.Lock()


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


def apply_stored(*, hostname: str) -> str:
    """Make the engine run on what is stored now.

    Args:
        hostname: What this box is called when the configuration names none.

    Returns:
        A one-line summary of what happened.

    Raises:
        VaultLockedError: If there is no data key to open what is stored.
        ValueError: If the file is not JSON, or the stored secret or console
            address does not open.
        subprocess.CalledProcessError: If the engine refuses to restart.
    """
    with EASYTIER_APPLY_LOCK:
        return EasyTierConfigApplier().apply(read_stored(), hostname=hostname)


def console_device_names() -> list:
    """The interfaces the engine's console networks ride on right now.

    In console mode the engine names its own interface, so it is found by the
    address the engine reports for each network.

    Returns:
        Every interface holding one of those addresses, empty when the engine
        is not running or runs no network yet.
    """
    wanted = EasyTierStatusReader().addresses()
    if not wanted:
        return []
    return devices_holding(device_addresses(), wanted)


def devices_holding(held: dict, wanted: list) -> list:
    """The devices holding any of the wanted addresses.

    Args:
        held: Device name to address with its prefix, as
            :func:`neutrino_hub.modules.router.link_status.device_addresses`
            reads them.
        wanted: Addresses, with or without a prefix.

    Returns:
        The device names, sorted; the prefixes are not compared.
    """
    hosts = {str(address).split("/")[0] for address in wanted if address}
    return sorted(
        name for name, address in held.items() if str(address).split("/")[0] in hosts
    )


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


@dataclass
class EasyTierInstance:
    """One network the running engine is on, as it reports it.

    Attributes:
        instance_name: What the engine calls the instance.
        network_name: The network's name, empty when withheld.
        address: This box's address on it in CIDR form, empty when withheld
            or not yet assigned.
        hostname: What this box is called on it, empty when withheld.
        subnet_routes: The networks this box makes reachable on it.
        peers: The nodes this box sees on it, its own row first.
        withheld: Which of network name, address and hostname came back
            empty.
    """

    instance_name: str
    network_name: str
    address: str
    hostname: str
    subnet_routes: list = field(default_factory=list)
    peers: list = field(default_factory=list)
    withheld: list = field(default_factory=list)


class EasyTierStatusReader:
    """Reads what the running engine reports through its management portal."""

    def peers(self) -> list:
        """Every node this box can see on every network, its own rows first.

        Returns:
            The peers, empty when the engine is not running or answers with
            something that is not a table.
        """
        peers = []
        for _, rows in _by_instance(self._read("peer")):
            peers.extend(_peers(rows))
        peers.sort(key=lambda peer: (peer.link != EASYTIER_LINK_LOCAL, peer.hostname))
        return peers

    def instances(self) -> list:
        """Every network the engine runs, with its peers.

        Returns:
            One :class:`EasyTierInstance` per network, empty when the engine
            is not running or runs none.
        """
        peers_by_instance = dict(_by_instance(self._read("peer")))
        instances = []
        for name, info in _by_instance(self._read("node", "info")):
            if not isinstance(info, dict):
                continue
            instance = EasyTierInstance(
                instance_name=name,
                network_name=_network_name(info.get("config")),
                address=str(info.get("ipv4_addr", "") or ""),
                hostname=str(info.get("hostname", "") or ""),
                subnet_routes=[
                    str(cidr) for cidr in info.get("proxy_cidrs") or [] if cidr
                ],
                peers=_peers(peers_by_instance.get(name)),
            )
            instance.withheld = [
                key for key in EASYTIER_INSTANCE_FIELDS if not getattr(instance, key)
            ]
            instances.append(instance)
        return instances

    def addresses(self) -> list:
        """This box's address on every network the engine runs.

        Returns:
            Each address in CIDR form, empty when the engine is not running,
            runs none, or has not been given one yet.
        """
        found = []
        for _, info in _by_instance(self._read("node", "info")):
            if not isinstance(info, dict):
                continue
            address = str(info.get("ipv4_addr", "") or "")
            if address:
                found.append(address)
        return found

    def _read(self, *command: str):
        """One JSON answer of the engine's command line tool.

        Args:
            command: The tool's command words.

        Returns:
            The parsed answer, None when the engine is absent or silent.
        """
        if not EASYTIER_CLI_PATH.is_file():
            return None
        result = run(
            [
                str(EASYTIER_CLI_PATH),
                "-p",
                EASYTIER_RPC_PORTAL,
                "-o",
                "json",
                *command,
            ],
            is_checked=False,
            timeout_s=EASYTIER_STATUS_TIMEOUT_S,
        )
        if not result.is_success:
            return None
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return None


class EasyTierConfigApplier:
    """Renders the start line's drop-in and the network file, and restarts
    the engine on them."""

    def apply(self, config: EasyTierConfig, *, hostname: str) -> str:
        """Write what the panel stored and make the engine run on it.

        A mode with nothing to run removes the drop-in and the network file
        and stops the engine.

        Args:
            config: What the panel stored.
            hostname: What this box is called when the configuration names
                none.

        Returns:
            A one-line summary of what happened.

        Raises:
            VaultLockedError: If there is no data key to open what is stored.
            ValueError: If the stored secret or console address does not open.
            subprocess.CalledProcessError: If the engine refuses to restart.
        """
        network_path = UTILS_GENERATED_DIR / EASYTIER_GENERATED_NAME
        dropin_path = (
            SYSTEM_SYSTEMD_DIR / EASYTIER_DROPIN_DIR_NAME / EASYTIER_DROPIN_NAME
        )
        (UTILS_GENERATED_DIR / EASYTIER_STALE_ARGUMENTS_NAME).unlink(missing_ok=True)
        is_unit_owned = not is_dev_root_set()
        if not config.is_configured:
            network_path.unlink(missing_ok=True)
            if is_unit_owned and dropin_path.is_file():
                dropin_path.unlink()
                run(["systemctl", "daemon-reload"])
            if not self.is_installed:
                return "nothing to run"
            run(["systemctl", "stop", EASYTIER_UNIT], is_checked=False)
            return "stopped; there is no network to run"
        if config.is_console_mode:
            arguments = render_arguments(
                config,
                config_server=config.config_server(),
                config_path=str(network_path),
            )
            network_path.unlink(missing_ok=True)
        else:
            rendered = render_config(config, secret=config.secret(), hostname=hostname)
            # The network file carries the secret, so it is root-only like
            # every other rendered file that does.
            write_generated(network_path, rendered, mode=0o600)
            arguments = render_arguments(
                config, config_server="", config_path=str(network_path)
            )
        if not self.is_installed:
            return "rendered; the engine is not installed yet"
        if is_unit_owned:
            refresh_unit()
            write_generated(
                dropin_path,
                render_dropin(arguments, core_path=str(EASYTIER_CORE_PATH)),
                mode=0o644,
            )
            run(["systemctl", "daemon-reload"])
        run(["systemctl", "restart", EASYTIER_UNIT])
        return f"applied the {config.mode} network and restarted"

    @property
    def is_installed(self) -> bool:
        """Whether the engine is on the box."""
        return EASYTIER_CORE_PATH.is_file()


def _by_instance(payload) -> list:
    """An answer split by the instance it is about.

    Args:
        payload: The tool's answer: the answer itself for one instance, a
            list of ``{instance_id, instance_name, result}`` for several.

    Returns:
        ``(instance_name, result)`` pairs; one with an empty name for a
        single instance, none for no answer.
    """
    if payload is None:
        return []
    if (
        isinstance(payload, list)
        and payload
        and all(isinstance(item, dict) and "result" in item for item in payload)
    ):
        return [
            (str(item.get("instance_name", "") or ""), item["result"])
            for item in payload
        ]
    return [("", payload)]


def _peers(rows) -> list:
    """One instance's peer table, reshaped, its own row first.

    Args:
        rows: The engine's rows, anything else reading as none.

    Returns:
        The peers.
    """
    if not isinstance(rows, list):
        return []
    peers = [_peer(row) for row in rows if isinstance(row, dict)]
    peers.sort(key=lambda peer: (peer.link != EASYTIER_LINK_LOCAL, peer.hostname))
    return peers


def _network_name(config_text) -> str:
    """The network's name in the running configuration the engine printed.

    Args:
        config_text: The printed TOML, which also carries the secret.

    Returns:
        The name, empty when there is none to read.
    """
    try:
        data = tomllib.loads(str(config_text or ""))
    except tomllib.TOMLDecodeError:
        return ""
    identity = data.get("network_identity")
    if not isinstance(identity, dict):
        return ""
    return str(identity.get("network_name", "") or "")


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
