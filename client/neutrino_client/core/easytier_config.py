"""One EasyTier network's configuration file, as the client's daemon reads it.

Pure: strings in, a string out, no file and no process. The shape is the
hub's own file less what only a hub does: this side listens on nothing,
exports no network and names no device. ``instance_name`` is the network's
name, which is what ``easytier-cli -n`` selects. The RPC portal is the
daemon's command-line flag, one per process, so no line here names it.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import re
import urllib.parse

# What a network name, and so a file name, may be.
NETWORK_NAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
# What a hostname this side names itself by may be.
HOSTNAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
# The schemes a peer the client connects to may use.
PEER_SCHEMES = ("tcp", "udp", "ws", "wss", "quic")


def is_network_name(name: str) -> bool:
    """Whether a network name is one a file may be named after.

    Args:
        name: The network's name.

    Returns:
        True for 1 to 64 letters, digits, dots, dashes and underscores, and
        never ``.`` or ``..``.
    """
    return bool(NETWORK_NAME_PATTERN.match(name or "")) and name not in (".", "..")


def is_hostname(name: str) -> bool:
    """Whether a hostname may be written into a network's file.

    Args:
        name: The hostname.

    Returns:
        True for 1 to 64 letters, digits, dots, dashes and underscores.
    """
    return bool(HOSTNAME_PATTERN.match(name or ""))


def is_peer_uri(uri: str) -> bool:
    """Whether a peer is one the client connects to.

    Args:
        uri: The peer, as ``tcp://203.0.113.7:11010``.

    Returns:
        True for a known scheme, a host, and a port in 1..65535, with no
        path, query, login or whitespace.
    """
    text = uri or ""
    if any(character.isspace() or character in "\"'\\" for character in text):
        return False
    try:
        parts = urllib.parse.urlsplit(text)
        port = parts.port
    except ValueError:
        return False
    return (
        parts.scheme in PEER_SCHEMES
        and bool(parts.hostname)
        and port is not None
        and 0 < port < 65536
        and parts.path in ("", "/")
        and not parts.query
        and not parts.fragment
        and parts.username is None
    )


def safe_hostname(name: str) -> str:
    """A hostname cut down to what a network's file may carry.

    Args:
        name: The machine's hostname.

    Returns:
        The characters :func:`is_hostname` allows, at most 64 of them;
        ``neutrino-client`` when none is left.
    """
    kept = re.sub(r"[^A-Za-z0-9._-]", "-", name or "")[:64].strip("-")
    return kept or "neutrino-client"


def render_easytier_config(
    *, network_name: str, network_secret: str, peer: str, hostname: str
) -> str:
    """Render one network's ``<network_name>.toml``.

    Args:
        network_name: The hub's network, also the instance's name.
        network_secret: The network's secret.
        peer: The hub's peer URI.
        hostname: What this machine is called on the network.

    Returns:
        The file's text.

    Raises:
        ValueError: When the name, the peer or the hostname is not one
            :func:`is_network_name`, :func:`is_peer_uri` and
            :func:`is_hostname` accept, or the secret is empty.
    """
    if not is_network_name(network_name):
        raise ValueError("the network name is not one a file may carry")
    if not is_peer_uri(peer):
        raise ValueError("the peer is not one the client connects to")
    if not is_hostname(hostname):
        raise ValueError("the hostname is not one a file may carry")
    if not network_secret:
        raise ValueError("the network has no secret")
    lines = [
        f'instance_name = "{network_name}"',
        f'hostname = "{hostname}"',
        "dhcp = true",
        "listeners = []",
        "",
        "[network_identity]",
        f'network_name = "{network_name}"',
        f'network_secret = "{_escaped(network_secret)}"',
        "",
        "[[peer]]",
        f'uri = "{peer.rstrip("/")}"',
        "",
        "[flags]",
        f'relay_network_whitelist = "{network_name}"',
    ]
    return "\n".join(lines) + "\n"


def _escaped(value: str) -> str:
    """One TOML basic string's contents, backslashes, quotes and line ends escaped."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return escaped.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
