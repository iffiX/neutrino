"""The port service, end to end over real loopback sockets."""

import socket
import threading

import pytest

from neutrino_client.services.port import PortServiceHandler
from tests.conftest import discard


def echo(connection) -> None:
    while True:
        try:
            data = connection.recv(4096)
        except OSError:
            break
        if not data:
            break
        connection.sendall(data)
    connection.close()


@pytest.fixture
def upstream():
    """A real echo server on a loopback port of its own."""
    server = socket.create_server(("127.0.0.1", 0))
    port = server.getsockname()[1]

    def serve():
        while True:
            try:
                connection, _address = server.accept()
            except OSError:
                return
            threading.Thread(target=echo, args=(connection,), daemon=True).start()

    threading.Thread(target=serve, daemon=True).start()
    yield port
    server.close()


def entry_for(port):
    return {
        "id": "db",
        "type": "port",
        "title": "db",
        "payload": {"host": "127.0.0.1", "port": port},
        "is_healthy": True,
        "source": "module",
        "description": "",
    }


def test_a_forward_relays_bytes_both_ways(upstream):
    service = PortServiceHandler(log=discard)
    assert service.forward(entry_id="db", host="127.0.0.1", port=upstream) == {}
    row = service.state()["forwards"]["db"]
    assert row["is_active"] is True
    assert row["local_port"] not in (0, upstream)

    client = socket.create_connection(("127.0.0.1", row["local_port"]), timeout=5)
    client.sendall(b"ping across the relay")
    received = b""
    while len(received) < len(b"ping across the relay"):
        chunk = client.recv(4096)
        if not chunk:
            break
        received += chunk
    client.close()
    service.stop(entry_id="db")

    assert received == b"ping across the relay"


def test_the_published_number_is_used_when_free():
    probe = socket.create_server(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    service = PortServiceHandler(log=discard)

    assert service.forward(entry_id="web", host="127.0.0.1", port=port) == {}

    assert service.state()["forwards"]["web"]["local_port"] == port
    service.stop(entry_id="web")


def test_a_preferred_local_port_is_honored(upstream):
    probe = socket.create_server(("127.0.0.1", 0))
    wanted = probe.getsockname()[1]
    probe.close()
    service = PortServiceHandler(log=discard)

    outcome = service.act(
        entries=[entry_for(upstream)],
        body={"id": "db", "is_enabled": True, "local_port": wanted},
    )

    assert outcome == {}
    assert service.state()["forwards"]["db"]["local_port"] == wanted
    service.stop(entry_id="db")


def test_disabling_closes_the_listener_and_open_connections(upstream):
    service = PortServiceHandler(log=discard)
    service.forward(entry_id="db", host="127.0.0.1", port=upstream)
    local_port = service.state()["forwards"]["db"]["local_port"]
    client = socket.create_connection(("127.0.0.1", local_port), timeout=5)
    client.sendall(b"hello")
    assert client.recv(4096) == b"hello"

    assert service.stop(entry_id="db") == {}

    client.settimeout(5)
    try:
        leftover = client.recv(4096)
    except OSError:
        leftover = b""
    assert leftover == b""
    client.close()
    assert service.state()["forwards"] == {}


def test_release_closes_every_forward(upstream):
    service = PortServiceHandler(log=discard)
    service.forward(entry_id="a", host="127.0.0.1", port=upstream)
    service.forward(entry_id="b", host="127.0.0.1", port=upstream)
    ports = [row["local_port"] for row in service.state()["forwards"].values()]

    service.release()
    service.release()

    assert service.state()["forwards"] == {}
    for port in ports:
        with pytest.raises(OSError):
            socket.create_connection(("127.0.0.1", port), timeout=1)


def test_a_second_connect_reuses_the_running_relay(upstream):
    service = PortServiceHandler(log=discard)
    assert service.forward(entry_id="db", host="127.0.0.1", port=upstream) == {}
    first = service.state()["forwards"]["db"]["local_port"]

    assert service.forward(entry_id="db", host="127.0.0.1", port=upstream) == {}

    forwards = service.state()["forwards"]
    assert list(forwards) == ["db"]
    assert forwards["db"]["local_port"] == first
    service.stop(entry_id="db")


def test_an_unparsable_published_port_is_refused():
    service = PortServiceHandler(log=discard)
    entries = [dict(entry_for("not a number"), id="bad")]

    refused = service.act(entries=entries, body={"id": "bad", "is_enabled": True})

    assert refused == {"code": "unknown_request", "params": {}}
    assert service.state()["forwards"] == {}


def test_act_resolves_the_typed_entry(upstream):
    service = PortServiceHandler(log=discard)
    entries = [entry_for(upstream)]

    assert service.act(entries=entries, body={"id": "db", "is_enabled": True}) == {}
    assert service.state()["forwards"]["db"]["is_active"] is True
    assert service.act(entries=entries, body={"id": "db", "is_enabled": False}) == {}
    assert service.state()["forwards"] == {}
    assert service.act(entries=entries, body={"id": "gone"}) == {
        "code": "unknown_request",
        "params": {},
    }
