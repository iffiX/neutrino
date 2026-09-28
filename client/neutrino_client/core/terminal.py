"""A hub's shell carried to a terminal on this machine.

The resident opens a ``shell`` stream to a managed machine through its hub
and bridges it to two control connections of ``nclient terminal``: one
carries the keys typed to the hub, the other the hub's output back. Two
connections, one direction each, because a Windows pipe handle serves one
blocking operation at a time. The typing side ending closes the stream;
the hub closing it ends the output side, which ends the terminal.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import sys

from neutrino_client.exceptions import GatewayRefusedDetail, GatewayUnreachable

# How much one read from the typing side takes.
TERMINAL_READ_BYTES = 4096
# How long one wait for the hub's output lasts before the stream is looked
# at again.
TERMINAL_WAIT_S = 0.5
# The module ``nclient`` runs as from a checkout.
CLIENT_ENTRY_MODULE = "neutrino_client.cli.entry"


def client_command() -> list:
    """The argument vector that runs ``nclient`` itself.

    Returns:
        The compiled program alone in a package, the interpreter and the
        entry module in a checkout.
    """
    if "__compiled__" in globals():
        return [sys.executable]
    return [sys.executable, "-m", CLIENT_ENTRY_MODULE]


class TerminalBridge:
    """One shell stream, pumped to and from the terminal's two connections."""

    def __init__(self, *, stream):
        """
        Args:
            stream: The open ``shell`` stream.
        """
        self._stream = stream
        self._is_closed_here = False

    @property
    def stream_id(self) -> int:
        """The shell stream's id, which a resize names."""
        return self._stream.stream_id

    @property
    def is_done(self) -> bool:
        """Whether the stream has ended, from either side."""
        return self._stream.is_done

    def pump_in(self, read) -> None:
        """Send what is typed to the hub until the typing side ends.

        The stream is closed from this side when it does.

        Args:
            read: ``read(size)`` returns the next bytes typed, empty at the
                end; an ``OSError`` counts as the end.
        """
        while True:
            try:
                data = read(TERMINAL_READ_BYTES)
            except OSError:
                data = b""
            if not data:
                break
            try:
                self._stream.send(data)
            except (GatewayUnreachable, TimeoutError):
                break
        self._is_closed_here = not self._stream.is_done
        self._stream.close()

    def pump_out(self, write) -> None:
        """Write the hub's output until the stream ends.

        Args:
            write: ``write(data)`` puts bytes on the terminal's output
                connection; an ``OSError`` ends the stream from this side.
        """
        while True:
            data = self._stream.read(TERMINAL_WAIT_S)
            if data is None:
                continue
            if not data:
                return
            try:
                write(data)
            except OSError:
                self._is_closed_here = not self._stream.is_done
                self._stream.close()
                return

    def outcome(self) -> dict:
        """How the shell ended, once it has.

        Returns:
            ``{"exit_code"}`` for a shell the hub closed with a result or
            one closed from here, its code None when the hub named none;
            ``{"code", "params"}`` for a refusal or a socket that ended
            first.
        """
        if self._is_closed_here:
            return {"exit_code": None}
        try:
            params = self._stream.wait_close(0)
        except GatewayRefusedDetail as refused:
            return {"code": refused.code, "params": dict(refused.params)}
        except GatewayUnreachable:
            return {"code": "hub_unreachable", "params": {}}
        return {"exit_code": params.get("exit_code")}
