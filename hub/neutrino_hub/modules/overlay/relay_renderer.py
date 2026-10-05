"""Rendering the relay's start line, and judging how its ssh ended.

Pure: values in, words out, no file and no process.
"""

from neutrino_hub.modules.overlay.constants import (
    OVERLAY_RELAY_EXIT_LINES,
    OVERLAY_RELAY_KEY_FILE_ERROR,
    OVERLAY_RELAY_KEY_FILE_LINES,
    OVERLAY_RELAY_KEY_FILE_WINDOW,
    OVERLAY_RELAY_KNOWN_HOSTS_OPTION,
    OVERLAY_RELAY_LISTEN_ADDRESS,
    OVERLAY_RELAY_SSH_OPTIONS,
    OVERLAY_RELAY_STATE_UNREACHABLE,
    OVERLAY_RELAY_TARGET_ADDRESS,
)
from neutrino_hub.modules.overlay.relay_config import OverlayRelayConfig


class OverlayRelayRenderer:
    """Renders the relay's ``ssh`` start line from its settings."""

    def __init__(
        self,
        *,
        ssh_path: str,
        key_path: str,
        known_hosts_path: str,
        agent_port: int,
    ):
        """
        Args:
            ssh_path: The system's OpenSSH client.
            key_path: The key file under the state root.
            known_hosts_path: The known-hosts file under the state root.
            agent_port: The port the agent channel listens on.
        """
        self._ssh_path = ssh_path
        self._key_path = key_path
        self._known_hosts_path = known_hosts_path
        self._agent_port = agent_port

    def render(self, config: OverlayRelayConfig) -> list:
        """The argument vector, the program first.

        Args:
            config: The stored relay.

        Returns:
            The words of the start line network.md gives.

        Raises:
            ValueError: If the relay names no host, account or key.
        """
        if not config.has_settings:
            raise ValueError("the relay names no host, account or key")
        arguments = [self._ssh_path, "-N", "-T"]
        for option in OVERLAY_RELAY_SSH_OPTIONS:
            arguments += ["-o", option]
        arguments += [
            "-o",
            f"{OVERLAY_RELAY_KNOWN_HOSTS_OPTION}={self._known_hosts_path}",
            "-i",
            self._key_path,
            "-p",
            str(config.ssh_port),
            "-R",
            f"{OVERLAY_RELAY_LISTEN_ADDRESS}:{config.public_port}:"
            f"{OVERLAY_RELAY_TARGET_ADDRESS}:{self._agent_port}",
            f"{config.account}@{config.host}",
        ]
        return arguments


def judge_exit(lines: list) -> tuple:
    """The state an ended ssh leaves, from what it wrote last.

    Args:
        lines: What the ended process wrote to its standard error, oldest
            first.

    Returns:
        ``(state, last_line)``: the state of the first entry of
        :data:`OVERLAY_RELAY_EXIT_LINES` the last line holds, else
        ``unreachable``; and that line, empty when it wrote none. When one of
        the last lines says ssh ignored the hub's own key file for its
        permissions, the state is ``unreachable`` and the line says the file
        is the hub's.
    """
    written = [line.strip() for line in lines if line.strip()]
    if not written:
        return OVERLAY_RELAY_STATE_UNREACHABLE, ""
    last = written[-1]
    for line in written[-OVERLAY_RELAY_KEY_FILE_WINDOW:]:
        if any(phrase in line for phrase in OVERLAY_RELAY_KEY_FILE_LINES):
            return (
                OVERLAY_RELAY_STATE_UNREACHABLE,
                OVERLAY_RELAY_KEY_FILE_ERROR.format(line=line),
            )
    for phrase, state in OVERLAY_RELAY_EXIT_LINES:
        if phrase in last:
            return state, last
    return OVERLAY_RELAY_STATE_UNREACHABLE, last
