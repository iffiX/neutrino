"""The window's control connection, against a live control server.

The fd channel speaks the one handed-over connection for its whole session:
requests ride it one after another, the kernel-read peer scopes every
answer, and a connection that stops answering is dead for good — never
redialed, because a redial would be a fresh peer with the window's own
identity instead of the opener's.
"""

import socket

import pytest

from neutrino_agent.control import client
from neutrino_agent.control.server import ControlServer
from neutrino_agent.gui.channel import GuiFdChannel, GuiPipeChannel
from tests.conftest import ALICE, FakeControlAgent, FakeControlPlatform


@pytest.fixture(scope="module")
def channel_stack(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("gui_channel")
    platform = FakeControlPlatform()
    server = ControlServer(
        agent=FakeControlAgent(),
        platform=platform,
        log=lambda message: None,
        socket_path=str(tmp / "agent.sock"),
    )
    server.start()
    assert server.socket_path
    yield server, platform
    server.stop()


def connected_channel(server) -> GuiFdChannel:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(server.socket_path)
    return GuiFdChannel(sock=sock)


def test_one_connection_answers_request_after_request(channel_stack):
    server, platform = channel_stack
    platform.peer = dict(ALICE)
    channel = connected_channel(server)

    status, first = channel.request(method="GET", path="/api/state")
    _status, refused = channel.request(method="POST", path="/api/disconnect", body={})
    status_again, second = channel.request(method="GET", path="/api/state")

    assert (status, status_again) == (200, 200)
    assert first["caller"]["account"] == "alice"
    assert refused["code"] == "control_scope_refused"
    assert second["caller"]["account"] == "alice"


def test_the_channel_rebuilds_from_a_bare_descriptor(channel_stack):
    # The handover passes a file descriptor number, not a socket object.
    server, platform = channel_stack
    platform.peer = dict(ALICE)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(server.socket_path)
    inherited = socket.socket(fileno=sock.detach())
    channel = GuiFdChannel(sock=inherited)

    status, state = channel.request(method="GET", path="/api/state")

    assert status == 200
    assert state["caller"]["account"] == "alice"


def test_a_dead_connection_raises_and_stays_dead():
    ours, theirs = socket.socketpair()
    channel = GuiFdChannel(sock=ours)
    theirs.close()

    with pytest.raises(OSError):
        channel.request(method="GET", path="/api/state")
    with pytest.raises(OSError):
        channel.request(method="GET", path="/api/state")


def test_the_pipe_channel_dials_the_pipe_per_request(monkeypatch):
    asked = []

    def fake_request(*, socket_path, method, path, body=None, **kwargs):
        asked.append((socket_path, method, path, body))
        return 200, {"ok": True}

    monkeypatch.setattr(client, "request", fake_request)
    channel = GuiPipeChannel(pipe_name="\\\\.\\pipe\\neutrino_agent_control")

    status, reply = channel.request(method="GET", path="/api/state")
    channel.request(method="POST", path="/api/module", body={"name": "x"})

    assert (status, reply) == (200, {"ok": True})
    assert asked == [
        ("\\\\.\\pipe\\neutrino_agent_control", "GET", "/api/state", None),
        ("\\\\.\\pipe\\neutrino_agent_control", "POST", "/api/module", {"name": "x"}),
    ]
