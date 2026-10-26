"""A change on the Clients page closes what it covers at once, through the transport.

What these pin, cause by cause: switching a client off ends its session
with ``client_disabled``; taking a kind closes its streams of that kind on
every machine with ``permission_denied {kind}``; narrowing a kind to some
machines closes the streams on the machines outside the list, one command
per machine; taking ``panel`` closes its forward and ends its panel
sessions; a change to the default reaches only the clients that follow it;
and a change that takes nothing closes nothing.
"""

import pytest

from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.modules.devices.registry import DeviceRegistry
from neutrino_hub.web.client_access import close_lost_access
from tests.conftest import FakeChannelSessions

DEVICE_A = "dev-a"
DEVICE_B = "dev-b"


class PanelSessions:
    def __init__(self):
        self.ended: list = []

    def client_sessions(self):
        return []

    def logout(self, token):
        self.ended.append(token)


class Runtime:
    def __init__(self, online):
        self.client_sessions = FakeChannelSessions(online=online)
        self.sessions = PanelSessions()


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    registry = DeviceRegistry()
    for name, device_id in (("a", DEVICE_A), ("b", DEVICE_B)):
        registry.create(name, machine_id=f"m-{name}")
    return tmp_path


def client_with(kinds=None, devices=None) -> str:
    registry = ClientRegistry()
    client_id = registry.create("laptop")
    if kinds is not None:
        registry.set_permission(client_id, kinds, devices)
    return client_id


def device_ids() -> list:
    return [device.id for device in DeviceRegistry().all_stored()]


def test_switching_a_client_off_ends_its_session(config):
    client_id = client_with()
    ClientRegistry().set_disabled(client_id, True)
    runtime = Runtime(online=[client_id])

    closed = close_lost_access(runtime, why="disabled")

    assert runtime.client_sessions.refused == [(client_id, "client_disabled", {})]
    assert closed == {client_id: {"socket": True}}


def test_taking_a_kind_closes_its_streams_on_every_machine(config):
    client_id = client_with(kinds=["web", "terminal"])
    runtime = Runtime(online=[client_id])

    closed = close_lost_access(runtime, why="permission")

    kinds = [
        (kind, device)
        for _, kind, device, _, _, _ in runtime.client_sessions.stream_closes
    ]
    assert ("port", "") in kinds and ("ssh", "") in kinds and ("rdp", "") in kinds
    assert ("web", "") not in kinds and ("terminal", "") not in kinds
    assert ("panel", "") in kinds
    assert all(
        code == "permission_denied" and params == {"kind": kind}
        for _, kind, _, _, code, params in runtime.client_sessions.stream_closes
    )
    assert closed[client_id]["streams"]


def test_narrowing_a_kind_to_some_machines_closes_the_streams_elsewhere(config):
    ids = device_ids()
    client_id = client_with(kinds=["web"], devices={"web": [ids[0]]})
    runtime = Runtime(online=[client_id])

    close_lost_access(runtime, why="permission")

    web = [
        device
        for _, kind, device, _, _, _ in runtime.client_sessions.stream_closes
        if kind == "web"
    ]
    assert web == [ids[1]]


def test_a_change_to_the_default_reaches_only_its_followers(config):
    follower = client_with()
    own = client_with(kinds=["web"])
    ClientRegistry().set_default_permission(["web", "panel"])
    runtime = Runtime(online=[follower, own])

    close_lost_access(runtime, why="default")

    by_client = {}
    for key, kind, _, _, _, _ in runtime.client_sessions.stream_closes:
        by_client.setdefault(key, set()).add(kind)
    assert "panel" not in by_client[follower]
    assert "panel" in by_client[own]
    assert "web" not in by_client[follower] and "web" not in by_client[own]


def test_a_client_that_lost_nothing_but_the_panel_keeps_everything_else(config):
    client_id = client_with(
        kinds=["web", "port", "ssh", "ai", "file", "rdp", "overlay", "terminal"]
    )
    runtime = Runtime(online=[client_id])

    close_lost_access(runtime, why="permission")

    assert [kind for _, kind, _, _, _, _ in runtime.client_sessions.stream_closes] == [
        "panel"
    ]
