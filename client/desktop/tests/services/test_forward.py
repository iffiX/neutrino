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
import struct
import sys
import threading
import time

import pytest

import neutrino_client.services.forward as forward_module
from neutrino_client.exceptions import GatewayUnreachable
from neutrino_client.platforms import win32
from neutrino_client.services.forward import (
    FORWARD_PANEL_ID,
    ConnectStreamSocket,
    ForwardListenerRegistry,
    PortLocalTable,
    is_kept_port_free,
    is_port_free,
    is_udp_port_free,
    relay_socket,
)
from neutrino_client.exceptions import LocalPortTakenError
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
    assert table_on(tmp_path).take("h1/db", 5432) == 5432


def test_a_kept_auto_port_another_program_took_is_picked_again_and_kept(tmp_path):
    assert table_on(tmp_path).take("h1/db", 5432) == 5432

    assert table_on(tmp_path, busy=(5432,)).take("h1/db", 5432) == 20000

    assert table_on(tmp_path).setting("h1/db") == "auto"
    assert table_on(tmp_path).take("h1/db", 5432) == 20000


def test_a_fixed_port_another_program_took_is_refused_and_kept(tmp_path):
    table = table_on(tmp_path, busy=(15432,))
    assert table.configure("h1/db", 15432) == {}

    with pytest.raises(LocalPortTakenError) as taken:
        table.take("h1/db", 5432)

    assert taken.value.port == 15432
    assert table.setting("h1/db") == 15432
    assert table_on(tmp_path).take("h1/db", 5432) == 15432


def test_a_kept_port_on_the_wildcard_of_another_socket_is_picked_again(tmp_path):
    """The lab's B1-6: another program listens on every address of the
    port the entry kept, and the forward must not listen beside it."""
    other = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    other.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    other.bind(("0.0.0.0", 0))  # scan: allow
    other.listen()
    port = other.getsockname()[1]
    store = ClientServiceStore(path=str(tmp_path / "state.json"))
    store.set_local_port("h1/web", "auto", port)
    table = PortLocalTable(store=store)

    picked = table.take("h1/web", port)

    assert picked != port
    assert store.local_ports()["h1/web"] == {
        "setting": "auto",
        "port": picked,
        "protocol": "tcp",
    }
    other.close()


def test_a_kept_port_still_free_is_kept_without_a_new_pick(tmp_path):
    port = free_port()
    store = ClientServiceStore(path=str(tmp_path / "state.json"))
    store.set_local_port("h1/web", "auto", port)

    assert PortLocalTable(store=store).take("h1/web", 0) == port
    assert store.local_ports()["h1/web"]["port"] == port


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux's TIME_WAIT")
def test_the_clients_own_closed_connections_do_not_take_its_kept_port():
    listener = socket.create_server(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    client = socket.create_connection(("127.0.0.1", port))
    served, _ = listener.accept()
    served.close()
    client.recv(1)
    client.close()
    listener.close()

    assert is_kept_port_free(port) is True


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


# --- a UDP entry's forward: one socket, one stream ---


from neutrino_client.core.streams import ClientStream  # noqa: E402
from neutrino_client.services.forward import UdpForwardListener  # noqa: E402
from neutrino_client.services.port import PortServiceHandler  # noqa: E402


def udp_echo():
    """A real UDP server on the loopback answering ``echo:<datagram>``."""
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.bind(("127.0.0.1", 0))
    received = []

    def serve() -> None:
        while True:
            try:
                data, address = server.recvfrom(65535)
            except OSError:
                return
            received.append(data)
            server.sendto(b"echo:" + data, address)

    threading.Thread(target=serve, daemon=True).start()
    return server, received


class FakeUdpHub:
    """The hub and the far end of UDP ``connect`` streams, on the loopback.

    Each frame's source gets a UDP socket of its own connected to
    ``far_port``, and its replies come back with that source in front, as
    U.md's far end does. ``is_crediting`` False opens streams with no
    credit until :meth:`credit` grants it; ``refusal`` closes every new
    stream with that code just after its credit, as the hub does.
    """

    def __init__(self, far_port: int):
        self.far_port = far_port
        self.opens = []
        self.streams = []
        self.frames = []
        self.is_crediting = True
        self.refusal = ""
        self.error = None
        self._next_id = 1

    def open_connect(self, hub_id: str, args: dict):
        if self.error is not None:
            raise self.error
        self.opens.append((hub_id, dict(args)))
        sockets = {}
        stream_id = self._next_id
        self._next_id += 2
        holder = {}

        def send_bytes(frame: bytes) -> None:
            payload = frame[4:]
            self.frames.append(payload)
            source, data = payload[:2], payload[2:]
            far = sockets.get(source)
            if far is None:
                far = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                far.connect(("127.0.0.1", self.far_port))
                sockets[source] = far

                def answer() -> None:
                    while True:
                        try:
                            reply = far.recv(65535)
                        except OSError:
                            return
                        holder["stream"].take_bytes(source + reply)

                threading.Thread(target=answer, daemon=True).start()
            far.send(data)

        def close() -> None:
            for far in sockets.values():
                far.close()

        stream = ClientStream(
            stream_id=stream_id,
            kind="connect",
            send_bytes=send_bytes,
            grant=lambda nbytes: None,
            close=close,
        )
        holder["stream"] = stream
        self.streams.append(stream)
        if self.is_crediting:
            stream.take_credit(1 << 20)
        if self.refusal:
            code = self.refusal
            stream.take_credit(1 << 20)
            threading.Timer(
                0.02,
                lambda: stream.take_close(code=code, params={"kind": "port"}),
            ).start()
        return stream

    def credit(self, stream, nbytes: int = 1 << 20) -> None:
        stream.take_credit(nbytes)


@pytest.fixture
def udp_far():
    server, received = udp_echo()
    yield server.getsockname()[1], received
    server.close()


def ask(port: int, payload: bytes, program=None) -> bytes:
    """Send one datagram to the forward from a local program, read its reply."""
    program = program or socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    program.settimeout(5)
    program.sendto(payload, ("127.0.0.1", port))
    return program.recvfrom(65535)[0]


def test_two_local_programs_through_one_stream_each_get_their_own_replies(udp_far):
    far_port, _received = udp_far
    hub = FakeUdpHub(far_port)
    registry = ForwardListenerRegistry(open_connect=hub.open_connect, log=discard)
    port = registry.ensure(
        hub_id="h1", entry_id="dns_udp", own_port=0, kind="port", protocol="udp"
    )
    first = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    second = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    assert ask(port, b"one", first) == b"echo:one"
    assert ask(port, b"two", second) == b"echo:two"
    assert ask(port, b"again", first) == b"echo:again"

    assert hub.opens == [("h1", {"id": "dns_udp"})]
    sources = {frame[:2] for frame in hub.frames}
    assert sources == {
        first.getsockname()[1].to_bytes(2, "big"),
        second.getsockname()[1].to_bytes(2, "big"),
    }
    first.close()
    second.close()
    registry.release()


def test_the_udp_forward_binds_the_loopback_alone(udp_far):
    hub = FakeUdpHub(udp_far[0])
    registry = ForwardListenerRegistry(open_connect=hub.open_connect, log=discard)
    registry.ensure(
        hub_id="h1", entry_id="dns_udp", own_port=0, kind="port", protocol="udp"
    )

    listener = registry._listeners["h1/dns_udp"]
    assert listener._socket.getsockname()[0] == "127.0.0.1"
    assert listener._socket.type == socket.SOCK_DGRAM
    registry.release()


def test_a_datagram_of_zero_bytes_is_carried_as_two_bytes(udp_far):
    far_port, received = udp_far
    hub = FakeUdpHub(far_port)
    registry = ForwardListenerRegistry(open_connect=hub.open_connect, log=discard)
    port = registry.ensure(
        hub_id="h1", entry_id="u", own_port=0, kind="port", protocol="udp"
    )

    assert ask(port, b"") == b"echo:"

    assert [len(frame) for frame in hub.frames] == [2]
    registry.release()


UDP_ENTRY = {
    "hub_id": "h1",
    "id": "dns_udp",
    "type": "port",
    "payload": {"host": "hub", "port": 53, "protocol": "udp"},
}
CONNECT_UDP = {"hub_id": "h1", "id": "dns_udp", "is_enabled": True}


def wait_for_true(condition, timeout_s: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.01)
    return condition()


def test_a_refusal_before_any_datagram_ends_the_forward_with_the_code(udp_far):
    """The hub grants the first credit before it judges the open, so the
    refusal comes after Connect: the forward ends and the row has the code."""
    hub = FakeUdpHub(udp_far[0])
    hub.refusal = "permission_denied"
    refused = []
    registry = ForwardListenerRegistry(
        open_connect=hub.open_connect,
        log=discard,
        on_refused=lambda *told: refused.append(told),
    )
    handler = PortServiceHandler(forwards=registry, log=discard)

    assert handler.act(entries=[UDP_ENTRY], body=CONNECT_UDP) == {}

    assert wait_for_true(lambda: registry.forwards() == {})
    assert refused == [
        ("h1", "dns_udp", {"code": "permission_denied", "params": {"kind": "port"}})
    ]


def test_connect_with_no_hub_to_ask_fails_at_once_with_its_code(udp_far):
    hub = FakeUdpHub(udp_far[0])
    hub.error = GatewayUnreachable("this hub is not connected")
    registry = ForwardListenerRegistry(open_connect=hub.open_connect, log=discard)
    handler = PortServiceHandler(forwards=registry, log=discard)

    outcome = handler.act(entries=[UDP_ENTRY], body=CONNECT_UDP)

    assert outcome["code"] == "hub_unreachable"
    assert registry.forwards() == {}


@pytest.mark.parametrize("is_socket_gone", [True, False])
def test_a_stream_ending_with_no_code_tells_nobody_and_the_next_datagram_reopens(
    udp_far, is_socket_gone
):
    far_port, _received = udp_far
    hub = FakeUdpHub(far_port)
    refused = []
    now = {"t": 100.0}
    listener = UdpForwardListener(
        open_stream=lambda: hub.open_connect("h1", {"id": "u"}),
        local_port=0,
        kind="port",
        log=discard,
        on_refused=lambda *told: refused.append(told),
        clock=lambda: now["t"],
    )
    port = listener.start()

    if is_socket_gone:
        hub.streams[0].end()
    else:
        hub.streams[0].take_close(code="", params={})
    assert wait_for_true(lambda: listener._stream is None)
    now["t"] += 5

    assert ask(port, b"after") == b"echo:after"
    assert refused == []
    assert len(hub.opens) == 2
    listener.close()


def test_an_open_refused_later_keeps_listening_and_tries_again_once_a_second(udp_far):
    far_port, _received = udp_far
    hub = FakeUdpHub(far_port)
    now = {"t": 100.0}
    refusals = []
    listener = UdpForwardListener(
        open_stream=lambda: hub.open_connect("h1", {"id": "u"}),
        local_port=0,
        kind="port",
        log=discard,
        on_refused=lambda *told: refusals.append(told),
        clock=lambda: now["t"],
    )
    port = listener.start()
    assert ask(port, b"first") == b"echo:first"

    hub.refusal = "agent_offline"
    hub.streams[0].take_close(code="agent_offline", params={"device": "d1"})
    deadline = time.monotonic() + 5
    while not refusals and time.monotonic() < deadline:
        time.sleep(0.01)
    assert refusals == [({"code": "agent_offline", "params": {"device": "d1"}}, False)]
    assert listener.is_active

    program = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    now["t"] += 0.5
    program.sendto(b"too soon", ("127.0.0.1", port))
    time.sleep(0.2)
    assert len(hub.opens) == 1
    now["t"] += 1.0
    hub.refusal = ""
    program.sendto(b"later", ("127.0.0.1", port))
    deadline = time.monotonic() + 5
    while len(hub.opens) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert len(hub.opens) == 2
    program.close()
    listener.close()


def test_a_refusal_is_answered_by_the_first_reply_not_by_the_first_credit(udp_far):
    """A container stopped, then started: the error line goes when a reply
    comes back on a later stream, never at its credit alone."""
    far_port, _received = udp_far
    hub = FakeUdpHub(far_port)
    now = {"t": 100.0}
    refusals = []
    answers = []
    listener = UdpForwardListener(
        open_stream=lambda: hub.open_connect("h1", {"id": "u"}),
        local_port=0,
        kind="port",
        log=discard,
        on_refused=lambda *told: refusals.append(told),
        on_answered=lambda: answers.append(1),
        clock=lambda: now["t"],
    )
    port = listener.start()
    assert ask(port, b"first") == b"echo:first"
    assert answers == []
    hub.streams[0].take_close(code="port_not_published", params={"port": 5353})
    deadline = time.monotonic() + 5
    while not refusals and time.monotonic() < deadline:
        time.sleep(0.01)

    silent = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    silent.bind(("127.0.0.1", 0))
    hub.far_port = silent.getsockname()[1]
    now["t"] += 2.0
    program = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    program.sendto(b"nobody answers", ("127.0.0.1", port))
    deadline = time.monotonic() + 5
    while len(hub.opens) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    time.sleep(0.3)
    assert len(hub.opens) == 2 and answers == []

    hub.far_port = far_port
    assert ask(port, b"back") == b"echo:back"
    deadline = time.monotonic() + 5
    while not answers and time.monotonic() < deadline:
        time.sleep(0.01)
    assert answers == [1]
    assert ask(port, b"again") == b"echo:again"
    assert answers == [1]
    silent.close()
    program.close()
    listener.close()


def test_datagrams_wait_for_a_reopened_streams_first_credit_sixteen_at_most(udp_far):
    far_port, received = udp_far
    hub = FakeUdpHub(far_port)
    listener = UdpForwardListener(
        open_stream=lambda: hub.open_connect("h1", {"id": "u"}),
        local_port=0,
        kind="port",
        log=discard,
        clock=lambda: 1000.0 + len(hub.opens) * 10,
    )
    port = listener.start()
    hub.is_crediting = False
    hub.streams[0].take_close(code="", params={})
    deadline = time.monotonic() + 5
    while listener._stream is not None and time.monotonic() < deadline:
        time.sleep(0.01)
    program = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    for index in range(20):
        program.sendto(b"held-%d" % index, ("127.0.0.1", port))
    deadline = time.monotonic() + 5
    while len(listener._held) < 16 and time.monotonic() < deadline:
        time.sleep(0.01)
    time.sleep(0.1)
    assert len(hub.opens) == 2
    assert len(listener._held) == 16
    assert hub.frames == []

    hub.credit(hub.streams[1])
    deadline = time.monotonic() + 5
    while len(received) < 16 and time.monotonic() < deadline:
        time.sleep(0.01)
    time.sleep(0.1)
    assert received == [b"held-%d" % index for index in range(16)]
    program.close()
    listener.close()


class RecordingStream:
    """A stream that takes every frame the credit allows, and records it."""

    is_done = False

    def __init__(self, credit: int = 1 << 20):
        self.sent = []
        self.credit = credit

    def try_send(self, frame: bytes) -> bool:
        if len(frame) > self.credit:
            return False
        self.credit -= len(frame)
        self.sent.append(frame)
        return True


def bare_listener(stream) -> UdpForwardListener:
    listener = UdpForwardListener(
        open_stream=lambda: stream, local_port=0, kind="port", log=discard
    )
    listener._stream = stream
    return listener


def test_a_datagram_the_credit_does_not_cover_is_dropped_never_queued():
    stream = RecordingStream(credit=10)
    listener = bare_listener(stream)

    listener.take_datagram(b"12345678", ("127.0.0.1", 4000))
    listener.take_datagram(b"another", ("127.0.0.1", 4000))

    assert stream.sent == [(4000).to_bytes(2, "big") + b"12345678"]
    assert listener._held == []


def test_the_sixty_fifth_source_replaces_the_one_idle_longest():
    stream = RecordingStream()
    listener = bare_listener(stream)

    for source in range(5000, 5065):
        listener.take_datagram(b"x", ("127.0.0.1", source))

    assert len(listener._sources) == 64
    assert 5000 not in listener._sources
    assert 5064 in listener._sources


def test_a_frame_for_a_forgotten_source_or_too_short_is_dropped():
    stream = RecordingStream()
    listener = bare_listener(stream)
    sent = []

    class Socket:
        def sendto(self, data, address):
            sent.append((data, address))

    listener._socket = Socket()
    listener.take_datagram(b"q", ("127.0.0.1", 6000))

    listener.take_frame((6000).to_bytes(2, "big") + b"answer")
    listener.take_frame((6001).to_bytes(2, "big") + b"nobody asked")
    listener.take_frame(b"\x01")

    assert sent == [(b"answer", ("127.0.0.1", 6000))]


# --- the table per protocol ---


def test_a_tcp_and_a_udp_entry_hold_one_number_and_auto_gives_both_their_own(
    tmp_path,
):
    table = table_on(tmp_path)

    assert table.take("h1/dns", 53, "tcp") == 53
    assert table.take("h1/dns_udp", 53, "udp") == 53
    assert table.take("h2/dns_udp", 53, "udp") == 20000
    stored = ClientServiceStore(path=str(tmp_path / "state.json")).local_ports()
    assert stored["h1/dns"]["protocol"] == "tcp"
    assert stored["h1/dns_udp"]["protocol"] == "udp"


def test_a_fixed_number_is_taken_only_against_the_same_protocol(tmp_path):
    table = table_on(tmp_path)
    assert table.configure("h1/a", 15353, "tcp") == {}

    assert table.configure("h1/b", 15353, "udp") == {}
    assert table.configure("h1/c", 15353, "udp") == {
        "code": "port_taken",
        "params": {"port": 15353},
    }
    assert table.configure("h1/d", 15353, "tcp")["code"] == "port_taken"


def test_a_table_from_before_udp_entries_reads_as_tcp(tmp_path):
    path = tmp_path / "state.json"
    path.write_text('{"local_ports": {"h1/db": {"setting": "auto", "port": 5432}}}')
    table = PortLocalTable(
        store=ClientServiceStore(path=str(path)), is_free=lambda port: True
    )

    assert table.take("h1/db", 5432, "tcp") == 5432
    assert table.take("h1/db_udp", 5432, "udp") == 5432


def test_the_udp_probe_binds_udp_sockets_on_the_wildcard():
    held = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    held.bind(("0.0.0.0", 0))  # scan: allow
    port = held.getsockname()[1]

    assert is_udp_port_free(port) is False
    assert is_port_free(port) is True
    held.close()
    assert is_udp_port_free(port) is True


# --- the UDP probe on Windows: the system's table, never a wildcard bind ---

IPV4_ANY = "0.0.0.0"  # scan: allow


def udp_table(family: int, endpoints: list) -> bytes:
    """A table laid out as GetExtendedUdpTable writes it with UDP_TABLE_BASIC."""
    rows = [struct.pack("<I", len(endpoints))]
    for address, port in endpoints:
        if family == win32.WIN_AF_INET6:
            packed = socket.inet_pton(socket.AF_INET6, address)
            rows.append(packed + struct.pack("<I", 0) + struct.pack(">HH", port, 0))
        else:
            packed = socket.inet_pton(socket.AF_INET, address)
            rows.append(packed + struct.pack(">HH", port, 0))
    return b"".join(rows)


class NoSockets:
    """Stands in for socket.socket and records every socket asked for."""

    made = []

    def __init__(self, *args, **kwargs):
        NoSockets.made.append(args)
        raise AssertionError("a socket was made")


@pytest.fixture
def windows_udp(monkeypatch):
    """The Windows UDP probe, its table call scripted per family."""
    tables = {win32.WIN_AF_INET: [], win32.WIN_AF_INET6: []}
    asked = []

    def read(family: int) -> bytes:
        asked.append(family)
        return udp_table(family, tables[family])

    monkeypatch.setattr(forward_module, "FORWARD_IS_UDP_TABLE", True)
    monkeypatch.setattr(win32, "udp_table", read)
    NoSockets.made = []
    monkeypatch.setattr(socket, "socket", NoSockets)
    return tables, asked


@pytest.mark.parametrize(
    "family, address",
    [
        (win32.WIN_AF_INET, IPV4_ANY),
        (win32.WIN_AF_INET6, "::"),
        (win32.WIN_AF_INET, "192.168.10.5"),
        (win32.WIN_AF_INET, "127.0.0.1"),
        (win32.WIN_AF_INET6, "fe80::1"),
    ],
)
def test_a_udp_port_held_on_any_address_is_not_free_on_windows(
    windows_udp, family, address
):
    tables, _asked = windows_udp
    tables[family].append((address, 5353))

    assert is_udp_port_free(5353) is False
    assert is_port_free(5353, protocol="udp") is False
    assert NoSockets.made == []


def test_a_udp_port_nobody_holds_is_free_on_windows_and_both_tables_are_read(
    windows_udp,
):
    tables, asked = windows_udp
    tables[win32.WIN_AF_INET].append((IPV4_ANY, 5354))
    tables[win32.WIN_AF_INET6].append(("::", 5355))

    assert is_udp_port_free(5353) is True
    assert asked == [win32.WIN_AF_INET, win32.WIN_AF_INET6]
    assert NoSockets.made == []


def test_a_udp_table_that_cannot_be_read_holds_every_port(windows_udp, monkeypatch):
    def refuse(family: int) -> bytes:
        raise OSError("GetExtendedUdpTable: refused")

    monkeypatch.setattr(win32, "udp_table", refuse)

    assert is_udp_port_free(5353) is False
    assert is_udp_port_free(70000) is False
    assert NoSockets.made == []


def test_the_udp_tables_rows_are_read_with_their_addresses():
    v4 = udp_table(win32.WIN_AF_INET, [(IPV4_ANY, 5353), ("10.1.2.3", 53)])
    v6 = udp_table(win32.WIN_AF_INET6, [("::", 5353), ("fe80::1", 546)])

    assert win32.udp_table_endpoints(v4, win32.WIN_AF_INET) == [
        (IPV4_ANY, 5353),
        ("10.1.2.3", 53),
    ]
    assert win32.udp_table_endpoints(v6, win32.WIN_AF_INET6) == [
        ("::", 5353),
        ("fe80::1", 546),
    ]
    with pytest.raises(ValueError):
        win32.udp_table_endpoints(v4[:-1], win32.WIN_AF_INET)


def test_only_windows_reads_the_udp_table():
    assert forward_module.FORWARD_IS_UDP_TABLE is (sys.platform == "win32")
