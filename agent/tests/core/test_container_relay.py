"""The relays a container reaches the agent's loopback listeners through.

What these pin: the gateway port a state names is read only as a port; a
relay listens on its address bound to its interface where the address has
an index, and carries each connection to ``127.0.0.1`` on the same port,
both ways, with one side's end passed on to the other; the relays follow the
addresses and the listeners, one per address and port, a bridge made again
under a new index has its relay closed and opened again, and a port that
cannot be had is one line in the log and tried again; the firewall is given
the relays' rules at the first pass, when the relays change, when its last
try failed and at the recheck while rules are held, and left alone while
there is no relay and none was found; a stop closes every relay and takes
the rules away. Nothing here leaves loopback.
"""

import socket
import threading
import time

import pytest

from neutrino_agent.core.container_relay import (
    ContainerRelay,
    ContainerRelays,
    gateway_port_of,
    open_listener,
)
from neutrino_agent.platforms.base import AgentPlatform, RelayAddress, RelayRule

RELAY_HOST = "127.0.0.2"


def loopback_index() -> int:
    """The index of the loopback interface on this machine."""
    return socket.if_nametoindex("lo")


def loopback_relay_address() -> RelayAddress:
    """A relay address on loopback, bound to ``lo`` as a bridge's would be."""
    return RelayAddress(
        interface="lo", index=loopback_index(), address=RELAY_HOST, prefix=8
    )


class EchoServer:
    """A listener on ``127.0.0.1`` that answers each connection with a line, then echoes."""

    def __init__(self):
        self.listener = socket.create_server(("127.0.0.1", 0))
        self.port = self.listener.getsockname()[1]
        self.peers: list = []
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        while True:
            try:
                client, address = self.listener.accept()
            except OSError:
                return
            self.peers.append(address)
            threading.Thread(target=self._echo, args=(client,), daemon=True).start()

    @staticmethod
    def _echo(client):
        with client:
            client.sendall(b"hello\n")
            while True:
                data = client.recv(1024)
                if not data:
                    break
                client.sendall(data)

    def close(self):
        self.listener.close()


@pytest.fixture
def echo():
    server = EchoServer()
    yield server
    server.close()


def read_until(connection, size, timeout_s=3.0):
    """Read until ``size`` bytes or the end."""
    connection.settimeout(timeout_s)
    received = b""
    while len(received) < size:
        chunk = connection.recv(size - len(received))
        if not chunk:
            break
        received += chunk
    return received


# --- the gateway port ---


@pytest.mark.parametrize(
    ("document", "port"),
    [
        ({"ai_tools": {"gateway_port": 8317}}, 8317),
        ({"ai_tools": {"gateway_port": 0}}, 0),
        ({"ai_tools": {"gateway_port": "8317"}}, 0),
        ({"ai_tools": {"gateway_port": True}}, 0),
        ({"ai_tools": {"gateway_port": 70000}}, 0),
        ({"ai_tools": {}}, 0),
        ({"ai_tools": None}, 0),
        ({}, 0),
        (None, 0),
    ],
)
def test_the_gateway_port_is_read_only_as_a_port(document, port):
    assert gateway_port_of(document) == port


# --- one relay ---


def test_a_relay_is_bound_to_its_interface_where_the_address_has_an_index(echo):
    listener = open_listener(loopback_relay_address(), echo.port)
    try:
        bound = listener.getsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, 16)
        address = listener.getsockname()
    finally:
        listener.close()

    assert bound.rstrip(b"\0") == b"lo"
    assert address == (RELAY_HOST, echo.port)


def test_a_relay_with_no_index_is_bound_to_no_interface(echo):
    listener = open_listener(
        RelayAddress(
            interface="vEthernet (WSL)", index=0, address=RELAY_HOST, prefix=0
        ),
        echo.port,
    )
    try:
        bound = listener.getsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, 16)
    finally:
        listener.close()

    assert bound.rstrip(b"\0") == b""


def test_a_relay_carries_a_connection_to_loopback_on_the_same_port_both_ways(echo):
    relay = ContainerRelay(
        listener=open_listener(loopback_relay_address(), echo.port), port=echo.port
    )
    relay.start()
    try:
        with socket.create_connection((RELAY_HOST, echo.port), timeout=3) as tool:
            greeting = read_until(tool, 6)
            tool.sendall(b"ping")
            answer = read_until(tool, 4)
    finally:
        relay.close()

    assert greeting == b"hello\n"
    assert answer == b"ping"
    assert echo.peers[0][0] == "127.0.0.1"


def test_the_end_of_one_side_reaches_the_other(echo):
    relay = ContainerRelay(
        listener=open_listener(loopback_relay_address(), echo.port), port=echo.port
    )
    relay.start()
    try:
        with socket.create_connection((RELAY_HOST, echo.port), timeout=3) as tool:
            read_until(tool, 6)
            tool.sendall(b"last")
            tool.shutdown(socket.SHUT_WR)
            rest = read_until(tool, 1024)
    finally:
        relay.close()

    assert rest == b"last"


def test_a_target_that_does_not_answer_closes_the_connection():
    holder = socket.create_server(("127.0.0.1", 0))
    port = holder.getsockname()[1]
    holder.close()
    relay = ContainerRelay(
        listener=open_listener(loopback_relay_address(), port), port=port
    )
    relay.start()
    try:
        with socket.create_connection((RELAY_HOST, port), timeout=3) as tool:
            rest = read_until(tool, 1024)
    finally:
        relay.close()

    assert rest == b""


def test_closing_a_relay_ends_the_connections_it_carries(echo):
    relay = ContainerRelay(
        listener=open_listener(loopback_relay_address(), echo.port), port=echo.port
    )
    relay.start()
    with socket.create_connection((RELAY_HOST, echo.port), timeout=3) as tool:
        read_until(tool, 6)
        relay.close()
        rest = read_until(tool, 1024)

    assert rest == b""
    with pytest.raises(OSError):
        socket.create_connection((RELAY_HOST, echo.port), timeout=1).close()


# --- the relays together ---


class RelayPlatform(AgentPlatform):
    """Addresses and firewall answers as each test sets them; every sync recorded."""

    os_name = "linux"

    def __init__(self, addresses=()):
        self.addresses = list(addresses)
        self.synced: list = []
        self.error = None
        self.changes: list = []

    def read_relay_addresses(self):
        return list(self.addresses)

    def sync_relay_rules(self, rules):
        self.synced.append(rules)
        if self.error is not None:
            raise self.error
        return list(self.changes)


class FakeRelay:
    """A relay that records its start and close."""

    def __init__(self, *, listener, port):
        self.listener = listener
        self.port = port
        self.is_started = False
        self.is_closed = False

    def start(self):
        self.is_started = True

    def close(self):
        self.is_closed = True


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


PODMAN1 = RelayAddress(interface="podman1", index=6, address="10.89.0.1", prefix=24)
PODMAN1_AGAIN = RelayAddress(
    interface="podman1", index=10, address="10.89.0.1", prefix=24
)
CNI0 = RelayAddress(interface="cni-podman0", index=4, address="10.88.0.1", prefix=16)


def relays_with(platform, ports, *, listen=None, log=None):
    opened = []
    made = []
    lines = [] if log is None else log

    def fake_listen(address, port):
        opened.append((address, port))
        return object()

    def factory(*, listener, port):
        relay = FakeRelay(listener=listener, port=port)
        made.append(relay)
        return relay

    clock = Clock()
    relays = ContainerRelays(
        platform=platform,
        ports=lambda: set(ports),
        log=lines.append,
        recheck_s=60,
        clock=clock,
        listen=listen or fake_listen,
        relay_factory=factory,
    )
    return relays, opened, made, clock


def test_one_relay_opens_per_address_and_listener_port():
    platform = RelayPlatform([PODMAN1, CNI0])
    relays, opened, made, _ = relays_with(platform, {8317, 3101})

    relays.sync()

    assert relays.relays == {
        ("podman1", 6, "10.89.0.1", 8317),
        ("podman1", 6, "10.89.0.1", 3101),
        ("cni-podman0", 4, "10.88.0.1", 8317),
        ("cni-podman0", 4, "10.88.0.1", 3101),
    }
    assert all(relay.is_started for relay in made)
    assert sorted((address.interface, port) for address, port in opened) == [
        ("cni-podman0", 3101),
        ("cni-podman0", 8317),
        ("podman1", 3101),
        ("podman1", 8317),
    ]


def test_a_listener_that_closes_closes_its_relays():
    platform = RelayPlatform([PODMAN1])
    ports = {8317, 3101}
    relays, _, made, _ = relays_with(platform, ports)
    relays.sync()

    ports.discard(3101)
    relays._ports = lambda: set(ports)
    relays.sync()

    assert relays.relays == {("podman1", 6, "10.89.0.1", 8317)}
    assert [relay.port for relay in made if relay.is_closed] == [3101]


def test_a_bridge_made_again_under_a_new_index_has_its_relay_opened_again():
    platform = RelayPlatform([PODMAN1])
    relays, opened, made, _ = relays_with(platform, {8317})
    relays.sync()

    platform.addresses = [PODMAN1_AGAIN]
    relays.sync()

    assert relays.relays == {("podman1", 10, "10.89.0.1", 8317)}
    assert made[0].is_closed and not made[1].is_closed
    assert [address.index for address, _port in opened] == [6, 10]


def test_a_bridge_that_goes_closes_its_relays_and_nothing_is_open_without_one():
    platform = RelayPlatform([PODMAN1])
    relays, _, made, _ = relays_with(platform, {8317})
    relays.sync()

    platform.addresses = []
    relays.sync()

    assert relays.relays == set()
    assert made[0].is_closed


def test_no_listener_opens_no_relay():
    platform = RelayPlatform([PODMAN1])
    relays, opened, _, _ = relays_with(platform, set())

    relays.sync()

    assert relays.relays == set()
    assert opened == []


def test_a_port_that_cannot_be_had_is_one_line_and_tried_again():
    platform = RelayPlatform([PODMAN1])
    attempts = []

    def refusing(address, port):
        attempts.append(port)
        raise OSError(98, "Address already in use")

    lines = []
    relays, _, _, _ = relays_with(platform, {8317}, listen=refusing, log=lines)

    relays.sync()
    relays.sync()

    assert attempts == [8317, 8317]
    assert relays.relays == set()
    assert [line for line in lines if "not opened" in line] == [
        "relay 10.89.0.1:8317 on podman1 not opened: [Errno 98] Address already in use"
    ]


def test_the_first_pass_hands_the_firewall_no_rule_so_a_crash_s_rules_go():
    platform = RelayPlatform([])
    relays, _, _, _ = relays_with(platform, {8317})

    relays.sync()

    assert platform.synced == [frozenset()]


def test_the_firewall_is_given_each_relay_s_rule_when_the_relays_change():
    platform = RelayPlatform([PODMAN1])
    relays, _, _, _ = relays_with(platform, {8317})

    relays.sync()
    relays.sync()

    assert platform.synced == [
        frozenset(
            {RelayRule(interface="podman1", address="10.89.0.1", prefix=24, port=8317)}
        )
    ]


def test_the_firewall_is_read_again_at_the_recheck_while_rules_are_held():
    platform = RelayPlatform([PODMAN1])
    relays, _, _, clock = relays_with(platform, {8317})
    relays.sync()

    clock.now += 59
    relays.sync()
    clock.now += 1
    relays.sync()

    assert len(platform.synced) == 2


def test_with_no_relay_and_no_rule_the_firewall_is_left_alone():
    platform = RelayPlatform([])
    relays, _, _, clock = relays_with(platform, {8317})
    relays.sync()

    clock.now += 3600
    relays.sync()

    assert platform.synced == [frozenset()]


def test_a_firewall_that_fails_is_one_line_and_tried_again_at_the_recheck():
    platform = RelayPlatform([])
    platform.error = OSError("ufw did not answer")
    lines = []
    relays, _, _, clock = relays_with(platform, {8317}, log=lines)

    relays.sync()
    relays.sync()
    clock.now += 60
    relays.sync()

    assert len(platform.synced) == 2
    assert lines == [
        "relays: the firewall rules were not set: ufw did not answer",
    ]


def test_what_the_firewall_changed_is_logged():
    platform = RelayPlatform([PODMAN1])
    platform.changes = ["added ufw rule: allow in on podman1 to 10.89.0.1 port 8317"]
    lines = []
    relays, _, _, _ = relays_with(platform, {8317}, log=lines)

    relays.sync()

    assert "relays: added ufw rule: allow in on podman1 to 10.89.0.1 port 8317" in (
        lines
    )


def test_a_stop_closes_every_relay_and_takes_the_rules_away():
    platform = RelayPlatform([PODMAN1])
    relays, _, made, _ = relays_with(platform, {8317})
    relays.sync()

    relays.stop()

    assert relays.relays == set()
    assert made[0].is_closed
    assert platform.synced[-1] == frozenset()


def test_the_relays_follow_the_listeners_on_a_thread_of_their_own(echo):
    platform = RelayPlatform([loopback_relay_address()])
    relays = ContainerRelays(
        platform=platform, ports=lambda: {echo.port}, log=lambda line: None
    )

    relays.start()
    try:
        deadline = time.monotonic() + 3
        while not relays.relays and time.monotonic() < deadline:
            time.sleep(0.01)
        with socket.create_connection((RELAY_HOST, echo.port), timeout=3) as tool:
            greeting = read_until(tool, 6)
    finally:
        relays.stop()

    assert greeting == b"hello\n"
    assert platform.synced[0] == frozenset(
        {RelayRule(interface="lo", address=RELAY_HOST, prefix=8, port=echo.port)}
    )
    assert platform.synced[-1] == frozenset()
