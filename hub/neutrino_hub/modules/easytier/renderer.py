"""Rendering an EasyTier configuration file from what the panel stored.

Pure: strings in, a string out, no file and no process. The shape is the
engine's own — running it with flags prints the equivalent file, which is
where this came from.
"""

from neutrino_hub.modules.easytier.config import EasyTierConfig
from neutrino_hub.modules.easytier.constants import (
    EASYTIER_DEVICE_NAME,
    EASYTIER_PEER_PORT,
    EASYTIER_RPC_PORTAL,
)


def render_config(config: EasyTierConfig, *, secret: str, hostname: str) -> str:
    """Render ``easytier.toml``.

    Args:
        config: What the panel stored.
        secret: The network secret, already opened.
        hostname: What this box is called when the configuration names none.

    Returns:
        The file's text.

    Raises:
        ValueError: If there is no network to render.
    """
    if not config.network_name or not secret:
        raise ValueError("there is no network to render")
    lines = [
        f'hostname = "{_escaped(config.hostname or hostname)}"',
    ]
    if config.address:
        lines.append(f'ipv4 = "{_escaped(config.address)}"')
    lines.append("listeners = [")
    for scheme in ("tcp", "udp"):
        lines.append(f'    "{scheme}://0.0.0.0:{EASYTIER_PEER_PORT}",')
    lines.append("]")
    lines.append(f'rpc_portal = "{EASYTIER_RPC_PORTAL}"')
    lines.append("")
    lines.append("[network_identity]")
    lines.append(f'network_name = "{_escaped(config.network_name)}"')
    lines.append(f'network_secret = "{_escaped(secret)}"')
    for uri in config.peers:
        lines.append("")
        lines.append("[[peer]]")
        lines.append(f'uri = "{_escaped(uri)}"')
    for cidr in config.exported_networks:
        lines.append("")
        lines.append("[[proxy_network]]")
        lines.append(f'cidr = "{_escaped(cidr)}"')
    lines.append("")
    lines.append("[flags]")
    lines.append(f'dev_name = "{EASYTIER_DEVICE_NAME}"')
    # The engine relays for every network it hears from unless it is told
    # otherwise, which would make this gateway carry strangers' traffic.
    lines.append(f'relay_network_whitelist = "{_escaped(config.network_name)}"')
    return "\n".join(lines) + "\n"


def _escaped(value: str) -> str:
    """One TOML basic string's contents.

    Args:
        value: The text to put between quotes.

    Returns:
        The text with backslashes and quotes escaped.
    """
    return value.replace("\\", "\\\\").replace('"', '\\"')
