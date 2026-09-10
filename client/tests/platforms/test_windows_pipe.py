"""The named-pipe transport: the same handler set over a scripted pipe.

A fake pipe API stands in for Win32, so a whole HTTP exchange runs through
the real request handler: the request bytes go in as a connected client,
the platform reads the peer from the connection's ``pipe_handle``, and the
JSON answer lands in the fake's write buffer. The pipe's descriptor names
the current user alone.
"""

import io
import json
import threading
import time

from neutrino_client.control.server import ControlServer, _ControlRequestHandler
from neutrino_client.platforms.windows_pipe import (
    ControlPipeHttpServer,
    PipeConnection,
    pipe_security_sddl,
)
from neutrino_client.platforms.base import ClientPlatform
from tests.conftest import FakeClientPlatform, FakeSession, discard

PIPE_NAME = "\\\\.\\pipe\\neutrino_client_test"

STATE_REQUEST = b"GET /api/state HTTP/1.1\r\nHost: pipe\r\nConnection: close\r\n\r\n"


class FakePipeApi:
    """Win32 named pipes as in-memory byte buffers."""

    def __init__(self, requests):
        self.requests = list(requests)
        self.readers = {}
        self.written = {}
        self.created = []
        self.closed = []
        self.disconnected = []
        self.opened_clients = []
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
        self.opened_clients.append(pipe_name)
        self._wake.set()
        return 999

    def read(self, handle, size):
        reader = self.readers.get(handle)
        return reader.read(size) if reader is not None else b""

    def write(self, handle, data):
        self.written.setdefault(handle, bytearray()).extend(data)

    def disconnect(self, handle):
        self.disconnected.append(handle)

    def close(self, handle):
        self.closed.append(handle)


class RecordingPlatform(FakeClientPlatform):
    """The client platform fake, remembering each peer connection."""

    def __init__(self):
        FakeClientPlatform.__init__(self)
        self.peers = []

    def read_peer_identity(self, connection):
        self.peers.append(connection)
        return FakeClientPlatform.read_peer_identity(self, connection)


def serve_one_exchange(api, platform):
    """Run the pipe server over the scripted client until it answers."""
    server = ControlPipeHttpServer(PIPE_NAME, _ControlRequestHandler, api=api)
    server.control_session = FakeSession()
    server.control_platform = platform
    server.control_log = discard
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if any(b"\r\n\r\n" in bytes(body) for body in api.written.values()):
            break
        time.sleep(0.01)
    server.shutdown()
    thread.join(timeout=5)
    server.server_close()
    assert not thread.is_alive()
    return server


def answered_json(api):
    """The one JSON body the fake's write buffers hold."""
    for body in api.written.values():
        raw = bytes(body)
        if b"\r\n\r\n" in raw:
            head, _, payload = raw.partition(b"\r\n\r\n")
            return head.decode("latin-1"), json.loads(payload.decode("utf-8"))
    raise AssertionError("no response landed in the pipe")


def test_the_descriptor_names_the_owner_alone():
    sddl = pipe_security_sddl("S-1-5-21-1-2-3-1001")

    assert sddl == "D:(A;;GA;;;S-1-5-21-1-2-3-1001)"
    assert "WD" not in sddl and "BA" not in sddl


def test_the_first_instance_refuses_a_second_resident():
    api = FakePipeApi([])

    ControlPipeHttpServer(PIPE_NAME, _ControlRequestHandler, api=api)

    assert api.created == [(PIPE_NAME, True)]


def test_the_pipe_serves_the_same_handler_set():
    api = FakePipeApi([STATE_REQUEST])
    platform = RecordingPlatform()

    serve_one_exchange(api, platform)

    head, state = answered_json(api)
    assert head.startswith("HTTP/1.0 200") or head.startswith("HTTP/1.1 200")
    assert state["hostname"] == "box"


def test_another_account_is_refused_over_the_pipe():
    api = FakePipeApi([STATE_REQUEST])
    platform = RecordingPlatform()
    platform.peer = {"account": "bob", "uid": -1, "is_same_user": False}

    serve_one_exchange(api, platform)

    head, reply = answered_json(api)
    assert "403" in head
    assert reply["code"] == "control_peer_refused"


def test_the_platform_reads_the_peer_from_the_pipe_handle():
    api = FakePipeApi([STATE_REQUEST])
    platform = RecordingPlatform()

    serve_one_exchange(api, platform)

    assert len(platform.peers) == 1
    assert platform.peers[0].pipe_handle in api.readers


def test_shutdown_dials_the_pipe_to_wake_the_accept():
    api = FakePipeApi([STATE_REQUEST])

    serve_one_exchange(api, RecordingPlatform())

    assert api.opened_clients == [PIPE_NAME]


def test_a_served_client_is_disconnected_and_closed():
    api = FakePipeApi([STATE_REQUEST])
    platform = RecordingPlatform()

    serve_one_exchange(api, platform)

    handle = platform.peers[0].pipe_handle
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and handle not in api.disconnected:
        time.sleep(0.01)
    assert handle in api.disconnected
    assert handle in api.closed


def test_the_control_server_builds_the_pipe_transport_for_a_pipe_path():
    api = FakePipeApi([])

    class PipePlatform(ClientPlatform):
        def control_socket_path(self):
            return PIPE_NAME

    import neutrino_client.platforms.windows_pipe as windows_pipe

    original = windows_pipe.ControlPipeHttpServer

    class InjectedServer(original):
        def __init__(self, pipe_name, handler_class, **kwargs):
            original.__init__(self, pipe_name, handler_class, api=api)

    windows_pipe.ControlPipeHttpServer = InjectedServer
    try:
        server = ControlServer(
            session=FakeSession(), platform=PipePlatform(), log=discard
        )
        assert server.start()
        assert server.socket_path == PIPE_NAME
        assert api.created
        server.stop()
    finally:
        windows_pipe.ControlPipeHttpServer = original


def test_a_pipe_connection_is_shaped_like_a_socket():
    api = FakePipeApi([])
    api.readers[5] = io.BytesIO(b"hello")
    api.written[5] = bytearray()
    connection = PipeConnection(api=api, handle=5)

    connection.settimeout(10)
    stream = connection.makefile("rb", -1)
    assert stream.read(5) == b"hello"
    assert stream.read(1) == b""

    connection.sendall(b"back")
    assert bytes(api.written[5]) == b"back"

    connection.shutdown(1)
    stream.close()
    connection.close()
    connection.close()
    assert api.disconnected == [5]
    assert api.closed == [5]


def test_a_body_survives_a_connection_close_until_the_reader_closes():
    api = FakePipeApi([])
    api.readers[7] = io.BytesIO(b"the body")
    connection = PipeConnection(api=api, handle=7, is_server_end=False)

    reader = connection.makefile("rb", -1)
    connection.close()

    assert api.closed == []
    assert reader.read() == b"the body"

    reader.close()
    assert api.closed == [7]


def test_a_client_end_close_does_not_disconnect_the_instance():
    api = FakePipeApi([])
    connection = PipeConnection(api=api, handle=9, is_server_end=False)

    connection.close()

    assert api.disconnected == []
    assert api.closed == [9]
