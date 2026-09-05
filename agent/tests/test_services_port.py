"""The port service, end to end over real loopback sockets."""

import socket
import threading

import pytest

from neutrino_agent.services.port import PortServiceHandler


def discard(message: str) -> None:
    """Swallow the log lines."""


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


def test_a_forward_relays_bytes_both_ways(upstream):
    service = PortServiceHandler(log=discard)
    assert service.forward(entry_id="db", host="127.0.0.1", port=upstream) == {}
    row = service.state()["forwards"]["db"]
    assert row["is_active"] is True
    # The published number is held by the upstream itself, so the relay
    # names a free one instead.
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


def test_stopping_what_is_not_running_is_nothing():
    service = PortServiceHandler(log=discard)

    assert service.stop(entry_id="gone") == {}
    assert service.state()["forwards"] == {}


def test_act_resolves_the_typed_entry(upstream):
    service = PortServiceHandler(log=discard)
    entries = [
        {
            "id": "db",
            "type": "port",
            "title": "db",
            "payload": {"host": "127.0.0.1", "port": upstream},
            "is_healthy": True,
            "source": "module",
            "description": "",
        }
    ]

    assert (
        service.act(
            entries=entries,
            account="alice",
            is_privileged=False,
            body={"id": "db", "is_enabled": True},
        )
        == {}
    )
    assert service.state()["forwards"]["db"]["is_active"] is True

    assert (
        service.act(
            entries=entries,
            account="alice",
            is_privileged=False,
            body={"id": "db", "is_enabled": False},
        )
        == {}
    )
    assert service.state()["forwards"] == {}

    refused = service.act(
        entries=entries, account="alice", is_privileged=False, body={"id": "gone"}
    )
    assert refused == {"code": "unknown_request", "params": {}}
