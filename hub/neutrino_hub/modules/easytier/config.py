"""What this box's EasyTier network is, and what it exports to it.

A network here is two strings: a name and a secret. Every machine carrying
both is on the same network, and the secret is also the key the traffic is
encrypted under, so it is sealed under the vault's data key and never sits in
``config/easytier/easytier.json``.

Parsing and validation only. Rendering is
:mod:`neutrino_hub.modules.easytier.renderer`; making it true on the box is
:mod:`neutrino_hub.modules.easytier.ops`.
"""

import ipaddress
import re
import secrets
from dataclasses import dataclass, field
from urllib.parse import urlparse

from neutrino_hub.modules.credentials.vault import seal_bytes, unseal_bytes
from neutrino_hub.modules.easytier.constants import (
    EASYTIER_DEFAULT_ADDRESS,
    EASYTIER_DEFAULT_PREFIX_LEN,
    EASYTIER_DISCOVERY_SCHEMES,
    EASYTIER_NAME_BYTES,
    EASYTIER_NAME_MAX_LEN,
    EASYTIER_NAME_PREFIX,
    EASYTIER_PEER_SCHEMES,
    EASYTIER_SECRET_AAD,
    EASYTIER_SECRET_BYTES,
)

# A name travels in the clear to every node that relays for this network, and
# it is matched against the relay whitelist as a word: letters, digits, dashes
# and underscores, so neither a space nor a wildcard can hide in one.
EASYTIER_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,%d}$" % EASYTIER_NAME_MAX_LEN)


@dataclass
class EasyTierConfig:
    """This box's membership of one EasyTier network.

    Attributes:
        network_name: What identifies the network. Every node carrying this
            name and the same secret is on it.
        secret_sealed: The network secret, sealed under the vault's data key.
            Empty until a network is configured.
        address: This box's address on the overlay in CIDR form. Empty lets
            the engine assign one, which is what a node that only forwards
            wants.
        hostname: What this box is called on the overlay. Empty uses the
            machine's own name.
        peers: What to connect to at startup, in configuration order. A
            decentralized network has no server, so a node still needs one
            address of a machine already on it.
        exported_networks: The CIDRs this box makes reachable to the others.
    """

    network_name: str = ""
    secret_sealed: dict = field(default_factory=dict)
    address: str = ""
    hostname: str = ""
    peers: list = field(default_factory=list)
    exported_networks: list = field(default_factory=list)

    @property
    def is_configured(self) -> bool:
        """Whether this box has a network to join at all."""
        return bool(self.network_name and self.secret_sealed)

    def secret(self) -> str:
        """The network secret in the clear.

        Returns:
            The secret, empty when none is stored.

        Raises:
            VaultLockedError: If there is no data key on this box.
            ValueError: If what is stored does not decrypt.
        """
        if not self.secret_sealed:
            return ""
        return unseal_bytes(self.secret_sealed, EASYTIER_SECRET_AAD).decode()

    def set_secret(self, secret: str) -> None:
        """Store a new network secret.

        Args:
            secret: The secret every node on the network carries.

        Raises:
            ValueError: If it is empty.
            VaultLockedError: If there is no data key on this box.
        """
        if not secret:
            raise ValueError("a network secret cannot be empty")
        self.secret_sealed = seal_bytes(secret.encode(), EASYTIER_SECRET_AAD)

    @classmethod
    def from_dict(cls, data: dict) -> "EasyTierConfig":
        """Parse the stored file.

        Args:
            data: The parsed ``config/easytier/easytier.json``.

        Returns:
            The configuration, with anything unreadable left at its default.
        """
        sealed = data.get("network_secret_sealed")
        return cls(
            network_name=str(data.get("network_name", "")),
            secret_sealed=sealed if isinstance(sealed, dict) else {},
            address=str(data.get("address", "")),
            hostname=str(data.get("hostname", "")),
            peers=[str(entry) for entry in data.get("peers", []) if entry],
            exported_networks=[
                str(entry) for entry in data.get("exported_networks", []) if entry
            ],
        )

    def to_dict(self) -> dict:
        """Serialize the whole configuration.

        Returns:
            What belongs in ``config/easytier/easytier.json``.
        """
        return {
            "network_name": self.network_name,
            "network_secret_sealed": self.secret_sealed,
            "address": self.address,
            "hostname": self.hostname,
            "peers": list(self.peers),
            "exported_networks": list(self.exported_networks),
        }


def generated_name() -> str:
    """A network name nothing else is likely to carry.

    Returns:
        A name of the project's own shape, which is what keeps two unrelated
        networks on one shared node from colliding.
    """
    return EASYTIER_NAME_PREFIX + secrets.token_hex(EASYTIER_NAME_BYTES)


def generated_secret() -> str:
    """A network secret worth the encryption it keys.

    Returns:
        A fresh secret, URL-safe so it survives being pasted into a command.
    """
    return secrets.token_urlsafe(EASYTIER_SECRET_BYTES)


def generated_address(taken: list) -> str:
    """An address for this box that no network of its own overlaps.

    The engine's own automatic addressing starts at the first address of
    ``10.0.0.0/24``, so that network is the first choice: a machine joining
    with nothing but ``--dhcp`` then lands beside this box rather than on a
    network of its own. A box already on that range is given a random one and
    the machines it invites are given an address to use.

    Args:
        taken: CIDRs this machine already has, in any form ``ip_network``
            accepts.

    Returns:
        An address in CIDR form.
    """
    used = []
    for entry in taken:
        try:
            used.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            continue
    candidates = [ipaddress.ip_network(EASYTIER_DEFAULT_ADDRESS, strict=False)]
    for _ in range(16):
        octets = (secrets.randbelow(254) + 1, secrets.randbelow(254) + 1)
        candidates.append(
            ipaddress.ip_network(
                f"10.{octets[0]}.{octets[1]}.0/{EASYTIER_DEFAULT_PREFIX_LEN}"
            )
        )
    for candidate in candidates:
        if any(candidate.overlaps(network) for network in used):
            continue
        return f"{candidate.network_address + 1}/{candidate.prefixlen}"
    return EASYTIER_DEFAULT_ADDRESS


def validate_name(name: str) -> None:
    """Refuse a network name the engine or the relay whitelist cannot carry.

    Args:
        name: What was typed.

    Raises:
        ValueError: When it is empty or carries anything but letters, digits,
            dashes and underscores.
    """
    if not EASYTIER_NAME_PATTERN.match(name or ""):
        raise ValueError(f"{name!r} is not a network name")


def validate_address(address: str) -> None:
    """Refuse an overlay address that is not one.

    Args:
        address: What was typed, in CIDR form. Empty is allowed and means the
            engine assigns one.

    Raises:
        ValueError: When it is not a host address with a prefix length.
    """
    if not address:
        return
    try:
        interface = ipaddress.ip_interface(address)
    except ValueError as error:
        raise ValueError(f"{address!r} is not an address") from error
    if interface.version != 4:
        raise ValueError(f"{address!r} is not an IPv4 address")
    if "/" not in address:
        raise ValueError(f"{address!r} carries no prefix length")


def validate_peer(uri: str) -> None:
    """Refuse an address the engine would not dial.

    Args:
        uri: What was typed.

    Raises:
        ValueError: When the scheme is neither one the engine connects with
            nor one it asks for addresses, or when there is no host.
    """
    parsed = urlparse(uri or "")
    if parsed.scheme in EASYTIER_PEER_SCHEMES:
        if not parsed.hostname or not parsed.port:
            raise ValueError(f"{uri!r} names no host and port")
        return
    if parsed.scheme in EASYTIER_DISCOVERY_SCHEMES:
        if not (parsed.netloc or parsed.path):
            raise ValueError(f"{uri!r} names nothing to ask")
        return
    raise ValueError(f"{uri!r} is not an address this engine dials")


def validate_network(cidr: str) -> None:
    """Refuse an exported network that is not one.

    Args:
        cidr: What was typed.

    Raises:
        ValueError: When it is not a network, or is the whole internet.
    """
    try:
        network = ipaddress.ip_network(cidr, strict=False)
    except ValueError as error:
        raise ValueError(f"{cidr!r} is not a network") from error
    if network.prefixlen == 0:
        raise ValueError(f"{cidr!r} is every address, not a network")
