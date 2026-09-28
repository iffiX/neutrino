"""Rendering the engine's start arguments and its network file from what the
panel stored.

Pure: strings in, strings out, no file and no process. The network file's
shape is the engine's own: running it with flags prints the equivalent file,
which is where this came from. The start arguments name that file in manual
mode, and the console address in console mode, where the console pushes the
network and no file is rendered; they reach the engine as a unit drop-in.
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


def render_arguments(
    config: EasyTierConfig, *, config_server: str, config_path: str
) -> list:
    """The engine's start arguments for the stored mode.

    Args:
        config: What the panel stored.
        config_server: The console address, already opened; read only in
            console mode.
        config_path: Where the network file is, read only in manual mode.

    Returns:
        The arguments after the engine's own path. The management portal is
        always named here, since the engine ignores one in a file.

    Raises:
        ValueError: If console mode has no console address.
    """
    portal = ["--rpc-portal", EASYTIER_RPC_PORTAL]
    if not config.is_console_mode:
        return ["-c", config_path, *portal]
    if not config_server:
        raise ValueError("there is no console address to render")
    arguments = ["--config-server", config_server]
    if config.is_secure_mode:
        arguments.append("--secure-mode=true")
    return [*arguments, *portal]


def render_dropin(arguments: list, *, core_path: str) -> str:
    """The unit drop-in that starts the engine with these arguments.

    Args:
        arguments: What :func:`render_arguments` returned.
        core_path: The engine's own path.

    Returns:
        The drop-in's text: an empty ``ExecStart=`` clearing the unit's own,
        then the full start line, every word quoted for systemd.
    """
    words = " ".join(_systemd_quoted(word) for word in [core_path, *arguments])
    return f"[Service]\nExecStart=\nExecStart={words}\n"


def _systemd_quoted(word: str) -> str:
    """One command line word as systemd reads it back unchanged.

    Args:
        word: The word.

    Returns:
        The word in double quotes, with backslashes and quotes escaped and
        the specifier and variable signs doubled.
    """
    escaped = (
        word.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("%", "%%")
        .replace("$", "$$")
    )
    return f'"{escaped}"'


def _escaped(value: str) -> str:
    """One TOML basic string's contents.

    Args:
        value: The text to put between quotes.

    Returns:
        The text with backslashes and quotes escaped.
    """
    return value.replace("\\", "\\\\").replace('"', '\\"')
