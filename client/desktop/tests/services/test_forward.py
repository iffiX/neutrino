"""The local forwards: listeners the transport holds, at the numbers the table gives.

Pinned here: an app entry forwards at the hub's ``local_port`` or the
person's own number, never moved, refused ``port_taken`` when another
program or another entry of the same protocol holds it, or when the
transport cannot bind it; a forward of no app picks from 20000 to 23999 and
keeps the pick, picked again when another program took it; ``forward_start``
names the hub's binding, the loopback address, the protocol and the
``connect`` open, the panel's by ``is_panel``; ``forward_stop`` names the
address and the protocol; a ``forward_end`` with a code ends the forward and
says why; every forward starts again when the transport is back; and the
probe that says whether a number is free on every address.
"""

import functools
import socket
import struct
import sys

import pytest

import neutrino_client.services.forward as forward_module
from neutrino_client.exceptions import GatewayUnreachable, LocalPortTakenError
from neutrino_client.platforms import win32
from neutrino_client.services.forward import (
    ConnectStreamSocket,
    ForwardListenerRegistry,
    PortLocalTable,
    is_port_free,
)
from neutrino_client.services.store import ClientServiceStore
from tests.conftest import FakeStreamEnd, FakeTransportChannel, discard


def free_port() -> int:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def _is_free(busy, port, is_kept=False, protocol="tcp") -> bool:
    return port not in busy


def table_on(tmp_path, busy=()):
    """A table kept in a store file, every port free but the busy ones."""
    store = ClientServiceStore(path=str(tmp_path / "state.json"))
    return PortLocalTable(store=store, is_free=functools.partial(_is_free, set(busy)))


class Registry:
    """A registry over an in-process transport, and what it told."""

    def __init__(self, tmp_path, busy=(), bindings=None):
        self.transport = FakeTransportChannel()
        self.refusals = []
        self.changes = 0
        self.table = table_on(tmp_path, busy)
        held = {"h1": "c1", "h2": "c2"} if bindings is None else bindings
        self.forwards = ForwardListenerRegistry(
            command=self.transport.command,
            binding_of=functools.partial(dict.get, held),
            ports=self.table,
            log=discard,
            on_change=self._changed,
            on_refused=self._refused,
        )

    def _changed(self):
        self.changes += 1

    def _refused(self, hub_id, entry_id, refusal):
        self.refusals.append((hub_id, entry_id, refusal))


@pytest.fixture
def registry(tmp_path):
    return Registry(tmp_path)


# --- the forwards ---


def test_an_app_entry_forwards_at_the_hubs_number_through_the_transport(registry):
    port = registry.forwards.ensure(
        hub_id="h1", entry_id="gitea_d1_web", kind="web", own_port=25001
    )

    assert port == 25001
    assert registry.transport.commands == [
        (
            "forward_start",
            {
                "binding": "c1",
                "listen": "127.0.0.1:25001",
                "protocol": "tcp",
                "open": {"kind": "connect", "id": "gitea_d1_web"},
            },
        )
    ]
    assert registry.forwards.forwards() == {"h1/gitea_d1_web": 25001}
    assert registry.forwards.port_of("h1", "gitea_d1_web") == 25001


def test_a_second_ensure_keeps_the_running_forward(registry):
    registry.forwards.ensure(hub_id="h1", entry_id="e", kind="port", own_port=25002)
    registry.forwards.ensure(hub_id="h1", entry_id="e", kind="port", own_port=25002)

    assert len(registry.transport.commands_of("forward_start")) == 1


def test_the_persons_number_replaces_the_hubs(registry):
    registry.table.set_own("h1/e", 30001, "tcp")

    assert (
        registry.forwards.ensure(hub_id="h1", entry_id="e", kind="port", own_port=25003)
        == 30001
    )


def test_a_udp_entry_forwards_on_its_protocol(registry):
    registry.forwards.ensure(
        hub_id="h1", entry_id="dns", kind="port", own_port=25053, protocol="udp"
    )

    (start,) = registry.transport.commands_of("forward_start")
    assert (start["listen"], start["protocol"]) == ("127.0.0.1:25053", "udp")


def test_a_number_another_program_holds_is_refused_and_never_moved(tmp_path):
    made = Registry(tmp_path, busy={25004})

    with pytest.raises(LocalPortTakenError) as caught:
        made.forwards.ensure(hub_id="h1", entry_id="e", kind="web", own_port=25004)

    assert caught.value.port == 25004
    assert made.transport.commands == []


def test_a_number_another_entry_forwards_on_is_refused(registry):
    registry.forwards.ensure(hub_id="h1", entry_id="a", kind="port", own_port=25005)

    with pytest.raises(LocalPortTakenError):
        registry.forwards.ensure(hub_id="h1", entry_id="b", kind="port", own_port=25005)


def test_a_tcp_and_a_udp_entry_hold_one_number(registry):
    registry.forwards.ensure(hub_id="h1", entry_id="a", kind="port", own_port=25006)

    assert (
        registry.forwards.ensure(
            hub_id="h1", entry_id="b", kind="port", own_port=25006, protocol="udp"
        )
        == 25006
    )


def test_a_number_the_transport_cannot_bind_is_port_taken(registry):
    registry.transport.answers["forward_start"] = lambda fields: {
        "code": "port_taken",
        "params": {"port": 25007},
    }

    with pytest.raises(LocalPortTakenError):
        registry.forwards.ensure(hub_id="h1", entry_id="e", kind="web", own_port=25007)
    assert registry.forwards.forwards() == {}


def test_any_other_refusal_of_the_transport_is_an_os_error(registry):
    registry.transport.answers["forward_start"] = lambda fields: {"code": "x"}

    with pytest.raises(OSError):
        registry.forwards.ensure(hub_id="h1", entry_id="e", kind="web", own_port=25008)


def test_a_hub_not_joined_forwards_nothing(tmp_path):
    made = Registry(tmp_path, bindings={})

    with pytest.raises(GatewayUnreachable):
        made.forwards.ensure(hub_id="h9", entry_id="e", kind="web", own_port=25009)


def test_a_transport_that_is_not_running_forwards_nothing(registry):
    registry.transport.is_running = False

    with pytest.raises(GatewayUnreachable):
        registry.forwards.ensure(hub_id="h1", entry_id="e", kind="web", own_port=25010)


def test_a_forward_of_no_app_picks_from_20000_and_keeps_the_pick(tmp_path):
    made = Registry(tmp_path, busy={20000})

    assert made.forwards.ensure(hub_id="h1", entry_id="ai", kind="ai") == 20001
    made.forwards.stop("h1", "ai")
    assert made.forwards.ensure(hub_id="h1", entry_id="ai", kind="ai") == 20001
    assert made.table.setting("h1/ai") == "auto"


def test_the_panel_forward_opens_the_panel(registry):
    registry.forwards.ensure(hub_id="h1", entry_id=":panel", kind="panel")

    (start,) = registry.transport.commands_of("forward_start")
    assert start["open"] == {"kind": "connect", "is_panel": True}
    assert 20000 <= int(start["listen"].rsplit(":", 1)[1]) <= 23999


def test_stop_names_the_address_and_the_protocol(registry):
    registry.forwards.ensure(
        hub_id="h1", entry_id="dns", kind="port", own_port=25011, protocol="udp"
    )

    assert registry.forwards.stop("h1", "dns") is True
    assert registry.forwards.stop("h1", "dns") is False
    assert registry.transport.commands_of("forward_stop") == [
        {"listen": "127.0.0.1:25011", "protocol": "udp"}
    ]


def test_a_forward_end_with_a_code_ends_the_forward_and_says_why(registry):
    registry.forwards.ensure(
        hub_id="h1", entry_id="dns", kind="port", own_port=25012, protocol="udp"
    )

    registry.forwards.take_end(
        {
            "listen": "127.0.0.1:25012",
            "protocol": "udp",
            "code": "agent_offline",
            "params": {"device": "lab"},
        }
    )

    assert registry.forwards.forwards() == {}
    assert registry.refusals == [
        ("h1", "dns", {"code": "agent_offline", "params": {"device": "lab"}})
    ]


def test_a_forward_end_of_another_protocol_ends_nothing(registry):
    registry.forwards.ensure(hub_id="h1", entry_id="a", kind="port", own_port=25013)

    registry.forwards.take_end(
        {"listen": "127.0.0.1:25013", "protocol": "udp", "code": "x"}
    )

    assert registry.forwards.forwards() == {"h1/a": 25013}


def test_every_forward_starts_again_when_the_transport_is_back(registry):
    registry.forwards.ensure(hub_id="h1", entry_id="a", kind="port", own_port=25014)
    registry.forwards.ensure(hub_id="h2", entry_id="b", kind="web", own_port=25015)
    registry.transport.commands.clear()

    registry.forwards.restart()

    assert [
        fields["listen"] for fields in registry.transport.commands_of("forward_start")
    ] == [
        "127.0.0.1:25014",
        "127.0.0.1:25015",
    ]


def test_a_forward_that_cannot_start_again_ends_with_its_refusal(registry):
    registry.forwards.ensure(hub_id="h1", entry_id="a", kind="port", own_port=25016)
    registry.transport.answers["forward_start"] = lambda fields: {
        "code": "port_taken",
        "params": {"port": 25016},
    }

    registry.forwards.restart()

    assert registry.forwards.forwards() == {}
    assert registry.refusals == [
        ("h1", "a", {"code": "port_taken", "params": {"port": 25016}})
    ]


def test_release_hub_ends_only_that_hubs_forwards_the_panel_among_them(registry):
    registry.forwards.ensure(hub_id="h1", entry_id="a", kind="port", own_port=25017)
    registry.forwards.ensure(hub_id="h1", entry_id=":panel", kind="panel")
    registry.forwards.ensure(hub_id="h2", entry_id="b", kind="port", own_port=25018)

    assert registry.forwards.release_hub("h1") == 2
    assert list(registry.forwards.forwards()) == ["h2/b"]


def test_an_entry_gone_from_the_list_ends_its_app_forwards_alone(registry):
    registry.forwards.ensure(hub_id="h1", entry_id="web", kind="web", own_port=25019)
    registry.forwards.ensure(hub_id="h1", entry_id="ssh", kind="ssh", own_port=25020)
    registry.forwards.ensure(hub_id="h1", entry_id="rdp", kind="rdp")

    ended = registry.forwards.drop_withdrawn(hub_id="h1", entries=[{"id": "web"}])

    assert ended == 1
    assert sorted(registry.forwards.forwards()) == ["h1/rdp", "h1/web"]


def test_release_kind_ends_one_kind_of_one_hub(registry):
    registry.forwards.ensure(hub_id="h1", entry_id="r", kind="rdp")
    registry.forwards.ensure(hub_id="h2", entry_id="r", kind="rdp")

    assert registry.forwards.release_kind("rdp", "h1") == 1
    assert list(registry.forwards.forwards()) == ["h2/r"]


# --- the table ---


def test_the_table_asks_whether_a_port_is_free_on_every_address():
    assert PortLocalTable()._is_free is is_port_free


def test_an_app_entry_takes_the_persons_number_else_the_hubs(tmp_path):
    table = table_on(tmp_path)

    assert table.app_port("h1/e", 25001) == 25001
    table.set_own("h1/e", 30000, "tcp")
    assert table.app_port("h1/e", 25001) == 30000
    table.set_own("h1/e", None, "tcp")
    assert table.app_port("h1/e", 25001) == 25001
    assert table.setting("h1/e") is None


@pytest.mark.parametrize("port", [1023, 65536, "x", True, 3.5])
def test_a_number_out_of_range_or_of_another_shape_is_refused(tmp_path, port):
    assert table_on(tmp_path).check_own("h1/e", port, "tcp", {}) == {
        "code": "local_port_invalid",
        "params": {"port": port},
    }


def test_a_number_another_entry_holds_in_the_table_is_refused(tmp_path):
    table = table_on(tmp_path)
    table.set_own("h1/a", 30000, "tcp")

    assert table.check_own("h1/b", 30000, "tcp", {}) == {
        "code": "port_taken",
        "params": {"port": 30000},
    }
    assert table.check_own("h1/b", 30000, "udp", {}) == {}
    assert table.check_own("h1/b", 30000, "tcp", {}, ignored=("h1/a",)) == {}


def test_a_number_another_entry_has_as_its_hub_number_is_refused(tmp_path):
    table = table_on(tmp_path)
    hub_numbers = {"h1/a": (25001, "tcp"), "h1/c": (25002, "udp")}

    assert table.check_own("h1/b", 25001, "tcp", hub_numbers)["code"] == "port_taken"
    assert table.check_own("h1/b", 25002, "tcp", hub_numbers) == {}
    table.set_own("h1/a", 30000, "tcp")
    assert table.check_own("h1/b", 25001, "tcp", hub_numbers) == {}


def test_a_kept_pick_another_program_took_is_picked_again_and_kept(tmp_path):
    path = tmp_path / "state.json"
    path.write_text('{"local_ports": {"h1/ai": {"setting": "auto", "port": 20000}}}')
    table = PortLocalTable(
        store=ClientServiceStore(path=str(path)),
        is_free=functools.partial(_is_free, {20000}),
    )

    assert table.take_auto("h1/ai") == 20001
    assert ClientServiceStore(path=str(path)).local_ports()["h1/ai"]["port"] == 20001


def test_two_picks_never_share_a_number_of_one_protocol(tmp_path):
    table = table_on(tmp_path)

    assert table.take_auto("h1/a") == 20000
    assert table.take_auto("h1/b") == 20001
    assert table.take_auto("h1/c", "udp") == 20000


def test_a_range_with_no_free_port_is_an_os_error(tmp_path):
    table = table_on(tmp_path, busy=set(range(20000, 24000)))

    with pytest.raises(OSError):
        table.take_auto("h1/a")


# --- the socket face of a connect stream ---


def test_the_socket_face_sends_and_receives_in_the_sizes_asked():
    stream = FakeStreamEnd(pieces=[b"abcdef"])
    face = ConnectStreamSocket(stream)

    assert face.recv(4) == b"abcd"
    assert face.recv(4) == b"ef"
    face.sendall(b"up")
    assert stream.sent == [b"up"]
    face.close()
    assert face.recv(4) == b""


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


def test_the_udp_probe_binds_udp_sockets_on_the_wildcard():
    held = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    held.bind(("0.0.0.0", 0))  # scan: allow
    port = held.getsockname()[1]

    assert is_port_free(port, protocol="udp") is False
    assert is_port_free(port) is True
    held.close()
    assert is_port_free(port, protocol="udp") is True


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

    assert is_port_free(5353, protocol="udp") is False
    assert NoSockets.made == []


def test_a_udp_port_nobody_holds_is_free_on_windows_and_both_tables_are_read(
    windows_udp,
):
    tables, asked = windows_udp
    tables[win32.WIN_AF_INET].append((IPV4_ANY, 5354))
    tables[win32.WIN_AF_INET6].append(("::", 5355))

    assert is_port_free(5353, protocol="udp") is True
    assert asked == [win32.WIN_AF_INET, win32.WIN_AF_INET6]
    assert NoSockets.made == []


def test_a_udp_table_that_cannot_be_read_holds_every_port(windows_udp, monkeypatch):
    def refuse(family: int) -> bytes:
        raise OSError("GetExtendedUdpTable: refused")

    monkeypatch.setattr(win32, "udp_table", refuse)

    assert is_port_free(5353, protocol="udp") is False
    assert is_port_free(70000, protocol="udp") is False
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
