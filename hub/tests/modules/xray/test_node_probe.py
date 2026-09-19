"""What one measurement of a node is, and what it must never blame the node for.

Three failures share one shape here and must not share one reading: a node that
did not answer, a probe inbound that refused the measurement before it left the
box, and a name that does not resolve. Only the first is the node's.
"""

import socket
import struct

import pytest

from neutrino_hub.modules.xray import node_probe
from neutrino_hub.modules.xray.constants import (
    XRAY_EGRESS_MARK,
    XRAY_PROBE_PASSWORD,
    XRAY_PROBE_PORT,
)
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
NAMED_NODE = XrayNodeConfig(
    id="two",
    name="two",
    address="exit.example.net",
    is_enabled=True,
    protocol="shadowsocks",
    port=5800,
)
PROBE_URL = "http://probe.example.net/generate_204"
# The probe inbound granting the account, the node granting the connection,
# and the target answering.
SOCKS_GRANTED = b"\x05\x02" + b"\x01\x00" + b"\x05\x00\x00\x01" + bytes(6)
ANSWER_204 = b"HTTP/1.1 204 No Content\r\n\r\n"


class _Clock:
    """A monotonic clock a test steps by hand."""

    def __init__(self, *, step_s: float = 0.0):
        self.now = 0.0
        self._step_s = step_s

    def __call__(self) -> float:
        value = self.now
        self.now += self._step_s
        return value

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _ScriptedSocket:
    """A socket that records what was set and sent, and reads from a script."""

    def __init__(
        self,
        *,
        answer: bytes = b"",
        clock: "_Clock | None" = None,
        connect_cost_s: float = 0.0,
        reply_cost_s: float = 0.0,
        is_refused: bool = False,
    ):
        self.options: list = []
        self.timeouts: list = []
        self.connected: list = []
        self.sent = b""
        self.is_closed = False
        self._answer = answer
        self._clock = clock
        self._connect_cost_s = connect_cost_s
        self._reply_cost_s = reply_cost_s
        self._is_refused = is_refused
        self._is_first_read = True

    def setsockopt(self, level, option, value) -> None:
        self.options.append((level, option, value))

    def settimeout(self, timeout_s) -> None:
        self.timeouts.append(timeout_s)

    def connect(self, address) -> None:
        self.connected.append(address)
        if self._clock is not None:
            self._clock.advance(self._connect_cost_s)
        if self._is_refused:
            raise ConnectionRefusedError("nothing is listening there")

    def sendall(self, payload: bytes) -> None:
        self.sent += payload

    def recv(self, count: int) -> bytes:
        if self._clock is not None and self._is_first_read:
            self._clock.advance(self._reply_cost_s)
            self._is_first_read = False
        piece, self._answer = self._answer[:count], self._answer[count:]
        return piece

    def close(self) -> None:
        self.is_closed = True

    def __enter__(self):
        return self

    def __exit__(self, *arguments) -> None:
        self.close()


class _Dialer:
    """Hands out the sockets a probe opens, in the order it opens them."""

    def __init__(self, *sockets: _ScriptedSocket):
        self.opened: list = []
        self._queue = list(sockets)

    def __call__(self, *arguments) -> _ScriptedSocket:
        connection = self._queue.pop(0) if self._queue else _ScriptedSocket()
        self.opened.append(connection)
        return connection


@pytest.fixture
def dialer(monkeypatch):
    """Install a socket factory a test fills; it answers `socket.socket`."""

    def install(*sockets: _ScriptedSocket) -> _Dialer:
        built = _Dialer(*sockets)
        monkeypatch.setattr(node_probe.socket, "socket", built)
        return built

    return install


def test_the_socks_handshake_names_the_node_and_the_host(dialer):
    """The account name is the node's outbound tag, which is what the probe
    rule matches, and the host goes out as a domain so the exit resolves it."""
    node_socket = _ScriptedSocket()
    channel = _ScriptedSocket(answer=SOCKS_GRANTED + ANSWER_204)
    dialer(node_socket, channel)

    measurement = XrayNodeProbe().probe(NODE, url=PROBE_URL)

    assert channel.connected == [("127.0.0.1", XRAY_PROBE_PORT)]
    tag = b"node_one"
    password = XRAY_PROBE_PASSWORD.encode()
    host = b"probe.example.net"
    assert channel.sent == (
        b"\x05\x01\x02"
        + bytes([1, len(tag)])
        + tag
        + bytes([len(password)])
        + password
        + bytes([5, 1, 0, 3, len(host)])
        + host
        + struct.pack("!H", 80)
        + b"GET /generate_204 HTTP/1.1\r\n"
        + b"Host: probe.example.net\r\n"
        + b"User-Agent: neutrino-hub\r\n"
        + b"Connection: close\r\n\r\n"
    )
    assert measurement.is_success
    assert measurement.is_xray_reachable


def test_the_loopback_hop_is_not_charged_to_the_node(dialer, monkeypatch):
    """The connect to the probe inbound is microseconds on a box that is well,
    and seconds on one that is not; neither is the node's."""
    clock = _Clock()
    monkeypatch.setattr(node_probe.time, "monotonic", clock)
    node_socket = _ScriptedSocket(clock=clock, connect_cost_s=0.125)
    channel = _ScriptedSocket(
        answer=SOCKS_GRANTED + ANSWER_204,
        clock=clock,
        connect_cost_s=0.5,
        reply_cost_s=0.25,
    )
    dialer(node_socket, channel)

    measurement = XrayNodeProbe().probe(NODE, url=PROBE_URL)

    assert measurement.connect_ms == 125
    assert measurement.request_ms == 250


def test_one_deadline_covers_every_phase(dialer, monkeypatch):
    """Each phase gets what is left of the one timeout, not a timeout of its
    own: five phases with five seconds each is a twenty-five second probe."""
    clock = _Clock(step_s=2.0)
    monkeypatch.setattr(node_probe.time, "monotonic", clock)
    channel = _ScriptedSocket(answer=SOCKS_GRANTED + ANSWER_204)
    dialer(channel)

    measurement = XrayNodeProbe(timeout_s=5.0).probe(NAMED_NODE, url=PROBE_URL)

    assert channel.timeouts == [5.0, 3.0, 1.0]
    assert measurement.request_ms is None
    assert measurement.is_xray_reachable
    assert b"GET" not in channel.sent


def test_a_refused_probe_inbound_is_not_the_nodes_failure(dialer):
    """xray restarting refuses every measurement at once. Blaming the nodes
    for it would take the exit off a node that is answering fine."""
    node_socket = _ScriptedSocket()
    channel = _ScriptedSocket(is_refused=True)
    dialer(node_socket, channel)

    measurement = XrayNodeProbe().probe(NODE, url=PROBE_URL)

    assert measurement.is_xray_reachable is False
    assert measurement.request_ms is None
    assert measurement.connect_ms is not None


def test_a_status_the_server_refused_is_a_failed_measurement(dialer):
    node_socket = _ScriptedSocket()
    channel = _ScriptedSocket(
        answer=SOCKS_GRANTED + b"HTTP/1.1 502 Bad Gateway\r\n\r\n"
    )
    dialer(node_socket, channel)

    measurement = XrayNodeProbe().probe(NODE, url=PROBE_URL)

    assert measurement.is_success is False
    assert measurement.is_xray_reachable


def test_an_account_the_inbound_refuses_is_a_failed_measurement(dialer):
    node_socket = _ScriptedSocket()
    channel = _ScriptedSocket(answer=b"\x05\x02" + b"\x01\x01")
    dialer(node_socket, channel)

    measurement = XrayNodeProbe().probe(NODE, url=PROBE_URL)

    assert measurement.is_success is False
    assert measurement.is_xray_reachable


def test_a_probed_request_never_verifies_tls(dialer, monkeypatch):
    """A fault in this box's CA store would otherwise read as every exit dying
    at once while the direct reference stayed green."""
    wrapped: list = []

    def wrap(connection, host):
        wrapped.append(host)
        return connection

    monkeypatch.setattr(node_probe, "_tls_wrapped", wrap)
    node_socket = _ScriptedSocket()
    channel = _ScriptedSocket(answer=SOCKS_GRANTED + ANSWER_204)
    dialer(node_socket, channel)

    XrayNodeProbe().probe(NODE, url="https://probe.example.net/generate_204")

    assert wrapped == ["probe.example.net"]
    assert b"Host: probe.example.net\r\n" in channel.sent


def test_the_unverified_context_checks_no_name_and_no_chain(monkeypatch):
    class _Context:
        """An SSL context that records what the probe asked of it."""

        def __init__(self, protocol=None):
            self.check_hostname = True
            self.verify_mode = None
            self.wrapped: list = []

        def wrap_socket(self, connection, server_hostname):
            self.wrapped.append(server_hostname)
            return connection

    built = _Context()
    monkeypatch.setattr(node_probe.ssl, "SSLContext", lambda protocol: built)

    node_probe._tls_wrapped(object(), "probe.example.net")

    assert built.check_hostname is False
    assert built.verify_mode == node_probe.ssl.CERT_NONE
    assert built.wrapped == ["probe.example.net"]


def test_the_probe_leaves_under_the_egress_mark_and_the_loopback_does_not(dialer):
    """A box proxying its own traffic diverts an unmarked probe into its own
    TPROXY socket: the handshake completes locally in no time at all, so every
    node reads alive at 0 ms whatever the node is doing. The loopback hop needs
    no mark, because the output chain returns on the reserved address set."""
    node_socket = _ScriptedSocket()
    channel = _ScriptedSocket(answer=SOCKS_GRANTED + ANSWER_204)
    dialer(node_socket, channel)

    XrayNodeProbe().probe(NODE, url=PROBE_URL)

    assert node_socket.options == [
        (socket.SOL_SOCKET, socket.SO_MARK, XRAY_EGRESS_MARK)
    ]
    assert node_socket.connected == [("203.0.113.10", 5800)]
    assert channel.options == []


def test_the_reference_goes_out_marked_and_past_xray(dialer):
    """A reference that rode xray could not tell an uplink that is down from an
    xray that is down, and it has to answer while xray is restarting."""
    uplink = _ScriptedSocket(answer=ANSWER_204)
    dialer(uplink)

    reference_ms = XrayNodeProbe().probe_reference("http://203.0.113.9/connecttest")

    assert reference_ms is not None
    assert uplink.options == [(socket.SOL_SOCKET, socket.SO_MARK, XRAY_EGRESS_MARK)]
    assert uplink.connected == [("203.0.113.9", 80)]
    assert uplink.sent.startswith(b"GET /connecttest HTTP/1.1\r\n")


def test_a_reference_that_does_not_answer_reads_as_an_uplink_that_is_down(dialer):
    dialer(_ScriptedSocket(is_refused=True))

    assert XrayNodeProbe().probe_reference("http://203.0.113.9/connecttest") is None


def test_a_probe_without_the_privilege_to_mark_still_probes(dialer):
    """The mark needs CAP_NET_ADMIN, which the panel has and a developer
    running this by hand may not."""

    class _Refusing(_ScriptedSocket):
        def setsockopt(self, level, option, value) -> None:
            raise PermissionError("no CAP_NET_ADMIN here")

    node_socket = _Refusing()
    channel = _ScriptedSocket(answer=SOCKS_GRANTED + ANSWER_204)
    dialer(node_socket, channel)

    measurement = XrayNodeProbe().probe(NODE, url=PROBE_URL)

    assert measurement.connect_ms is not None
    assert measurement.is_success


def test_a_name_is_resolved_at_the_direct_resolver_before_the_clock_starts(
    dialer, monkeypatch
):
    """The lookup is not the node's latency, and the machine's own resolver is
    the proxy on a box proxying its own names."""
    clock = _Clock()
    monkeypatch.setattr(node_probe.time, "monotonic", clock)
    asked: list = []

    def slow_lookup(name, *, server, port=53, timeout_s=0):
        asked.append((name, server, port))
        clock.advance(0.5)
        return "203.0.113.10"

    monkeypatch.setattr(node_probe, "resolve_direct", slow_lookup)
    node_socket = _ScriptedSocket(clock=clock, connect_cost_s=0.125)
    dialer(node_socket, _ScriptedSocket(is_refused=True))

    measurement = XrayNodeProbe(resolver_of=lambda: ("223.5.5.5", 53)).probe(
        NAMED_NODE, url=PROBE_URL
    )

    assert asked == [("exit.example.net", "223.5.5.5", 53)]
    assert measurement.connect_ms == 125


def test_a_name_is_never_asked_of_the_machines_own_resolver(dialer, monkeypatch):
    """That resolver is the proxy on a box proxying its own names, and a probe
    of an exit that waits on the exit measures nothing."""
    monkeypatch.setattr(
        node_probe.socket,
        "getaddrinfo",
        lambda *arguments, **keywords: (_ for _ in ()).throw(AssertionError("asked")),
    )
    dialer(_ScriptedSocket(is_refused=True))

    measurement = XrayNodeProbe().probe(NAMED_NODE, url=PROBE_URL)

    assert measurement.connect_ms is None


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
