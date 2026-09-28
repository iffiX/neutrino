"""The EasyTier daemon's socket: one JSON line in, one JSON line out.

On Linux and macOS a real Unix socket in a temporary directory, served by
the real server and asked by the real client; on Windows the named pipe,
served over a fake pipe API. Pinned here: the socket is open to every
account, a request reaches the daemon as sent and its answer comes back
whole, an oversized or unreadable request is refused without reaching the
daemon, a daemon that raises answers ``client_internal`` and keeps serving,
a stale socket is replaced, a stop takes the socket away, and the pipe's
descriptor admits interactive users without letting them make an instance.
"""

import io
import json
import os
import socket
import threading
import time

import pytest

from neutrino_client.constants import CLIENT_EASYTIER_REQUEST_LIMIT_BYTES
from neutrino_client.control.easytier_socket import (
    EASYTIER_PIPE_SDDL,
    EasytierSocketServer,
    ask_easytier_daemon,
)
from tests.conftest import discard

PIPE_NAME = "\\\\.\\pipe\\neutrino_client_easytier_test"


class RecordingDaemon:
    """Answers every request with what it was asked, or raises."""

    def __init__(self):
        self.requests = []
        self.error = None

    def handle(self, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return {"networks": [], "console": None, "is_running": False, "echo": request}


@pytest.fixture
def served(tmp_path):
    address = str(tmp_path / "run" / "easytier.sock")
    daemon = RecordingDaemon()
    server = EasytierSocketServer(daemon=daemon, address=address, log=discard)
    server.start()
    yield address, daemon, server
    server.stop()


def test_the_socket_is_open_to_every_account(served):
    address, _daemon, _server = served

    assert os.stat(address).st_mode & 0o777 == 0o666


def test_a_request_crosses_whole_and_its_answer_comes_back(served):
    address, daemon, _server = served
    request = {"verb": "join", "network_secret": "s3cret é"}  # scan: allow

    answer = ask_easytier_daemon(address, request)

    assert daemon.requests == [request]
    assert answer["echo"] == request


def test_each_connection_carries_one_request(served):
    address, daemon, _server = served

    for number in range(3):
        ask_easytier_daemon(address, {"verb": "status", "n": number})

    assert [request["n"] for request in daemon.requests] == [0, 1, 2]


def raw_exchange(address, payload: bytes) -> dict:
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.settimeout(5)
    connection.connect(address)
    try:
        connection.sendall(payload)
        reader = connection.makefile("rb")
        return json.loads(reader.readline().decode("utf-8"))
    finally:
        connection.close()


def test_an_oversized_request_is_refused_before_the_daemon(served):
    address, daemon, _server = served
    payload = (
        b'{"verb": "' + b"x" * (CLIENT_EASYTIER_REQUEST_LIMIT_BYTES + 10) + b'"}\n'
    )

    answer = raw_exchange(address, payload)

    assert answer == {"code": "overlay_request_invalid", "params": {}}
    assert daemon.requests == []


def test_an_unreadable_request_reaches_the_daemon_as_nothing(served):
    address, daemon, _server = served

    raw_exchange(address, b"not json\n")

    assert daemon.requests == [None]


def test_a_daemon_that_raises_answers_internal_and_keeps_serving(served):
    address, daemon, _server = served
    daemon.error = RuntimeError("boom")

    answer = ask_easytier_daemon(address, {"verb": "status"})

    assert answer == {"code": "client_internal", "params": {"kind": "RuntimeError"}}
    daemon.error = None
    assert ask_easytier_daemon(address, {"verb": "status"})["is_running"] is False


def test_a_stale_socket_is_replaced_and_a_stop_takes_it_away(tmp_path):
    address = str(tmp_path / "easytier.sock")
    stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    stale.bind(address)
    stale.close()
    server = EasytierSocketServer(
        daemon=RecordingDaemon(), address=address, log=discard
    )

    server.start()
    assert ask_easytier_daemon(address, {"verb": "status"})["is_running"] is False
    server.stop()

    assert not os.path.exists(address)
    with pytest.raises(OSError):
        ask_easytier_daemon(address, {"verb": "status"}, timeout_s=1)


def test_nothing_listening_is_an_os_error(tmp_path):
    with pytest.raises(OSError):
        ask_easytier_daemon(str(tmp_path / "none.sock"), {"verb": "status"})


# --- the named pipe ---


def test_the_pipe_admits_interactive_users_but_not_as_instance_makers():
    assert EASYTIER_PIPE_SDDL.startswith("D:P")
    assert "(A;;GA;;;SY)" in EASYTIER_PIPE_SDDL
    assert "(A;;GA;;;BA)" in EASYTIER_PIPE_SDDL
    interactive = EASYTIER_PIPE_SDDL.split("(A;;")[-1]
    assert interactive.endswith(";;;IU)")
    rights = int(interactive.split(";")[0], 16)
    file_create_pipe_instance = 0x0004
    assert rights & 0x0001 and rights & 0x0002
    assert not rights & file_create_pipe_instance
    assert ";WD)" not in EASYTIER_PIPE_SDDL and ";BU)" not in EASYTIER_PIPE_SDDL


class FakePipeApi:
    """Win32 named pipes as in-memory buffers, one scripted client each."""

    def __init__(self, requests):
        self.requests = list(requests)
        self.readers = {}
        self.written = {}
        self.created = []
        self.next_handle = 100
        self._wake = threading.Event()

    def create_instance(self, pipe_name, *, is_first=False):
        self.created.append((pipe_name, is_first))
        self.next_handle += 1
        return self.next_handle

    def wait_for_client(self, handle):
        if self.requests:
            self.readers[handle] = io.BytesIO(self.requests.pop(0))
            self.written[handle] = bytearray()
            return True
        self._wake.wait(timeout=5)
        return False

    def open_client(self, pipe_name):
        self._wake.set()
        return 999

    def read(self, handle, size):
        reader = self.readers.get(handle)
        return reader.read(size) if reader is not None else b""

    def write(self, handle, data):
        self.written.setdefault(handle, bytearray()).extend(data)

    def disconnect(self, handle):
        pass

    def close(self, handle):
        pass


def test_the_pipe_serves_one_request_to_the_daemon():
    api = FakePipeApi([b'{"verb": "status"}\n'])
    daemon = RecordingDaemon()
    server = EasytierSocketServer(
        daemon=daemon, address=PIPE_NAME, log=discard, pipe_api=api
    )

    server.start()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not any(
        body.endswith(b"\n") for body in api.written.values()
    ):
        time.sleep(0.01)
    server.stop()

    assert api.created[0] == (PIPE_NAME, True)
    assert daemon.requests == [{"verb": "status"}]
    (body,) = [bytes(body) for body in api.written.values() if body]
    assert json.loads(body.decode("utf-8"))["echo"] == {"verb": "status"}


class FakeClientPipe:
    """The client end of the daemon's pipe: one answer queued."""

    def __init__(self, answer: bytes):
        self.answer = io.BytesIO(answer)
        self.sent = bytearray()
        self.opened = []
        self.closed = []

    def open_client(self, pipe_name):
        self.opened.append(pipe_name)
        return 5

    def read(self, handle, size):
        return self.answer.read(size)

    def write(self, handle, data):
        self.sent.extend(data)

    def disconnect(self, handle):
        pass

    def close(self, handle):
        self.closed.append(handle)


def test_the_client_asks_over_the_pipe_and_closes_it():
    api = FakeClientPipe(b'{"networks": ["home"]}\n')

    answer = ask_easytier_daemon(PIPE_NAME, {"verb": "status"}, pipe_api=api)

    assert answer == {"networks": ["home"]}
    assert api.opened == [PIPE_NAME]
    assert json.loads(bytes(api.sent)) == {"verb": "status"}
    assert api.closed == [5]


def test_an_answer_that_is_no_object_is_a_value_error():
    api = FakeClientPipe(b"[1, 2]\n")

    with pytest.raises(ValueError):
        ask_easytier_daemon(PIPE_NAME, {"verb": "status"}, pipe_api=api)
