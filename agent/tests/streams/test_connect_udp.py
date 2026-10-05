"""The UDP connect stream: every datagram of one UDP entry over one stream.

What these pin, on real UDP sockets on loopback: a number published on TCP
alone is refused ``port_not_published`` and so is any open naming another
protocol; two sources each get their own replies through their own socket;
a datagram the hub's credit does not cover is dropped at once while every
datagram from the hub is granted back; a frame shorter than its source is
dropped and an empty datagram is carried; a source idle for
``AGENT_UDP_IDLE_TIMEOUT_S`` is forgotten and a later datagram gets a new
socket; one source past the limit replaces the idlest; an unreachable port
loses the datagram and keeps the stream; the stream ends with the hub's
close, or ``port_not_published`` once the port is no longer published; and
a first socket that cannot be opened is ``connect_failed``.
"""

import errno
import socket
import struct
import threading
import time

import pytest

from neutrino_agent.constants import AGENT_UDP_IDLE_TIMEOUT_S, AGENT_UDP_SOURCES_MAX
from neutrino_agent.exceptions import StreamRefused
from neutrino_agent.streams import connect_udp
from neutrino_agent.streams.channel import StreamChannel
from neutrino_agent.streams.connect import ConnectStream, published_ports
from neutrino_agent.streams.connect_udp import UdpConnectStream, open_connect_stream

WAIT_S = 5.0


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class RecordingSession:
    """The session a StreamChannel sends through, recording what goes up."""

    def __init__(self):
        self.frames: list = []
        self.credits: list = []
        self.lock = threading.Lock()

    def _send_bytes(self, stream_id, data):
        with self.lock:
            self.frames.append(bytes(data))

    def _send(self, message):
        if message.get("type") == "credit":
            with self.lock:
                self.credits.append(message["bytes"])

    def _close_stream(self, stream_id, code, params):
        pass


class Echo:
    """A UDP service on loopback answering each datagram with ``echo:`` in
    front, and remembering the peers it heard from."""

    def __init__(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(("127.0.0.1", 0))
        self.socket.settimeout(0.2)
        self.port = self.socket.getsockname()[1]
        self.peers: list = []
        self._is_done = threading.Event()
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while not self._is_done.is_set():
            try:
                data, peer = self.socket.recvfrom(65535)
            except OSError:
                continue
            self.peers.append(peer)
            self.socket.sendto(b"echo:" + data, peer)

    def close(self):
        self._is_done.set()
        self.socket.close()


@pytest.fixture
def echo():
    held = Echo()
    yield held
    held.close()


class Running:
    """One UDP stream opened and run on its own thread."""

    def __init__(self, port, *, credit=1 << 20, published=None, clock=None):
        self.session = RecordingSession()
        self.channel = StreamChannel(self.session, 2, credit=credit)
        self.clock = clock or Clock()
        self.ports = {port: "127.0.0.1"}
        self.stream = UdpConnectStream(
            self.channel,
            {"port": port, "protocol": "udp"},
            published=published or self.published,
            clock=self.clock,
        )
        self.stream.open()
        self.result: dict = {}
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def published(self, protocol="tcp"):
        return dict(self.ports) if protocol == "udp" else {}

    def _run(self):
        self.result = self.stream.run()

    def send(self, source: int, datagram: bytes) -> None:
        self.channel._feed(("data", struct.pack(">H", source) + datagram))

    def replies(self) -> list:
        with self.session.lock:
            return [
                (struct.unpack(">H", frame[:2])[0], frame[2:])
                for frame in self.session.frames
            ]

    def close(self):
        self.channel._end()
        self.thread.join(timeout=WAIT_S)


def wait_until(predicate, what):
    deadline = time.monotonic() + WAIT_S
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    pytest.fail(f"timed out waiting for {what}")


def test_the_limits_are_the_hubs():
    assert AGENT_UDP_IDLE_TIMEOUT_S == 60
    assert AGENT_UDP_SOURCES_MAX == 64


def test_two_sources_each_get_their_own_replies(echo):
    running = Running(echo.port)
    try:
        running.send(40001, b"one")
        running.send(40002, b"two")
        wait_until(lambda: len(running.replies()) == 2, "two replies")

        assert sorted(running.replies()) == [
            (40001, b"echo:one"),
            (40002, b"echo:two"),
        ]
        assert len({peer for peer in echo.peers}) == 2
        running.send(40001, b"again")
        wait_until(lambda: len(running.replies()) == 3, "a third reply")
        assert running.replies()[-1] == (40001, b"echo:again")
        assert len(set(echo.peers)) == 2
    finally:
        running.close()
    assert running.result == {"code": "", "params": {}}


def test_a_number_published_on_tcp_alone_is_not_published_on_udp(echo):
    stream = UdpConnectStream(
        StreamChannel(RecordingSession(), 2),
        {"port": echo.port, "protocol": "udp"},
        published=lambda protocol="tcp": (
            {echo.port: "127.0.0.1"} if protocol == "tcp" else {}
        ),
    )

    with pytest.raises(StreamRefused) as refused:
        stream.open()

    assert (refused.value.code, refused.value.params) == (
        "port_not_published",
        {"port": echo.port},
    )


def test_an_open_names_its_protocol_and_none_is_tcp():
    channel = StreamChannel(RecordingSession(), 2)
    published = lambda protocol="tcp": {53: "127.0.0.1"}  # noqa: E731

    assert isinstance(
        open_connect_stream(channel, {"port": 53}, published=published),
        ConnectStream,
    )
    assert isinstance(
        open_connect_stream(
            channel, {"port": 53, "protocol": "udp"}, published=published
        ),
        UdpConnectStream,
    )
    other = open_connect_stream(
        channel, {"port": 53, "protocol": "sctp"}, published=published
    )
    with pytest.raises(StreamRefused) as refused:
        other.open()
    assert refused.value.code == "port_not_published"


def test_what_is_published_is_counted_per_protocol():
    podman = {
        "state": "running",
        "details": {
            "containers": [
                {
                    "host_bindings": [
                        {"address": "", "port": 53, "protocol": "udp"},
                        {"address": "", "port": 53, "protocol": "tcp"},
                        {"address": "192.168.1.5", "port": 5353, "protocol": "udp"},
                        {"address": "", "port": 8080},
                    ]
                }
            ]
        },
    }
    samba = {"state": "running", "details": {"shares": [{"name": "media"}]}}
    modules = {"podman": podman, "samba": samba}
    desktop = {"is_shared": True, "port": 21118}

    assert published_ports(modules, {}, desktop, "udp") == {
        53: "127.0.0.1",
        5353: "192.168.1.5",
    }
    assert published_ports(modules, {}, desktop) == {
        445: "127.0.0.1",
        21118: "127.0.0.1",
        53: "127.0.0.1",
        8080: "127.0.0.1",
    }


def test_a_datagram_the_hubs_credit_does_not_cover_is_dropped_at_once(echo):
    running = Running(echo.port, credit=0)
    try:
        running.send(40001, b"lost")
        wait_until(lambda: len(echo.peers) == 1, "the datagram to reach the port")
        time.sleep(0.3)
        assert running.replies() == []

        running.channel._grant(64)
        running.send(40001, b"kept")
        wait_until(lambda: running.replies() == [(40001, b"echo:kept")], "a reply")
    finally:
        running.close()
    # The window offered at the start, then each frame from the hub granted
    # back, the dropped reply's notwithstanding.
    assert running.session.credits[1:] == [6, 6]


def test_a_short_frame_is_dropped_and_an_empty_datagram_is_carried(echo):
    running = Running(echo.port)
    try:
        running.channel._feed(("data", b"\x01"))
        running.send(40001, b"")
        wait_until(lambda: running.replies() == [(40001, b"echo:")], "a reply")
    finally:
        running.close()
    assert running.session.credits[1:] == [1, 2]
    assert len(echo.peers) == 1


def test_an_idle_source_is_forgotten_and_comes_back_with_a_new_socket(echo):
    running = Running(echo.port)
    try:
        running.send(40001, b"first")
        wait_until(lambda: len(running.replies()) == 1, "the first reply")
        assert running.stream.sources() == [40001]

        running.clock.now += AGENT_UDP_IDLE_TIMEOUT_S - 1
        time.sleep(0.4)
        assert running.stream.sources() == [40001]

        running.clock.now += 1
        wait_until(lambda: running.stream.sources() == [], "the source forgotten")
        running.send(40001, b"second")
        wait_until(lambda: len(running.replies()) == 2, "the second reply")
    finally:
        running.close()
    assert echo.peers[0] != echo.peers[1]


def test_one_source_past_the_limit_replaces_the_idlest(echo, monkeypatch):
    monkeypatch.setattr(connect_udp, "AGENT_UDP_SOURCES_MAX", 3)
    running = Running(echo.port)
    try:
        for count, source in enumerate((40001, 40002, 40003), start=1):
            running.clock.now += 1
            running.send(source, b"x")
            wait_until(lambda: len(running.replies()) == count, "a reply")
        running.clock.now += 1
        running.send(40001, b"y")
        wait_until(lambda: len(running.replies()) == 4, "a reply")

        running.clock.now += 1
        running.send(40004, b"z")
        wait_until(lambda: len(running.replies()) == 5, "a reply")

        assert sorted(running.stream.sources()) == [40001, 40003, 40004]
    finally:
        running.close()


def test_an_unreachable_port_loses_the_datagram_and_keeps_the_stream(echo):
    nobody = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    nobody.bind(("127.0.0.1", 0))
    port = nobody.getsockname()[1]
    nobody.close()
    running = Running(port)
    try:
        running.send(40001, b"nobody home")
        running.send(40001, b"still nobody")
        time.sleep(0.5)
        assert running.thread.is_alive()
        assert running.replies() == []
    finally:
        running.close()
    assert running.result == {"code": "", "params": {}}


def test_the_stream_ends_once_the_port_is_no_longer_published(echo):
    running = Running(echo.port)
    try:
        running.send(40001, b"hello")
        wait_until(lambda: len(running.replies()) == 1, "a reply")
        running.ports.clear()
        running.clock.now += 1
        running.thread.join(timeout=WAIT_S)
    finally:
        running.close()
    assert running.result == {
        "code": "port_not_published",
        "params": {"port": echo.port},
    }


def test_the_stream_has_no_idle_close(echo):
    running = Running(echo.port)
    try:
        running.clock.now += AGENT_UDP_IDLE_TIMEOUT_S * 10
        time.sleep(0.5)
        assert running.thread.is_alive()
    finally:
        running.close()


def test_a_first_socket_that_cannot_be_opened_is_connect_failed(monkeypatch):
    def unreachable(self):
        raise OSError(errno.ENETUNREACH, "Network is unreachable")

    monkeypatch.setattr(UdpConnectStream, "_new_socket", unreachable)
    stream = UdpConnectStream(
        StreamChannel(RecordingSession(), 2),
        {"port": 53, "protocol": "udp"},
        published=lambda protocol="tcp": {53: "127.0.0.1"},
    )

    with pytest.raises(StreamRefused) as refused:
        stream.open()

    assert (refused.value.code, refused.value.params) == (
        "connect_failed",
        {"reason": "unreachable"},
    )
