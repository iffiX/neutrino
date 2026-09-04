"""The ports service: forwarding a published port to this machine.

A published port forwards to ``127.0.0.1`` on a click — a standard-library
relay on the same number when it is free and otherwise on a free one the row
names. A forward binds the loopback the whole machine shares, so it is
machine state every scope sees. The contract below is what the services flow
fills in; nothing calls it yet.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations


class PortsService:
    """Starts, stops and lists this machine's loopback port forwards."""

    def forward(self, *, host: str, port: int) -> dict:
        """Start forwarding one published port to the loopback.

        Args:
            host: The address the published port answers on.
            port: The published port number.

        Returns:
            ``{"state", "code", "params"}`` naming the local port taken.
        """
        raise NotImplementedError

    def stop(self, *, port: int) -> dict:
        """Stop the forward bound to one local port.

        Args:
            port: The local port the forward holds.

        Returns:
            ``{"state", "code", "params"}``.
        """
        raise NotImplementedError

    def forwards(self) -> list:
        """The forwards this machine is running.

        Returns:
            One row per forward.
        """
        raise NotImplementedError
