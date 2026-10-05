"""The port service: Connect makes the entry's forward on the port the one
local port table gives it, every connection a ``connect`` stream through the
hub and none dialled to the entry's own address; Disconnect ends it; a port
that cannot be listened on is ``forward_failed``.
"""

import socket

import pytest

from neutrino_client.services.forward import ForwardListenerRegistry
from neutrino_client.services.port import PortServiceHandler
from tests.conftest import FakeConnectHub, discard, echo_server, round_trip

# An address no test machine has: a dial there would never answer.
DEVICE_HOST = "203.0.113.9"


@pytest.fixture
def hub():
    port, close = echo_server()
    yield FakeConnectHub(far_port=port)
    close()


@pytest.fixture
def forwards(hub):
    registry = ForwardListenerRegistry(open_connect=hub.open_connect, log=discard)
    yield registry
    registry.release()


@pytest.fixture
def service(forwards):
    return PortServiceHandler(forwards=forwards, log=discard)


def entry_for(port, hub_id="h1", entry_id="db"):
    return {
        "hub_id": hub_id,
        "id": entry_id,
        "type": "port",
        "title": "db",
        "payload": {"host": DEVICE_HOST, "port": port},
        "is_healthy": True,
        "source": "module",
        "description": "",
    }


def free_port() -> int:
    probe = socket.create_server(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def test_connect_forwards_through_the_hub_and_never_dials_the_device(
    service, forwards, hub
):
    body = {"hub_id": "h1", "id": "db", "is_enabled": True}

    assert service.act(entries=[entry_for(5432)], body=body) == {}

    port = forwards.port_of("h1", "db")
    assert round_trip(port, b"ping across the hub") == b"ping across the hub"
    assert hub.opens == [("h1", {"id": "db"})]


def test_the_published_number_is_the_local_port_when_free(service, forwards):
    own = free_port()

    assert service.forward(hub_id="h1", entry_id="web", port=own) == {}

    assert forwards.port_of("h1", "web") == own


def test_a_preferred_local_port_is_honored(service, forwards):
    wanted = free_port()

    outcome = service.act(
        entries=[entry_for(5432)],
        body={"hub_id": "h1", "id": "db", "is_enabled": True, "local_port": wanted},
    )

    assert outcome == {}
    assert forwards.port_of("h1", "db") == wanted


def test_disconnect_ends_the_forward(service, forwards):
    entries = [entry_for(5432)]
    body = {"hub_id": "h1", "id": "db", "is_enabled": True}
    service.act(entries=entries, body=body)
    port = forwards.port_of("h1", "db")

    assert service.act(entries=entries, body=dict(body, is_enabled=False)) == {}

    assert forwards.forwards() == {}
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=1)


def test_an_unparsable_published_port_is_refused(service, forwards):
    entries = [dict(entry_for("not a number"), id="bad")]

    refused = service.act(
        entries=entries, body={"hub_id": "h1", "id": "bad", "is_enabled": True}
    )

    assert refused == {"code": "unknown_request", "params": {}}
    assert forwards.forwards() == {}


def test_act_resolves_the_typed_entry(service):
    entries = [entry_for(5432)]

    assert service.act(entries=entries, body={"hub_id": "h1", "id": "gone"}) == {
        "code": "unknown_request",
        "params": {},
    }
    assert service.act(entries=entries, body={"hub_id": "h2", "id": "db"}) == {
        "code": "unknown_request",
        "params": {},
    }


def test_two_hubs_publishing_one_id_are_two_forwards(service, forwards):
    entries = [entry_for(5432), entry_for(5432, hub_id="h2")]

    for hub_id in ("h1", "h2"):
        body = {"hub_id": hub_id, "id": "db", "is_enabled": True}
        assert service.act(entries=entries, body=body) == {}

    ports = forwards.forwards()
    assert sorted(ports) == ["h1/db", "h2/db"]
    assert ports["h1/db"] != ports["h2/db"]


def test_a_fixed_port_another_program_holds_is_taken(service, forwards):
    held = socket.create_server(("127.0.0.1", 0))
    port = held.getsockname()[1]
    forwards.ports.configure("h1/db", port)

    outcome = service.act(
        entries=[entry_for(5432)],
        body={"hub_id": "h1", "id": "db", "is_enabled": True},
    )

    assert outcome == {"code": "port_taken", "params": {"port": port}}
    assert forwards.forwards() == {}
    held.close()
