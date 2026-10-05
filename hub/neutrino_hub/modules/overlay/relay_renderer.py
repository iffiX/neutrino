"""Rendering the relay's start line, and judging how its ssh ended.

Pure: values in, words out, no file and no process.
"""

import shlex

from neutrino_hub.modules.overlay.constants import (
    OVERLAY_RELAY_ASKPASS_ENV,
    OVERLAY_RELAY_ASKPASS_REQUIRE,
    OVERLAY_RELAY_ASKPASS_REQUIRE_ENV,
    OVERLAY_RELAY_DISPLAY,
    OVERLAY_RELAY_DISPLAY_ENV,
    OVERLAY_RELAY_EXIT_LINES,
    OVERLAY_RELAY_KEY_FILE_ERROR,
    OVERLAY_RELAY_KEY_FILE_LINES,
    OVERLAY_RELAY_KEY_FILE_WINDOW,
    OVERLAY_RELAY_KNOWN_HOSTS_OPTION,
    OVERLAY_RELAY_LISTEN_ADDRESS,
    OVERLAY_RELAY_PASSWORD_SSH_OPTIONS,
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
        askpass_path: str = "",
    ):
        """
        Args:
            ssh_path: The system's OpenSSH client.
            key_path: The key file under the state root.
            known_hosts_path: The known-hosts file under the state root.
            agent_port: The port the agent channel listens on.
            askpass_path: The program that prints the login's password, under
                the state root.
        """
        self._ssh_path = ssh_path
        self._key_path = key_path
        self._known_hosts_path = known_hosts_path
        self._agent_port = agent_port
        self._askpass_path = askpass_path

    def render(self, config: OverlayRelayConfig) -> list:
        """The argument vector, the program first.

        Args:
            config: The stored relay.

        Returns:
            The words of the start line network.md gives: with a key, the
            key file; with a login, no key and a password asked through
            askpass.

        Raises:
            ValueError: If the relay names no host, account, key or login.
        """
        if not config.has_settings:
            raise ValueError("the relay names no host, account, key or login")
        options = (
            OVERLAY_RELAY_PASSWORD_SSH_OPTIONS
            if config.is_password_login
            else OVERLAY_RELAY_SSH_OPTIONS
        )
        arguments = [self._ssh_path, "-N", "-T"]
        for option in options:
            arguments += ["-o", option]
        arguments += [
            "-o",
            f"{OVERLAY_RELAY_KNOWN_HOSTS_OPTION}="
            f"{ssh_option_quoted(self._known_hosts_path)}",
        ]
        if not config.is_password_login:
            arguments += ["-i", self._key_path]
        arguments += [
            "-p",
            str(config.ssh_port),
            "-R",
            f"{OVERLAY_RELAY_LISTEN_ADDRESS}:{config.public_port}:"
            f"{OVERLAY_RELAY_TARGET_ADDRESS}:{self._agent_port}",
            f"{config.account}@{config.host}",
        ]
        return arguments

    def environment(self, config: OverlayRelayConfig) -> dict:
        """What the start line's environment adds.

        Args:
            config: The stored relay.

        Returns:
            With a login, ``SSH_ASKPASS`` naming the askpass program,
            ``SSH_ASKPASS_REQUIRE=force`` and a ``DISPLAY``; nothing with a
            key. The password itself is in none of them.
        """
        if not config.is_password_login:
            return {}
        return {
            OVERLAY_RELAY_ASKPASS_ENV: self._askpass_path,
            OVERLAY_RELAY_ASKPASS_REQUIRE_ENV: OVERLAY_RELAY_ASKPASS_REQUIRE,
            OVERLAY_RELAY_DISPLAY_ENV: OVERLAY_RELAY_DISPLAY,
        }


def askpass_program(password_path: str, *, is_windows: bool) -> str:
    """The askpass program's text: it prints the password file and nothing else.

    Args:
        password_path: The password file.
        is_windows: Whether the program is a Windows command script.

    Returns:
        A POSIX shell script, or a command script on Windows.
    """
    if is_windows:
        return f'@type "{password_path}"\r\n'
    return f"#!/bin/sh\nexec cat {shlex.quote(password_path)}\n"


def ssh_option_quoted(value: str) -> str:
    """One value of an ``-o`` option, whole whatever spaces it holds.

    ssh reads an ``-o`` the way it reads a line of ``ssh_config``: words split
    at spaces unless quoted, and a backslash before a backslash or a quote
    stands for that character.

    Args:
        value: The value, a path for example.

    Returns:
        The value in double quotes, its backslashes and quotes escaped.
    """
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


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
