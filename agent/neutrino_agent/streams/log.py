"""The output of an install or an uninstall, up one stream the agent opens.

The agent opens ``log {module}`` when a package operation begins, sends
each line the operation prints as one binary frame, and closes the stream
with the module's state once the operation ended; a failed operation's
close carries its code as well. The hub shows the lines as they arrive.

A stream the hub closed, or a socket that went away, takes no more lines
and ends the operation nowhere: the log is a window on the work, never a
condition of it.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

from neutrino_agent.exceptions import GatewayUnreachable, StreamClosed


class LogStream:
    """One package operation's lines, up the channel the agent opened."""

    def __init__(self, channel):
        """
        Args:
            channel: The stream's channel, opened as ``log {module}``.
        """
        self._channel = channel
        self._is_dead = False

    def send(self, line: str) -> None:
        """Send one output line, dropping it when the stream is gone.

        Args:
            line: The line, without its newline.
        """
        if self._is_dead:
            return
        try:
            self._channel.send_line(line)
        except (StreamClosed, GatewayUnreachable):
            self._is_dead = True

    def close(self, state: str, code: str = "", params: "dict | None" = None) -> None:
        """End the stream with the module's state after the operation.

        Args:
            state: The module's state as the report now says it.
            code: Why the operation failed; empty when it took.
            params: What the code's wording names.
        """
        closing = dict(params or {})
        closing["state"] = state
        try:
            self._channel.close(code, closing)
        except GatewayUnreachable:
            self._is_dead = True
