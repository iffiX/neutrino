"""The local forwards: a listener on ``127.0.0.1`` at the entry's local port,
one ``connect`` stream per accepted connection and no dial to a device
address, a clean end when the forward, the stream or the socket goes; and
the one table of local ports: auto takes the entry's own port when nothing
listens on it on any address of the machine, else the first free one from
20000, kept per entry; a fixed number is kept; no number is held by two
entries.
"""

import functools
import socket
import threading
import time

import pytest

from neutrino_client.exceptions import GatewayUnreachable
from neutrino_client.services.forward import (
    FORWARD_PANEL_ID,
    ConnectStreamSocket,
    ForwardListenerRegistry,
    PortLocalTable,
    is_port_free,
    relay_socket,
)
from neutrino_client.services.store import ClientServiceStore
from tests.conftest import FakeConnectHub, discard, echo_server, round_trip


@pytest.fixture
def far():
    """What the hub would dial: a real echo server on the loopback."""
    port, close = echo_server()
    yield port
    close()


@pytest.fixture
def hub(far):
    return FakeConnectHub(far_port=far)


@pytest.fixture
def forwards(hub):
    registry = ForwardListenerRegistry(open_connect=hub.open_connect, log=discard)
    yield registry
    registry.release()


def wait_for(condition, timeout_s: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return condition()


def free_port() -> int:
    probe = socket.create_server(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


# --- the listener and its streams ---


def test_every_accepted_connection_is_one_connect_stream_through_the_hub(hub, forwards):
    port = forwards.ensure(hub_id="h1", entry_id="db", own_port=0, kind="port")

    assert round_trip(port, b"first") == b"first"
    assert round_trip(port, b"second") == b"second"

    assert hub.opens == [("h1", {"id": "db"}), ("h1", {"id": "db"})]


def test_the_listener_takes_the_loopback_alone(forwards):
    forwards.ensure(hub_id="h1", entry_id="db", own_port=0, kind="port")

    listener = forwards._listeners["h1/db"]._listener
    assert listener.getsockname()[0] == "127.0.0.1"


def test_the_panel_forward_opens_the_panel_by_name(hub, forwards):
    port = forwards.ensure(
        hub_id="h1", entry_id=FORWARD_PANEL_ID, own_port=0, kind="panel"
    )

    assert round_trip(port, b"GET /") == b"GET /"
    assert hub.opens == [("h1", {"is_panel": True})]
    assert port >= 20000


def test_bytes_larger_than_a_frame_cross_both_ways(forwards):
    port = forwards.ensure(hub_id="h1", entry_id="db", own_port=0, kind="port")
    payload = bytes(range(256)) * 2048

    assert round_trip(port, payload) == payload


def test_a_second_ensure_keeps_the_running_listener(forwards):
    first = forwards.ensure(hub_id="h1", entry_id="db", own_port=0, kind="port")

    assert forwards.ensure(hub_id="h1", entry_id="db", own_port=0, kind="port") == first
    assert forwards.forwards() == {"h1/db": first}


def test_stop_closes_the_listener_and_ends_every_stream(hub, forwards):
    port = forwards.ensure(hub_id="h1", entry_id="db", own_port=0, kind="port")
    client = socket.create_connection(("127.0.0.1", port), timeout=5)
    client.sendall(b"hello")
    assert client.recv(4096) == b"hello"

    assert forwards.stop("h1", "db") is True
    assert forwards.stop("h1", "db") is False

    client.settimeout(5)
    try:
        leftover = client.recv(4096)
    except OSError:
        leftover = b""
    assert leftover == b""
    client.close()
    assert wait_for(lambda: hub.closed_here == [1])
    assert forwards.forwards() == {}
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=1)


def test_the_far_end_closing_writes_what_it_sent_and_closes_the_connection(
    forwards,
):
    server = socket.create_server(("127.0.0.1", 0))
    registry = ForwardListenerRegistry(
        open_connect=FakeConnectHub(far_port=server.getsockname()[1]).open_connect,
        log=discard,
    )
    port = registry.ensure(hub_id="h1", entry_id="web", own_port=0, kind="web")
    client = socket.create_connection(("127.0.0.1", port), timeout=5)
    far_side, _address = server.accept()
    far_side.sendall(b"the whole answer")
    far_side.close()

    received = b""
    while True:
        chunk = client.recv(4096)
        if not chunk:
            break
        received += chunk

    assert received == b"the whole answer"
    client.close()
    registry.release()
    server.close()


def test_a_refused_stream_closes_the_connection_and_the_listener_stays(hub, forwards):
    hub.refusal = "permission_denied"
    port = forwards.ensure(hub_id="h1", entry_id="db", own_port=0, kind="port")
    client = socket.create_connection(("127.0.0.1", port), timeout=5)
    client.settimeout(5)

    try:
        answer = client.recv(4096)
    except OSError:
        answer = b""

    assert answer == b""
    client.close()
    assert forwards.port_of("h1", "db") == port


def test_a_hub_that_is_not_connected_closes_the_connection(hub, forwards):
    hub.error = GatewayUnreachable("this hub is not connected")
    port = forwards.ensure(hub_id="h1", entry_id="db", own_port=0, kind="port")
    client = socket.create_connection(("127.0.0.1", port), timeout=5)
    client.settimeout(5)

    try:
        answer = client.recv(4096)
    except OSError:
        answer = b""

    assert answer == b""
    client.close()


def test_relay_socket_carries_one_connection_for_any_caller(hub, far):
    left, right = socket.socketpair()
    stream = hub.open_connect("h1", {"id": "share"})
    worker = threading.Thread(target=relay_socket, args=(right, stream, discard))
    worker.start()
    left.sendall(b"over the stream")
    received = b""
    while len(received) < len(b"over the stream"):
        received += left.recv(4096)
    left.close()
    worker.join(timeout=5)

    assert received == b"over the stream"
    assert not worker.is_alive()
    assert stream.is_done


# --- a connect stream with a socket's face, for the files endpoint ---


def test_the_socket_face_sends_and_receives_in_the_sizes_asked(hub):
    far = ConnectStreamSocket(hub.open_connect("h1", {"id": "share"}))

    far.sendall(b"abcdef")
    received = b""
    while len(received) < 6:
        received += far.recv(4)

    assert received == b"abcdef"
    far.close()


def test_a_close_from_another_thread_ends_a_waiting_recv(hub):
    far = ConnectStreamSocket(hub.open_connect("h1", {"id": "share"}))
    got = []
    reader = threading.Thread(target=lambda: got.append(far.recv(10)))
    reader.start()

    far.close()
    reader.join(timeout=5)

    assert got == [b""]


# --- the registry over every hub ---


def test_release_hub_ends_only_that_hubs_forwards_the_panel_among_them(forwards):
    changes = []
    forwards._on_change = lambda: changes.append(1)
    forwards.ensure(hub_id="h1", entry_id="a", own_port=0, kind="port")
    gone = [
        forwards.ensure(hub_id="h2", entry_id="a", own_port=0, kind="port"),
        forwards.ensure(
            hub_id="h2", entry_id=FORWARD_PANEL_ID, own_port=0, kind="panel"
        ),
    ]
    changes.clear()

    assert forwards.release_hub("h2") == 2
    assert forwards.release_hub("h2") == 0

    assert list(forwards.forwards()) == ["h1/a"]
    assert changes == [1]
    for port in gone:
        with pytest.raises(OSError):
            socket.create_connection(("127.0.0.1", port), timeout=1)


def test_an_entry_gone_from_the_list_ends_its_port_and_web_forwards(forwards):
    for entry_id, kind in (("db", "port"), ("wiki", "web"), ("ai", "ai")):
        forwards.ensure(hub_id="h1", entry_id=entry_id, own_port=0, kind=kind)
    forwards.ensure(hub_id="h1", entry_id=FORWARD_PANEL_ID, own_port=0, kind="panel")
    forwards.ensure(hub_id="h2", entry_id="db", own_port=0, kind="port")

    ended = forwards.drop_withdrawn(hub_id="h1", entries=[{"id": "wiki"}])

    assert ended == 1
    assert sorted(forwards.forwards()) == [
        "h1/:panel",
        "h1/ai",
        "h1/wiki",
        "h2/db",
    ]


def test_release_kind_ends_one_kind_of_one_hub(forwards):
    forwards.ensure(hub_id="h1", entry_id="d1", own_port=0, kind="rdp")
    forwards.ensure(hub_id="h2", entry_id="d2", own_port=0, kind="rdp")
    forwards.ensure(hub_id="h1", entry_id="db", own_port=0, kind="port")

    assert forwards.release_kind("rdp", "h1") == 1
    assert sorted(forwards.forwards()) == ["h1/db", "h2/d2"]
    assert forwards.release_kind("rdp") == 1
    assert forwards.release() == 1
    assert forwards.forwards() == {}


def test_a_port_the_system_holds_fails_the_forward(hub):
    held = socket.create_server(("127.0.0.1", 0))
    registry = ForwardListenerRegistry(open_connect=hub.open_connect, log=discard)
    registry.ports.configure("h1/db", held.getsockname()[1])

    with pytest.raises(OSError):
        registry.ensure(hub_id="h1", entry_id="db", own_port=0, kind="port")

    assert registry.forwards() == {}
    held.close()


def test_a_number_asked_for_once_is_listened_on(forwards):
    wanted = free_port()

    assert (
        forwards.ensure(
            hub_id="h1", entry_id="db", own_port=0, kind="port", local_port=wanted
        )
        == wanted
    )


# --- a port is free only when nothing listens on any address ---


def test_a_port_nothing_listens_on_is_free():
    assert is_port_free(free_port()) is True


def test_a_port_held_on_the_loopback_is_not_free():
    held = socket.create_server(("127.0.0.1", 0))

    assert is_port_free(held.getsockname()[1]) is False
    held.close()


def test_a_port_held_on_every_address_is_not_free():
    held = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    held.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    held.bind(("0.0.0.0", 0))  # scan: allow
    held.listen()

    assert is_port_free(held.getsockname()[1]) is False
    held.close()


@pytest.mark.skipif(not socket.has_ipv6, reason="no IPv6 on this machine")
def test_a_port_held_on_the_ipv6_wildcard_alone_is_not_free():
    try:
        held = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        held.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        held.bind(("::", 0))
    except OSError:
        pytest.skip("no IPv6 address to bind")
    held.listen()

    assert is_port_free(held.getsockname()[1]) is False
    held.close()


def test_a_number_outside_the_ports_is_not_free():
    assert is_port_free(70000) is False


# --- the one table of local ports ---


def table_on(tmp_path, busy=()):
    """A table kept in a store file, every port free but the busy ones."""
    store = ClientServiceStore(path=str(tmp_path / "state.json"))
    return PortLocalTable(store=store, is_free=functools.partial(_is_free, busy))


def test_the_table_asks_whether_a_port_is_free_on_every_address():
    assert PortLocalTable()._is_free is is_port_free


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


def test_an_entry_with_no_port_of_its_own_starts_at_20000(tmp_path):
    table = table_on(tmp_path)

    assert table.take("h1/:panel", 0) == 20000
    assert table.take("h2/:panel", 0) == 20001


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


def test_a_forward_listens_on_the_tables_port(hub, tmp_path):
    table = table_on(tmp_path)
    wanted = free_port()
    table.configure("h1/db", wanted)
    registry = ForwardListenerRegistry(
        open_connect=hub.open_connect, ports=table, log=discard
    )

    assert registry.ensure(hub_id="h1", entry_id="db", own_port=0, kind="port") == (
        wanted
    )
    registry.release()


def _is_free(busy, port) -> bool:
    return port not in busy
