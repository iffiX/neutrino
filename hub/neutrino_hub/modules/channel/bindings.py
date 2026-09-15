"""The binding: what a spent ticket leaves, and what a token resolves to.

A ticket is spent in one step, removed from the store before it is judged,
so two machines racing one link cannot both join. A token resolves to a
binding of either role, through the one place that consults both
registries; each compares in constant time.
"""

import time
from dataclasses import dataclass

from neutrino_hub.modules.channel.constants import (
    CHANNEL_ROLE_AGENT,
    CHANNEL_ROLE_CLIENT,
)
from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.modules.devices.registry import DeviceRegistry


@dataclass(frozen=True)
class ChannelBinding:
    """One binding a token resolved to.

    Attributes:
        role: ``agent`` or ``client``.
        id: The binding id: the device's or the client's.
        name: What the row is called, empty when unnamed.
    """

    role: str
    id: str
    name: str = ""


def spend_ticket(tickets: dict, token: str, role: str) -> dict:
    """Take a ticket out of the store and judge it.

    Args:
        tickets: The open tickets, by token.
        token: The ticket the join names.
        role: The role the join claims.

    Returns:
        The ticket, no longer in the store.

    Raises:
        KeyError: When no live ticket has the token, or it has expired.
        ValueError: When the ticket was made for the other role; the ticket
            is spent all the same.
    """
    ticket = tickets.pop(token, None)
    if ticket is None or float(ticket.get("expires_at", 0)) < time.time():
        raise KeyError("no live ticket")
    ticket_role = str(ticket.get("kind") or CHANNEL_ROLE_AGENT)
    if ticket_role != role:
        raise ValueError(f"a {ticket_role} ticket cannot join as {role}")
    return ticket


def resolve_token(token: str) -> "ChannelBinding | None":
    """The binding a presented token belongs to.

    Args:
        token: The token a hello or a leave carries.

    Returns:
        The binding, or None when no row of either role holds the token.
    """
    if not token:
        return None
    device = DeviceRegistry().find_by_token(token)
    if device is not None:
        return ChannelBinding(CHANNEL_ROLE_AGENT, device.id, device.name or "")
    client = ClientRegistry().find_by_token(token)
    if client is not None:
        return ChannelBinding(CHANNEL_ROLE_CLIENT, client.id, client.name)
    return None
