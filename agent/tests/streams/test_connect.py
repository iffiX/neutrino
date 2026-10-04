"""The connect stream: one TCP connection to a port this machine publishes.

What these pin: each kind of published port is in the table while it is
published and gone once it is not; a port outside the table is refused
``port_not_published {port}`` and nothing is dialled; the dial goes to
``127.0.0.1``, or to the one address a container port is published on,
within ``AGENT_CONNECT_DIAL_TIMEOUT_S``; a refused, timed-out or unreachable
dial is ``connect_failed {reason}``; bytes cross both ways, in no faster than
the credit offered and out no faster than the hub's; the socket's end of
file closes the stream empty once what was read is sent, and the hub's
close shuts the socket.
"""

import errno
import socket
import threading
import time

import pytest

from neutrino_agent.constants import (
    AGENT_CONNECT_DIAL_TIMEOUT_S,
    AGENT_WS_STREAM_CREDIT_BYTES,
)
from neutrino_agent.exceptions import StreamRefused
from neutrino_agent.streams.channel import StreamChannel
from neutrino_agent.streams.connect import (
    ConnectStream,
    dial_reason,
    published_ports,
)
from tests.streams.fake_channel import FakeChannel

SAMBA = {"state": "running", "details": {"shares": [{"name": "media"}]}}
GITEA = {"state": "running", "details": {"url": "http://192.168.1.5:3000/"}}
PODMAN = {
    "state": "running",
    "details": {
        "containers": [
            {
                "name": "db",
                "host_bindings": [
                    {"address": "192.168.1.5", "port": 5432},
                    {"address": "", "port": 8080},
                    {"address": "0.0.0.0", "port": 8081},
                ],
            }
        ]
    },
}
EDITORS = {
    name: {"want": "running", "config": {"instances": [{"account": "a", "port": port}]}}
    for name, port in (("vscode", 8000), ("cloudcli", 3001), ("code_server", 8443))
}
DESKTOP = {"is_shared": True, "port": 21118}


def test_every_kind_of_published_port_is_in_the_table():
    ports = published_ports(
        {"samba": SAMBA, "gitea": GITEA, "podman": PODMAN}, EDITORS, DESKTOP
    )

    assert ports == {
        445: "127.0.0.1",
        21118: "127.0.0.1",
        3000: "127.0.0.1",
        8000: "127.0.0.1",
        3001: "127.0.0.1",
        8443: "127.0.0.1",
        5432: "192.168.1.5",
        8080: "127.0.0.1",
        8081: "127.0.0.1",
    }


def test_a_port_leaves_the_table_once_it_is_not_published():
    stopped_sharing = {"is_shared": False, "port": 21118}
    no_shares = {"state": "running", "details": {"shares": []}}
    hand_installed = {"state": "installed", "details": GITEA["details"]}
    withdrawn = {name: dict(entry, want="absent") for name, entry in EDITORS.items()}
    no_containers = {"state": "running", "details": {"containers": []}}

    assert (
        published_ports(
            {"samba": no_shares, "gitea": hand_installed, "podman": no_containers},
            withdrawn,
            stopped_sharing,
        )
        == {}
    )


def test_a_gitea_url_with_no_port_publishes_its_schemes():
    gitea = {"state": "running", "details": {"url": "https://git.example/"}}

    assert published_ports({"gitea": gitea}, {}, {}) == {443: "127.0.0.1"}


class Dials:
    """Records each dial and answers with a connected socket or an error."""

    def __init__(self, answer=None):
        self.asked: list = []
        self.answer = answer

    def __call__(self, address, timeout):
        self.asked.append((address, timeout))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def test_a_port_the_machine_does_not_publish_is_refused_before_any_dial():
    dials = Dials()
    stream = ConnectStream(
        FakeChannel(), {"port": 22}, published=lambda: {445: "127.0.0.1"}, dial=dials
    )

    with pytest.raises(StreamRefused) as refused:
        stream.open()

    assert (refused.value.code, refused.value.params) == (
        "port_not_published",
        {"port": 22},
    )
    assert dials.asked == []


@pytest.mark.parametrize("port", ["445", None, True, 445.0])
def test_a_port_that_is_no_number_is_not_published(port):
    stream = ConnectStream(
        FakeChannel(), {"port": port}, published=lambda: {445: "127.0.0.1"}
    )

    with pytest.raises(StreamRefused) as refused:
        stream.open()

    assert refused.value.code == "port_not_published"


def test_the_dial_goes_to_the_address_the_table_names_within_the_timeout():
    left, right = socket.socketpair()
    try:
        dials = Dials(answer=left)
        ConnectStream(
            FakeChannel(),
            {"port": 5432},
            published=lambda: {5432: "192.168.1.5", 445: "127.0.0.1"},
            dial=dials,
        ).open()
    finally:
        left.close()
        right.close()

    assert dials.asked == [(("192.168.1.5", 5432), AGENT_CONNECT_DIAL_TIMEOUT_S)]


@pytest.mark.parametrize(
    "error, reason",
    [
        (ConnectionRefusedError(errno.ECONNREFUSED, "refused"), "refused"),
        (socket.timeout("timed out"), "timeout"),
        (OSError(errno.ETIMEDOUT, "timed out"), "timeout"),
        (OSError(errno.EHOSTUNREACH, "no route"), "unreachable"),
        (OSError(errno.ENETUNREACH, "no network"), "unreachable"),
    ],
)
def test_a_dial_that_fails_is_connect_failed_with_its_reason(error, reason):
    stream = ConnectStream(
        FakeChannel(),
        {"port": 445},
        published=lambda: {445: "127.0.0.1"},
        dial=Dials(answer=error),
    )

    with pytest.raises(StreamRefused) as refused:
        stream.open()

    assert (refused.value.code, refused.value.params) == (
        "connect_failed",
        {"reason": reason},
    )
    assert dial_reason(error) == reason


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_a_real_dial_to_a_closed_port_is_refused():
    port = free_port()
    stream = ConnectStream(
        FakeChannel(), {"port": port}, published=lambda: {port: "127.0.0.1"}
    )

    with pytest.raises(StreamRefused) as refused:
        stream.open()

    assert refused.value.params == {"reason": "refused"}


class Listener:
    """A loopback service: answers what it reads, then does what it is told."""

    def __init__(self, *, is_closing_after_answer: bool):
        self.server = socket.socket()
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(1)
        self.port = self.server.getsockname()[1]
        self.received = b""
        self.saw_end = threading.Event()
        self._is_closing = is_closing_after_answer
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        connection, _ = self.server.accept()
        with connection:
            data = connection.recv(4)
            self.received += data
            connection.sendall(data.upper())
            if self._is_closing:
                return
            while True:
                more = connection.recv(1024)
                if not more:
                    self.saw_end.set()
                    return
                self.received += more

    def close(self):
        self.server.close()


def test_bytes_cross_both_ways_and_the_sockets_end_closes_the_stream():
    listener = Listener(is_closing_after_answer=True)
    channel = FakeChannel()
    channel.feed(("data", b"ping"))
    try:
        stream = ConnectStream(
            channel,
            {"port": listener.port},
            published=lambda: {listener.port: "127.0.0.1"},
        )
        stream.open()
        result = stream.run()
    finally:
        listener.close()

    assert result == {"code": "", "params": {}}
    assert listener.received == b"ping"
    assert channel.output() == b"PING"
    assert channel.credits == [AGENT_WS_STREAM_CREDIT_BYTES, 4]


def test_the_hubs_close_shuts_the_socket():
    listener = Listener(is_closing_after_answer=False)
    channel = FakeChannel()
    channel.feed(("data", b"ping"))
    try:
        stream = ConnectStream(
            channel,
            {"port": listener.port},
            published=lambda: {listener.port: "127.0.0.1"},
        )
        stream.open()
        runner = threading.Thread(target=stream.run, daemon=True)
        runner.start()
        deadline = time.monotonic() + 5
        while channel.output() != b"PING" and time.monotonic() < deadline:
            time.sleep(0.01)
        channel.feed(("data", b"more"))
        channel.close_from_hub()
        runner.join(timeout=5)
    finally:
        listener.close()

    assert listener.saw_end.wait(timeout=5)
    assert listener.received == b"pingmore"
    assert not runner.is_alive()


class RecordingSession:
    """The session under a real stream channel: every frame it would send."""

    def __init__(self):
        self.frames: list = []

    def _send_bytes(self, stream_id, data):
        self.frames.append(bytes(data))

    def _send(self, message):
        self.frames.append(dict(message))

    def _close_stream(self, stream_id, code, params):
        self.frames.append({"type": "close", "code": code, "params": params})


def test_the_services_bytes_go_up_only_as_the_hubs_credit_allows():
    listener = Listener(is_closing_after_answer=True)
    session = RecordingSession()
    channel = StreamChannel(session, 2, credit=0)
    channel._feed(("data", b"ping"))
    try:
        stream = ConnectStream(
            channel,
            {"port": listener.port},
            published=lambda: {listener.port: "127.0.0.1"},
        )
        stream.open()
        runner = threading.Thread(target=stream.run, daemon=True)
        runner.start()
        time.sleep(0.2)
        before = [frame for frame in session.frames if isinstance(frame, bytes)]
        channel._grant(2)
        time.sleep(0.2)
        partway = [frame for frame in session.frames if isinstance(frame, bytes)]
        channel._grant(10)
        runner.join(timeout=5)
    finally:
        listener.close()

    assert before == []
    assert partway == [b"PI"]
    assert b"".join(f for f in session.frames if isinstance(f, bytes)) == b"PING"
