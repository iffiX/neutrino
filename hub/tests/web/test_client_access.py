"""A change on the Clients page closes what it covers at once.

The Clients routes run as they do in the panel, in a request thread, against
a real client socket registry whose sessions live on a loop of their own.
What these pin, cause by cause: switching a client off closes every stream
it opened with ``client_disabled`` and then its socket; deleting it refuses
its socket; taking ``terminal`` or one of its machines closes the shells on
that machine with ``permission_denied {kind: terminal}``; taking a kind or a
machine closes the ``connect`` streams it covers with ``permission_denied
{kind}``, the panel's forward among them; a change to the default reaches
only the clients that follow it; and everything still allowed stays open.
"""

import asyncio
import json
import threading

import pytest

from neutrino_hub.modules.channel.constants import CHANNEL_ROLE_CLIENT
from neutrino_hub.modules.channel.sessions import (
    ChannelSession,
    ChannelSessionRegistry,
    ChannelStream,
)
from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.modules.devices.registry import DeviceRegistry
from neutrino_hub.web.client_access import close_lost_access
from tests.web.routers.hub.test_client import api  # noqa: F401

DEVICE_A = "dev-a"
DEVICE_B = "dev-b"


class RecordingSocket:
    """A client's websocket: every frame and the close the hub sends."""

    def __init__(self):
        self.frames: list = []
        self.closed_with = None

    async def send_text(self, text: str) -> None:
        self.frames.append(json.loads(text))

    async def send_bytes(self, data: bytes) -> None:
        self.frames.append(bytes(data))

    async def close(self, code: int, reason: str = "") -> None:
        self.closed_with = (code, reason)

    def closes(self) -> dict:
        """Each stream's close, by stream id."""
        return {
            frame["stream"]: (frame["code"], frame["params"])
            for frame in self.frames
            if isinstance(frame, dict) and frame.get("type") == "close"
        }


@pytest.fixture
def loop():
    """The channel's loop, run on a thread of its own as the panel runs it."""
    running = asyncio.new_event_loop()
    thread = threading.Thread(target=running.run_forever, daemon=True)
    thread.start()
    yield running
    running.call_soon_threadsafe(running.stop)
    thread.join(5)
    running.close()


@pytest.fixture
def channel(api, loop):  # noqa: F811
    """The routes, with a real client socket registry on that loop."""
    client, runtime = api
    runtime.client_sessions = ChannelSessionRegistry(CHANNEL_ROLE_CLIENT)
    return client, runtime, loop


def on_loop(loop, coroutine):
    return asyncio.run_coroutine_threadsafe(coroutine, loop).result(5)


def connected(
    runtime, loop, client_id: str, devices: tuple = (DEVICE_A, DEVICE_B)
) -> tuple:
    """A client's live socket with a shell on each machine, a web stream to
    each machine, and the panel's forward."""
    socket = RecordingSocket()
    session = ChannelSession(
        key=client_id, role=CHANNEL_ROLE_CLIENT, websocket=socket, loop=loop
    )

    async def build():
        await runtime.client_sessions.attach(session)
        first, second = devices
        for stream_id, kind, device in (
            (1, "shell", first),
            (3, "shell", second),
            (5, "connect", first),
            (7, "connect", second),
            (9, "connect", ""),
        ):
            session._streams[stream_id] = ChannelStream(session, stream_id, kind, {})
            if kind == "shell":
                session.shells[stream_id] = (device, stream_id + 100, "")
            elif device:
                session.connects[stream_id] = ("web", device)
            else:
                session.connects[stream_id] = ("panel", "")

    on_loop(loop, build())
    return session, socket


def holding_everything(name: str = "laptop") -> str:
    registry = ClientRegistry()
    client_id = registry.create(name)
    registry.set_permission(client_id, ["web", "terminal", "panel"])
    return client_id


def test_switching_a_client_off_closes_every_stream_then_its_socket(channel):
    client, runtime, loop = channel
    client_id = holding_everything()
    session, socket = connected(runtime, loop, client_id)

    client.post("/api/hub/client/disable", json={"client_id": client_id})

    assert socket.closes() == {
        stream_id: ("client_disabled", {}) for stream_id in (1, 3, 5, 7, 9)
    }
    refused = [frame for frame in socket.frames if frame.get("type") == "refused"]
    assert refused == [{"type": "refused", "code": "client_disabled", "params": {}}]
    assert socket.closed_with == (4000, "client_disabled")


def test_deleting_a_client_refuses_its_socket(channel):
    client, runtime, loop = channel
    client_id = holding_everything()
    _, socket = connected(runtime, loop, client_id)

    client.post("/api/hub/client/remove", json={"client_id": client_id})

    assert socket.closed_with == (4000, "binding_unknown")


def test_taking_terminal_closes_every_shell_and_nothing_else(channel):
    client, runtime, loop = channel
    client_id = holding_everything()
    session, socket = connected(runtime, loop, client_id)

    client.post(
        "/api/hub/client/permission/set",
        json={"client_id": client_id, "kinds": ["web", "panel"]},
    )

    assert socket.closes() == {
        1: ("permission_denied", {"kind": "terminal"}),
        3: ("permission_denied", {"kind": "terminal"}),
    }
    assert runtime.client_sessions.is_online(client_id)


def test_taking_a_machine_closes_its_shells_and_streams_and_no_others(channel):
    client, runtime, loop = channel
    first = DeviceRegistry().create("first").id
    second = DeviceRegistry().create("second").id
    client_id = holding_everything()
    _, socket = connected(runtime, loop, client_id, (first, second))

    client.post(
        "/api/hub/client/permission/set",
        json={
            "client_id": client_id,
            "kinds": ["web", "terminal", "panel"],
            "devices": {"web": [second], "terminal": [second]},
        },
    )

    assert socket.closes() == {
        1: ("permission_denied", {"kind": "terminal"}),
        5: ("permission_denied", {"kind": "web"}),
    }


def test_taking_a_kind_closes_its_streams_and_taking_the_panel_its_forward(
    channel,
):
    client, runtime, loop = channel
    client_id = holding_everything()
    signed_in = runtime.sessions.open_for_client(client_id)
    _, socket = connected(runtime, loop, client_id)

    client.post(
        "/api/hub/client/permission/set",
        json={"client_id": client_id, "kinds": ["terminal"]},
    )

    assert socket.closes() == {
        5: ("permission_denied", {"kind": "web"}),
        7: ("permission_denied", {"kind": "web"}),
        9: ("permission_denied", {"kind": "panel"}),
    }
    assert not runtime.sessions.is_valid(signed_in)
    assert runtime.client_sessions.is_online(client_id)


def test_a_change_to_the_default_reaches_only_its_followers(channel):
    client, runtime, loop = channel
    registry = ClientRegistry()
    registry.set_default_permission(["web", "terminal", "panel"])
    follower = registry.create("laptop")
    own = holding_everything("desk")
    _, follower_socket = connected(runtime, loop, follower)
    _, own_socket = connected(runtime, loop, own)

    client.post("/api/hub/client/default_permission/set", json={"kinds": ["web"]})

    assert follower_socket.closes() == {
        1: ("permission_denied", {"kind": "terminal"}),
        3: ("permission_denied", {"kind": "terminal"}),
        9: ("permission_denied", {"kind": "panel"}),
    }
    assert own_socket.closes() == {}


def test_a_change_that_takes_nothing_closes_nothing(channel):
    _, runtime, loop = channel
    client_id = holding_everything()
    _, socket = connected(runtime, loop, client_id)

    assert close_lost_access(runtime, why="permission taken") == {}
    assert socket.closes() == {}
