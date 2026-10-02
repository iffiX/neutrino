"""The port service, end to end over real loopback sockets, one forward per
service key, each on the port the one local port table gives it: auto takes
the entry's own port, else the first free one from 20000, and keeps it
across restarts; a fixed number is kept; no number is held by two entries.
"""

import functools
import socket
import threading

import pytest

from neutrino_client.services.port import PortLocalTable, PortServiceHandler
from neutrino_client.services.store import ClientServiceStore
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


def entry_for(port, hub_id="h1"):
    return {
        "hub_id": hub_id,
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
    assert (
        service.forward(hub_id="h1", entry_id="db", host="127.0.0.1", port=upstream)
        == {}
    )
    row = service.state()["forwards"]["h1/db"]
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
    service.stop(hub_id="h1", entry_id="db")

    assert received == b"ping across the relay"


def test_the_published_number_is_used_when_free():
    probe = socket.create_server(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    service = PortServiceHandler(log=discard)

    assert (
        service.forward(hub_id="h1", entry_id="web", host="127.0.0.1", port=port) == {}
    )

    assert service.state()["forwards"]["h1/web"]["local_port"] == port
    service.stop(hub_id="h1", entry_id="web")


def test_a_preferred_local_port_is_honored(upstream):
    probe = socket.create_server(("127.0.0.1", 0))
    wanted = probe.getsockname()[1]
    probe.close()
    service = PortServiceHandler(log=discard)

    outcome = service.act(
        entries=[entry_for(upstream)],
        body={"hub_id": "h1", "id": "db", "is_enabled": True, "local_port": wanted},
    )

    assert outcome == {}
    assert service.state()["forwards"]["h1/db"]["local_port"] == wanted
    service.stop(hub_id="h1", entry_id="db")


def test_disabling_closes_the_listener_and_open_connections(upstream):
    service = PortServiceHandler(log=discard)
    service.forward(hub_id="h1", entry_id="db", host="127.0.0.1", port=upstream)
    local_port = service.state()["forwards"]["h1/db"]["local_port"]
    client = socket.create_connection(("127.0.0.1", local_port), timeout=5)
    client.sendall(b"hello")
    assert client.recv(4096) == b"hello"

    assert service.stop(hub_id="h1", entry_id="db") == {}

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
    service.forward(hub_id="h1", entry_id="a", host="127.0.0.1", port=upstream)
    service.forward(hub_id="h1", entry_id="b", host="127.0.0.1", port=upstream)
    ports = [row["local_port"] for row in service.state()["forwards"].values()]

    service.release()
    service.release()

    assert service.state()["forwards"] == {}
    for port in ports:
        with pytest.raises(OSError):
            socket.create_connection(("127.0.0.1", port), timeout=1)


def test_a_second_connect_reuses_the_running_relay(upstream):
    service = PortServiceHandler(log=discard)
    assert (
        service.forward(hub_id="h1", entry_id="db", host="127.0.0.1", port=upstream)
        == {}
    )
    first = service.state()["forwards"]["h1/db"]["local_port"]

    assert (
        service.forward(hub_id="h1", entry_id="db", host="127.0.0.1", port=upstream)
        == {}
    )

    forwards = service.state()["forwards"]
    assert list(forwards) == ["h1/db"]
    assert forwards["h1/db"]["local_port"] == first
    service.stop(hub_id="h1", entry_id="db")


def test_an_unparsable_published_port_is_refused():
    service = PortServiceHandler(log=discard)
    entries = [dict(entry_for("not a number"), id="bad")]

    refused = service.act(
        entries=entries, body={"hub_id": "h1", "id": "bad", "is_enabled": True}
    )

    assert refused == {"code": "unknown_request", "params": {}}
    assert service.state()["forwards"] == {}


def test_act_resolves_the_typed_entry(upstream):
    service = PortServiceHandler(log=discard)
    entries = [entry_for(upstream)]

    body = {"hub_id": "h1", "id": "db", "is_enabled": True}
    assert service.act(entries=entries, body=body) == {}
    assert service.state()["forwards"]["h1/db"]["is_active"] is True
    assert service.act(entries=entries, body=dict(body, is_enabled=False)) == {}
    assert service.state()["forwards"] == {}
    assert service.act(entries=entries, body={"hub_id": "h1", "id": "gone"}) == {
        "code": "unknown_request",
        "params": {},
    }
    assert service.act(entries=entries, body={"hub_id": "h2", "id": "db"}) == {
        "code": "unknown_request",
        "params": {},
    }


def test_two_hubs_publishing_one_id_are_two_forwards(upstream):
    service = PortServiceHandler(log=discard)
    entries = [entry_for(upstream), entry_for(upstream, hub_id="h2")]

    for hub_id in ("h1", "h2"):
        body = {"hub_id": hub_id, "id": "db", "is_enabled": True}
        assert service.act(entries=entries, body=body) == {}

    forwards = service.state()["forwards"]
    assert sorted(forwards) == ["h1/db", "h2/db"]
    assert forwards["h1/db"]["local_port"] != forwards["h2/db"]["local_port"]
    service.release()


def test_release_hub_closes_only_that_hubs_forwards(upstream):
    changes = []
    service = PortServiceHandler(log=discard, on_change=lambda: changes.append(1))
    service.forward(hub_id="h1", entry_id="a", host="127.0.0.1", port=upstream)
    service.forward(hub_id="h2", entry_id="a", host="127.0.0.1", port=upstream)
    service.forward(hub_id="h2", entry_id="b", host="127.0.0.1", port=upstream)
    gone = [service.state()["forwards"][key]["local_port"] for key in ("h2/a", "h2/b")]
    kept = service.state()["forwards"]["h1/a"]["local_port"]
    changes.clear()

    assert service.release_hub("h2") == 2
    assert service.release_hub("h2") == 0

    assert list(service.state()["forwards"]) == ["h1/a"]
    assert changes == [1]
    for port in gone:
        with pytest.raises(OSError):
            socket.create_connection(("127.0.0.1", port), timeout=1)
    socket.create_connection(("127.0.0.1", kept), timeout=1).close()
    service.release()


# --- the one table of local ports ---


def table_on(tmp_path, busy=()):
    """A table kept in a store file, every port free but the busy ones."""
    store = ClientServiceStore(path=str(tmp_path / "state.json"))
    return PortLocalTable(store=store, is_free=functools.partial(_is_free, busy))


def test_auto_takes_the_entrys_own_port_when_free_and_keeps_it(tmp_path):
    table = table_on(tmp_path)

    assert table.setting("h1/db") == "auto"
    assert table.take("h1/db", 5432) == 5432
    assert table_on(tmp_path, busy=(5432,)).take("h1/db", 5432) == 5432


def test_auto_takes_the_first_free_port_from_20000_when_its_own_is_not_to_be_had(
    tmp_path,
):
    table = table_on(tmp_path, busy=(8000, 20000))

    assert table.take("h1/code", 8000) == 20001
    assert table.take("h2/code", 8000) == 20002
    assert table_on(tmp_path).take("h2/code", 8000) == 20002


def test_no_two_entries_hold_one_number(tmp_path):
    table = table_on(tmp_path)

    assert table.take("h1/code", 8000) == 8000
    assert table.take("h2/code", 8000) == 20000
    assert table.configure("h3/db", 20000) == {
        "code": "port_taken",
        "params": {"port": 20000},
    }
    assert table.configure("h3/db", 8000)["code"] == "port_taken"


def test_a_fixed_number_is_kept_and_auto_picks_again_after_it(tmp_path):
    table = table_on(tmp_path)
    assert table.take("h1/db", 5432) == 5432

    assert table.configure("h1/db", 15432) == {}
    assert table_on(tmp_path).setting("h1/db") == 15432
    assert table.take("h1/db", 5432) == 15432
    assert table.configure("h1/db", "auto") == {}
    assert table.setting("h1/db") == "auto"
    assert table.take("h1/db", 5432) == 5432


def test_a_number_out_of_range_or_of_another_shape_is_refused(tmp_path):
    table = table_on(tmp_path)

    for setting in (1023, 65536, "8000", True, None):
        assert table.configure("h1/db", setting) == {
            "code": "unknown_request",
            "params": {},
        }
    assert table.setting("h1/db") == "auto"


def test_a_forward_listens_on_the_tables_port(upstream, tmp_path):
    table = table_on(tmp_path)
    probe = socket.create_server(("127.0.0.1", 0))
    wanted = probe.getsockname()[1]
    probe.close()
    table.configure("h1/db", wanted)
    service = PortServiceHandler(log=discard, ports=table)

    outcome = service.act(
        entries=[entry_for(upstream)],
        body={"hub_id": "h1", "id": "db", "is_enabled": True},
    )

    assert outcome == {}
    assert service.state()["forwards"]["h1/db"]["local_port"] == wanted
    service.release()


def test_a_port_the_system_holds_fails_the_forward(upstream, tmp_path):
    held = socket.create_server(("127.0.0.1", 0))
    table = table_on(tmp_path)
    table.configure("h1/db", held.getsockname()[1])
    service = PortServiceHandler(log=discard, ports=table)

    outcome = service.act(
        entries=[entry_for(upstream)],
        body={"hub_id": "h1", "id": "db", "is_enabled": True},
    )

    assert outcome["code"] == "forward_failed"
    assert service.state()["forwards"] == {}
    held.close()


def _is_free(busy, port) -> bool:
    return port not in busy
