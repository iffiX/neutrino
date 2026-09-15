"""The two state documents, and the pushes that hand them down.

An agent's state is the composed desired state under its hash; a client's
is the published list resolved for its host with the switch, hashed over
both. A push from the panel goes to the one binding named; a push after
the list moved goes to every live client whose hash differs, and to none
whose copy already agrees.
"""

import asyncio
from types import SimpleNamespace

import pytest

from neutrino_hub.modules.channel.constants import (
    CHANNEL_ROLE_AGENT,
    CHANNEL_ROLE_CLIENT,
)
from neutrino_hub.modules.channel.sessions import (
    ChannelSession,
    ChannelSessionRegistry,
)
from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.web import channel_state
from tests.conftest import FakeChannelSessions
from tests.modules.channel.test_sessions import FakeWebSocket

DEVICE = "device-one"
ENTRY = {
    "id": "web_gitea",
    "type": "web",
    "title": "Gitea",
    "payload": {"url": "http://192.168.100.1:3000"},
    "is_healthy": True,
    "source": "module",
    "description": "",
    "description_code": "gitea_module",
    "description_params": {},
    "record_id": None,
    "detail_code": None,
}


class StubPublishedServices:
    def __init__(self):
        self.entries = [ENTRY]
        self.hosts: list = []

    def entries_for(self, target_host):
        self.hosts.append(target_host)
        return list(self.entries)


class _OneLan:
    """One served network, 192.168.100.0/24, as the host resolver reads it."""

    lan_interfaces = [
        SimpleNamespace(
            lan=SimpleNamespace(address="192.168.100.1", cidr="192.168.100.0/24")
        )
    ]


class FakeRuntime:
    def __init__(self):
        self.agent_sessions = FakeChannelSessions(online=[DEVICE])
        self.client_sessions = ChannelSessionRegistry(CHANNEL_ROLE_CLIENT)
        self.client_catalog_host: dict = {}
        self.published_services = StubPublishedServices()
        self.desired = (
            "h9",
            {"modules": {"samba": {"want": "running"}}, "desktop": {}},
        )

    def network(self):
        return _OneLan()

    def desired_state_for(self, device):
        return self.desired


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    return tmp_path


def test_an_agents_state_is_the_composed_document_under_its_hash():
    runtime = FakeRuntime()

    assert channel_state.agent_state(runtime, DEVICE) == {
        "hash": "h9",
        "modules": {"samba": {"want": "running"}},
        "desktop": {},
    }


def test_a_clients_state_is_the_list_for_its_host_and_the_switch(config_dir):
    runtime = FakeRuntime()
    client_id = ClientRegistry().create("alice")
    runtime.client_catalog_host[client_id] = "192.168.100.1"

    state = channel_state.client_state(runtime, client_id)

    assert state["is_disabled"] is False
    assert [entry["id"] for entry in state["services"]] == ["web_gitea"]
    assert "record_id" not in state["services"][0]
    assert len(state["hash"]) == 16
    assert runtime.published_services.hosts == ["192.168.100.1"]


def test_a_disabled_or_missing_client_is_handed_an_empty_list(config_dir):
    runtime = FakeRuntime()
    client_id = ClientRegistry().create("alice")
    enabled = channel_state.client_state(runtime, client_id)
    ClientRegistry().set_disabled(client_id, True)

    disabled = channel_state.client_state(runtime, client_id)
    missing = channel_state.client_state(runtime, "nobody")

    assert (disabled["is_disabled"], disabled["services"]) == (True, [])
    assert missing["is_disabled"] is True
    assert disabled["hash"] != enabled["hash"]


def test_the_hash_moves_with_the_list_and_with_the_switch(config_dir):
    runtime = FakeRuntime()
    client_id = ClientRegistry().create("alice")
    first = channel_state.client_state(runtime, client_id)["hash"]
    again = channel_state.client_state(runtime, client_id)["hash"]
    runtime.published_services.entries = []

    moved = channel_state.client_state(runtime, client_id)["hash"]

    assert first == again
    assert moved != first


def test_a_push_from_the_panel_hands_one_agent_its_state():
    runtime = FakeRuntime()

    channel_state.push_state(runtime, CHANNEL_ROLE_AGENT, DEVICE)

    assert runtime.agent_sessions.pushes == [
        (
            DEVICE,
            "h9",
            {"hash": "h9", "modules": {"samba": {"want": "running"}}, "desktop": {}},
        )
    ]


def test_push_states_hands_every_client_whose_hash_differs_the_list(config_dir):
    runtime = FakeRuntime()
    registry = ClientRegistry()
    stale_id = registry.create("stale")
    current_id = registry.create("current")

    async def scenario():
        stale_socket, current_socket = FakeWebSocket(), FakeWebSocket()
        for client_id, socket in (
            (stale_id, stale_socket),
            (current_id, current_socket),
        ):
            await runtime.client_sessions.attach(
                ChannelSession(
                    key=client_id,
                    role=CHANNEL_ROLE_CLIENT,
                    websocket=socket,
                    loop=asyncio.get_running_loop(),
                    address="192.168.100.9",
                )
            )
        current = runtime.client_sessions.get(current_id)
        current.offered_hash = channel_state.client_state(runtime, current_id)["hash"]

        await asyncio.to_thread(channel_state.push_states, runtime, CHANNEL_ROLE_CLIENT)
        for _ in range(10):
            await asyncio.sleep(0)

        (pushed,) = stale_socket.sent("state")
        assert pushed["is_disabled"] is False
        assert [entry["id"] for entry in pushed["services"]] == ["web_gitea"]
        assert current_socket.sent("state") == []
        assert runtime.client_sessions.get(stale_id).offered_hash == pushed["hash"]
        # The host is settled afresh from the socket's peer: on the served
        # network, so the network's own address.
        assert runtime.client_catalog_host[stale_id] == "192.168.100.1"

    asyncio.run(scenario())
