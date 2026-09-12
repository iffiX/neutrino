"""When a node has been probed, and what "no answer" is allowed to mean.

Three states share one shape here and must not share one rendering: a node
nobody has probed yet, a node that is switched off and therefore never probed,
and a node that was probed and did not answer. The last is the only failure.
"""

import socket
import struct
import time

from neutrino_hub.modules.xray import node_probe
from neutrino_hub.modules.xray.constants import XRAY_EGRESS_MARK
from neutrino_hub.modules.xray.node_config import XrayNodeConfig
from neutrino_hub.modules.xray.node_probe import XrayNodeProbe

NODE = XrayNodeConfig(
    id="one",
    name="one",
    address="203.0.113.10",
    is_enabled=True,
    protocol="shadowsocks",
    port=5800,
)


def test_the_first_read_probes_however_young_the_machine_is(monkeypatch):
    """`time.monotonic` counts from boot on Linux, so a panel that starts
    early in one used to be younger than the cache's own age and never probe
    at all: every node read unreachable until uptime passed the window."""
    probe = XrayNodeProbe()
    monkeypatch.setattr(time, "monotonic", lambda: 3.0)
    probed: list = []
    monkeypatch.setattr(
        XrayNodeProbe, "refresh", lambda self, nodes: probed.append(nodes) or []
    )

    probe.results([NODE])

    assert probed == [[NODE]]


def test_a_second_read_inside_the_window_does_not_probe_again(monkeypatch):
    probe = XrayNodeProbe()
    monkeypatch.setattr(
        XrayNodeProbe,
        "refresh",
        lambda self, nodes: setattr(probe, "_probed_at", time.monotonic()),
    )
    probe.results([NODE])
    probed: list = []
    monkeypatch.setattr(
        XrayNodeProbe, "refresh", lambda self, nodes: probed.append(nodes)
    )

    probe.results([NODE])

    assert probed == []


class _RecordingSocket:
    """A socket that records what was set on it and connects to nothing."""

    def __init__(self, *arguments):
        self.options: list = []
        self.connected: list = []

    def setsockopt(self, level, option, value) -> None:
        self.options.append((level, option, value))

    def settimeout(self, timeout_s) -> None:
        self.timeout_s = timeout_s

    def connect(self, address) -> None:
        self.connected.append(address)

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *arguments) -> None:
        self.close()


def test_a_probe_leaves_under_the_egress_mark(monkeypatch):
    """A box proxying its own traffic diverts an unmarked probe into its own
    TPROXY socket: the handshake completes locally in no time at all, so every
    node reads alive at 0 ms whatever the node is doing. The mark is the same
    exemption xray stamps on its own outbound sockets."""
    opened: list = []

    def build(*arguments):
        connection = _RecordingSocket(*arguments)
        opened.append(connection)
        return connection

    monkeypatch.setattr(node_probe.socket, "socket", build)
    monkeypatch.setattr(
        node_probe.socket,
        "getaddrinfo",
        lambda address, port, **keywords: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))
        ],
    )

    XrayNodeProbe().probe(NODE)

    assert opened[0].options == [(socket.SOL_SOCKET, socket.SO_MARK, XRAY_EGRESS_MARK)]
    assert opened[0].connected == [("203.0.113.10", 5800)]


def test_a_probe_without_the_privilege_to_mark_still_probes(monkeypatch):
    """The mark needs CAP_NET_ADMIN, which the panel has and a developer
    running this by hand may not."""

    class _Refusing(_RecordingSocket):
        def setsockopt(self, level, option, value) -> None:
            raise PermissionError("no CAP_NET_ADMIN here")

    monkeypatch.setattr(node_probe.socket, "socket", lambda *arguments: _Refusing())
    monkeypatch.setattr(
        node_probe.socket,
        "getaddrinfo",
        lambda address, port, **keywords: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))
        ],
    )

    result = XrayNodeProbe().probe(NODE)

    assert result.is_alive


def test_the_delay_is_the_connect_and_not_the_lookup(monkeypatch):
    """The name is resolved before the clock starts, at the direct resolver."""
    clock = iter([0.0, 0.5, 1.0, 1.07])
    monkeypatch.setattr(node_probe.time, "monotonic", lambda: next(clock))
    asked: list = []

    def slow_lookup(name, *, server, port=53, timeout_s=0):
        asked.append((name, server, port))
        next(clock)
        next(clock)
        return "203.0.113.10"

    monkeypatch.setattr(node_probe, "resolve_direct", slow_lookup)
    monkeypatch.setattr(
        node_probe.socket, "socket", lambda *arguments: _RecordingSocket()
    )
    named = XrayNodeConfig(
        id="two",
        name="two",
        address="exit.example.net",
        is_enabled=True,
        protocol="shadowsocks",
        port=5800,
    )

    result = XrayNodeProbe(resolver_of=lambda: ("223.5.5.5", 53)).probe(named)

    assert asked == [("exit.example.net", "223.5.5.5", 53)]
    assert result.delay_ms == 70


def test_a_name_is_never_asked_of_the_machines_own_resolver(monkeypatch):
    """That resolver is the proxy on a box proxying its own names, and a
    probe of an exit that waits on the exit measures nothing."""
    monkeypatch.setattr(
        node_probe.socket,
        "getaddrinfo",
        lambda *arguments, **keywords: (_ for _ in ()).throw(AssertionError("asked")),
    )
    named = XrayNodeConfig(
        id="two",
        name="two",
        address="exit.example.net",
        is_enabled=True,
        protocol="shadowsocks",
        port=5800,
    )

    result = XrayNodeProbe().probe(named)

    assert result.is_alive is False


def test_a_dns_answer_yields_its_first_a_record():
    """A CNAME ahead of the address is skipped; the answer's names are
    compression pointers back into the question."""
    header = struct.pack("!HHHHHH", 7, 0x8180, 1, 2, 0, 0)
    question = b"\x04exit\x07example\x03net\x00" + struct.pack("!HH", 1, 1)
    cname = b"\xc0\x0c" + struct.pack("!HHIH", 5, 1, 60, 2) + b"\xc0\x0c"
    a_record = (
        b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, 60, 4) + bytes([203, 0, 113, 10])
    )

    assert node_probe._first_a_record(header + question + cname + a_record) == (
        "203.0.113.10"
    )
    assert node_probe._first_a_record(header + question) is None
