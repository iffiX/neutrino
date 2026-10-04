"""The ticket spent in one step, and the token resolved through both registries.

A ticket leaves the store before it is judged, so two machines racing one
link cannot both join; a dead or missing ticket and a ticket for the other
role read apart. A token resolves to a device or a client, and to nothing
at all once the row is gone or the token dropped.
"""

import time

import pytest

from neutrino_hub.modules.channel.bindings import (
    ChannelBinding,
    resolve_token,
    spend_ticket,
)
from neutrino_hub.modules.channel.tickets import ChannelTicketRegistry
from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.modules.devices.registry import DeviceRegistry


def store(**tickets) -> ChannelTicketRegistry:
    """A store holding each named ticket, one of each kind."""
    registry = ChannelTicketRegistry()
    for token, fields in tickets.items():
        registry.put(
            token, **{"kind": "agent", "expires_at": time.time() + 600, **fields}
        )
    return registry


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    return tmp_path


# --- the ticket ---


def test_a_ticket_is_taken_out_of_the_store_and_handed_back():
    tickets = store(t1={"name": "laptop"})

    spent = spend_ticket(tickets, "t1", "agent")

    assert spent["name"] == "laptop"
    assert tickets.entries() == []


def test_a_ticket_spent_once_is_dead_the_second_time():
    tickets = store(t1={})
    spend_ticket(tickets, "t1", "agent")

    with pytest.raises(KeyError):
        spend_ticket(tickets, "t1", "agent")


def test_an_unknown_or_expired_ticket_reads_the_same():
    tickets = store(old={"expires_at": time.time() - 1})

    with pytest.raises(KeyError):
        spend_ticket(tickets, "nonsense", "agent")
    with pytest.raises(KeyError):
        spend_ticket(tickets, "old", "agent")
    assert tickets.entries() == []


def test_a_ticket_for_the_other_role_is_refused_and_spent_all_the_same():
    tickets = store(c1={"kind": "client", "client_id": "x"}, d1={})

    with pytest.raises(ValueError):
        spend_ticket(tickets, "c1", "agent")
    with pytest.raises(ValueError):
        spend_ticket(tickets, "d1", "client")
    assert tickets.entries() == []


def test_a_client_ticket_joins_as_a_client():
    tickets = store(c1={"kind": "client", "client_id": "x"})

    assert spend_ticket(tickets, "c1", "client")["client_id"] == "x"


# --- the token ---


def test_a_device_token_resolves_to_its_binding(config_dir):
    device = DeviceRegistry().create("xenode")
    token = DeviceRegistry().issue_token(device.id)

    assert resolve_token(token) == ChannelBinding("agent", device.id, "xenode")


def test_a_client_token_resolves_to_its_binding(config_dir):
    registry = ClientRegistry()
    client_id = registry.create("alice")
    token = registry.issue_token(client_id)

    assert resolve_token(token) == ChannelBinding("client", client_id, "alice")


def test_an_unknown_blank_or_dropped_token_resolves_to_nothing(config_dir):
    registry = ClientRegistry()
    client_id = registry.create("alice")
    token = registry.issue_token(client_id)
    device = DeviceRegistry().create("box")
    device_token = DeviceRegistry().issue_token(device.id)

    assert resolve_token("nonsense") is None  # scan: allow
    assert resolve_token("") is None
    registry.drop_token(client_id)
    assert resolve_token(token) is None
    DeviceRegistry().forget(device.id)
    assert resolve_token(device_token) is None
