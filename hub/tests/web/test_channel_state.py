"""The two state documents, and the pushes that hand them down.

An agent's state is the composed desired state under its hash; a client's
is the published list resolved for its scope with the switch, hashed over
both, so two clients from two scopes hold two hashes over one fingerprint.
A push from the panel goes to the one binding named; a push after the
list moved goes to every live client whose hash differs, and to none whose
copy already agrees.
"""

import asyncio

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
from neutrino_hub.modules.services.collector import resolve_entries
from neutrino_hub.modules.services.host_scope import HostScope, link_scope
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
    "device_id": "",
}
LAN = HostScope(
    id="192.168.100.0/24", cidr="192.168.100.0/24", hub_address="192.168.100.1"
)
OVERLAY = HostScope(id="overlay", cidr="100.64.0.0/16", hub_address="100.64.0.1")


class StubPublishedServices:
    """One list, resolved for whatever scope is asked, under one fingerprint."""

    def __init__(self):
        self.entries = [ENTRY]
        self.scopes: list = []

    def entries_for(self, scope):
        self.scopes.append(scope)
        return resolve_entries(
            self.entries,
            device_hosts={},
            hub_addresses={"192.168.100.1"},
            hub_host=scope.hub_address,
        )


class FakeRuntime:
    def __init__(self):
        self.agent_sessions = FakeChannelSessions(online=[DEVICE])
        self.client_sessions = ChannelSessionRegistry(CHANNEL_ROLE_CLIENT)
        self.client_scope: dict = {}
        self.published_services = StubPublishedServices()
        self.desired = (
            "h9",
            {"modules": {"samba": {"want": "running"}}, "desktop": {}},
        )

    def host_scopes(self):
        return [LAN, OVERLAY]

    def desired_state_for(self, device):
        return self.desired


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def hub_urls(monkeypatch) -> list:
    """The addresses the hub answers the channel on; a test may move them."""
    urls = ["https://192.168.100.1:8443"]
    monkeypatch.setattr(channel_state, "channel_urls", lambda runtime: list(urls))
    return urls


def test_an_agents_state_is_the_composed_document_under_its_hash():
    runtime = FakeRuntime()

    assert channel_state.agent_state(runtime, DEVICE) == {
        "hash": "h9",
        "modules": {"samba": {"want": "running"}},
        "desktop": {},
    }


def test_a_clients_state_is_the_list_for_its_scope_and_the_switch(config_dir):
    runtime = FakeRuntime()
    client_id = ClientRegistry().create("alice")
    runtime.client_scope[client_id] = LAN

    state = channel_state.client_state(runtime, client_id)

    assert state["is_disabled"] is False
    assert [entry["id"] for entry in state["services"]] == ["web_gitea"]
    assert "record_id" not in state["services"][0]
    assert len(state["hash"]) == 16
    assert runtime.published_services.scopes == [LAN]


def test_two_clients_from_two_scopes_get_two_hosts_and_two_hashes(config_dir):
    """The fingerprint is one; the hash is over the list each client sees."""
    runtime = FakeRuntime()
    registry = ClientRegistry()
    on_lan = registry.create("lan")
    on_overlay = registry.create("overlay")
    runtime.client_scope[on_lan] = LAN
    runtime.client_scope[on_overlay] = OVERLAY

    lan_state = channel_state.client_state(runtime, on_lan)
    overlay_state = channel_state.client_state(runtime, on_overlay)

    assert lan_state["services"][0]["payload"] == {"url": "http://192.168.100.1:3000"}
    assert overlay_state["services"][0]["payload"] == {"url": "http://100.64.0.1:3000"}
    assert lan_state["hash"] != overlay_state["hash"]
    assert channel_state.client_state(runtime, on_lan)["hash"] == lan_state["hash"]


def test_a_client_whose_scope_was_never_settled_is_handed_the_composed_list(
    config_dir,
):
    runtime = FakeRuntime()
    client_id = ClientRegistry().create("alice")

    state = channel_state.client_state(runtime, client_id)

    assert state["services"][0]["payload"] == {"url": "http://192.168.100.1:3000"}
    assert runtime.published_services.scopes == [link_scope("")]


def test_a_clients_scope_is_settled_from_its_peer_and_kept(config_dir):
    runtime = FakeRuntime()
    client_id = ClientRegistry().create("alice")

    on_lan = channel_state.note_client_scope(
        runtime, client_id, peer_host="192.168.100.9", reached_host="192.168.100.1"
    )
    assert on_lan == LAN and runtime.client_scope[client_id] == LAN

    elsewhere = channel_state.note_client_scope(
        runtime, client_id, peer_host="203.0.113.5", reached_host="198.51.100.2"
    )
    assert elsewhere == link_scope("198.51.100.2")
    assert runtime.client_scope[client_id] == elsewhere


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
    runtime.client_scope[client_id] = LAN
    first = channel_state.client_state(runtime, client_id)["hash"]
    again = channel_state.client_state(runtime, client_id)["hash"]
    runtime.published_services.entries = []

    moved = channel_state.client_state(runtime, client_id)["hash"]

    assert first == again
    assert moved != first


def test_a_clients_state_names_every_address_the_hub_answers_on(config_dir, hub_urls):
    """The set rides inside the hashed body, so a client whose copy is
    stale reports a hash the hub answers with the state."""
    runtime = FakeRuntime()
    client_id = ClientRegistry().create("alice")
    runtime.client_scope[client_id] = LAN
    first = channel_state.client_state(runtime, client_id)

    hub_urls.append("https://100.64.0.1:8443")
    moved = channel_state.client_state(runtime, client_id)

    assert first["urls"] == ["https://192.168.100.1:8443"]
    assert moved["urls"] == ["https://192.168.100.1:8443", "https://100.64.0.1:8443"]
    assert moved["hash"] != first["hash"]


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
        # The scope is settled afresh from the socket's peer: on the served
        # network, so the list is resolved for the network's own address.
        assert runtime.client_scope[stale_id] == LAN
        assert pushed["services"][0]["payload"] == {"url": "http://192.168.100.1:3000"}

    asyncio.run(scenario())
