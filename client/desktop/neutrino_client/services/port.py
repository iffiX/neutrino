"""The port service type: forwarding a published port to this machine.

A published port forwards to ``127.0.0.1`` on a click, on the port the one
local port table gives the entry: for a TCP entry a listener whose every
connection is a ``connect`` stream through the hub, for a UDP entry one UDP
socket whose datagrams ride one stream. The forwards are runtime state and die
with the resident; they are held by service key, so two hubs publishing the
same entry id never collide.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

from neutrino_client.exceptions import GatewayUnreachable
from neutrino_client.services.base import (
    ServiceTypeHandler,
    channel_refusal,
    find_entry,
)
from neutrino_client.services.forward import (
    FORWARD_BIND_HOST,
    FORWARD_PROTOCOL_TCP,
    FORWARD_PROTOCOL_UDP,
    forward_refusal,
)


def entry_protocol(entry: dict) -> str:
    """The protocol a ``port`` entry is forwarded on.

    Args:
        entry: The entry.

    Returns:
        ``udp`` when its payload says so, ``tcp`` otherwise, an entry from
        before UDP entries naming none.
    """
    payload = entry.get("payload") or {}
    if payload.get("protocol") == FORWARD_PROTOCOL_UDP:
        return FORWARD_PROTOCOL_UDP
    return FORWARD_PROTOCOL_TCP


class PortServiceHandler(ServiceTypeHandler):
    """Starts and stops this machine's loopback port forwards."""

    service_type = "port"

    def __init__(self, *, forwards, log=print):
        """
        Args:
            forwards: The
                :class:`~neutrino_client.services.forward.ForwardListenerRegistry`
                the forwards live in.
            log: Callable used for progress messages.
        """
        self._forwards = forwards
        self._log = log

    def act(self, *, entries: list, body: dict):
        """Connect or disconnect one published port's loopback forward.

        Args:
            entries: The merged service list.
            body: ``{"hub_id", "id", "is_enabled", "local_port"}``;
                ``local_port`` is optional and asks for a particular
                loopback number this once, outside the table.

        Returns:
            Empty on success, ``{"code", "params"}`` on a refusal.
        """
        hub_id = str(body.get("hub_id", ""))
        entry_id = str(body.get("id", ""))
        entry = find_entry(entries, self.service_type, hub_id, entry_id)
        if entry is None:
            return {"code": "unknown_request", "params": {}}
        if not body.get("is_enabled"):
            return self.stop(hub_id=hub_id, entry_id=entry_id)
        payload = entry.get("payload") or {}
        try:
            port = int(payload.get("port", 0))
            local_port = int(body.get("local_port") or 0)
        except (TypeError, ValueError):
            return {"code": "unknown_request", "params": {}}
        return self.forward(
            hub_id=hub_id,
            entry_id=entry_id,
            port=port,
            local_port=local_port,
            protocol=entry_protocol(entry),
        )

    def forward(
        self,
        *,
        hub_id: str,
        entry_id: str,
        port: int,
        local_port: int = 0,
        protocol: str = FORWARD_PROTOCOL_TCP,
    ) -> dict:
        """Start forwarding one published port to the loopback.

        Args:
            hub_id: The hub the entry came from.
            entry_id: The entry's id in that hub's list.
            port: The published port number, which an auto pick takes first.
            local_port: The loopback number to listen on; 0 takes the
                entry's from the table.
            protocol: ``tcp`` or ``udp``.

        Returns:
            Empty on success; ``port_taken`` for a fixed port another program
            listens on, ``hub_unreachable`` when a UDP forward's stream
            cannot be asked for, ``forward_failed`` when the port cannot
            otherwise be listened on.
        """
        try:
            bound = self._forwards.ensure(
                hub_id=hub_id,
                entry_id=entry_id,
                own_port=port,
                kind=self.service_type,
                local_port=local_port,
                protocol=protocol,
            )
        except GatewayUnreachable as error:
            return channel_refusal(error)
        except OSError as error:
            return forward_refusal(error)
        self._log(f"port {entry_id} is on {FORWARD_BIND_HOST}:{bound}/{protocol}")
        return {}

    def stop(self, *, hub_id: str, entry_id: str) -> dict:
        """Stop one forward, closing its listener and every connection.

        Args:
            hub_id: The hub the entry came from.
            entry_id: The entry whose forward to stop.

        Returns:
            Empty; stopping what is not running is nothing.
        """
        self._forwards.stop(hub_id, entry_id)
        return {}
