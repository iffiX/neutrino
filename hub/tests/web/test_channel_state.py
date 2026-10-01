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
from neutrino_hub.modules.clients import services as clients_services
from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.modules.devices.registry import DeviceRegistry
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
        self.device_hostname: dict = {}
        self.device_address: dict = {}
        self.overlays: list = []

    def host_scopes(self):
        return [LAN, OVERLAY]

    def desired_state_for(self, device):
        return self.desired


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def overlay(monkeypatch):
    """The overlays' join material is whatever the runtime holds."""
    monkeypatch.setattr(
        channel_state.channel_overlay,
        "overlay_materials",
        lambda runtime: list(runtime.overlays),
    )


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


def test_a_clients_list_holds_only_the_kinds_it_is_allowed(config_dir):
    runtime = FakeRuntime()
    ai_entry = {**ENTRY, "id": "ai", "type": "ai", "payload": {}}
    runtime.published_services.entries = [ENTRY, ai_entry]
    registry = ClientRegistry()
    client_id = registry.create("alice")
    everything = channel_state.client_state(runtime, client_id)

    registry.set_permission(client_id, ["ai"])
    only_ai = channel_state.client_state(runtime, client_id)
    registry.set_permission(client_id, None)
    registry.set_default_permission(["web"])
    only_web = channel_state.client_state(runtime, client_id)

    assert [entry["id"] for entry in everything["services"]] == ["web_gitea", "ai"]
    assert [entry["id"] for entry in only_ai["services"]] == ["ai"]
    assert [entry["id"] for entry in only_web["services"]] == ["web_gitea"]
    assert len({everything["hash"], only_ai["hash"], only_web["hash"]}) == 3


NETBIRD_OVERLAY = {
    "provider": "netbird",
    "setup_key": "A1B2C3D4-0000-4000-8000-000000000000",  # scan: allow
    "management_url": "",
    "fqdn": "hub.netbird.cloud",
}


def test_a_clients_state_carries_the_overlays_and_a_key_moves_the_hash(config_dir):
    runtime = FakeRuntime()
    client_id = ClientRegistry().create("alice")
    runtime.overlays = [NETBIRD_OVERLAY]

    first = channel_state.client_state(runtime, client_id)
    runtime.overlays = [dict(NETBIRD_OVERLAY, setup_key="E5F6A7B8")]  # scan: allow
    second = channel_state.client_state(runtime, client_id)

    assert first["overlays"] == [NETBIRD_OVERLAY]
    assert second["overlays"][0]["setup_key"] == "E5F6A7B8"  # scan: allow
    assert first["hash"] != second["hash"]
    assert "overlay" not in first


def test_two_overlays_reach_the_client_in_their_order(config_dir):
    runtime = FakeRuntime()
    client_id = ClientRegistry().create("alice")
    easytier = {"provider": "easytier", "mode": "console", "hub_address": ""}
    runtime.overlays = [NETBIRD_OVERLAY, easytier]

    state = channel_state.client_state(runtime, client_id)

    assert [entry["provider"] for entry in state["overlays"]] == [
        "netbird",
        "easytier",
    ]


def test_a_client_without_overlay_permission_gets_none_and_keeps_its_list(
    config_dir,
):
    runtime = FakeRuntime()
    registry = ClientRegistry()
    client_id = registry.create("alice")
    runtime.overlays = [NETBIRD_OVERLAY]
    registry.set_permission(client_id, ["web"])

    state = channel_state.client_state(runtime, client_id)

    assert state["overlays"] == []
    assert [entry["id"] for entry in state["services"]] == ["web_gitea"]


def test_no_overlay_to_join_is_an_empty_list_with_the_list_still_there(config_dir):
    runtime = FakeRuntime()
    client_id = ClientRegistry().create("alice")

    state = channel_state.client_state(runtime, client_id)

    assert state["overlays"] == []
    assert [entry["id"] for entry in state["services"]] == ["web_gitea"]


def test_the_terminals_list_every_managed_machine_while_terminal_is_allowed(
    config_dir,
):
    runtime = FakeRuntime()
    devices = DeviceRegistry()
    online = devices.create("lepton")
    devices.issue_token(online.id)
    offline = devices.create(None)
    devices.issue_token(offline.id)
    runtime.device_hostname[offline.id] = "muon"
    devices.create("unmanaged")
    runtime.agent_sessions.online.add(online.id.lower())
    registry = ClientRegistry()
    client_id = registry.create("alice")

    allowed = channel_state.client_state(runtime, client_id)
    registry.set_permission(client_id, ["web"])
    refused = channel_state.client_state(runtime, client_id)

    assert sorted(allowed["terminals"], key=lambda entry: entry["name"]) == [
        {"device_id": online.id, "name": "lepton", "is_online": True, "sessions": []},
        {"device_id": offline.id, "name": "muon", "is_online": False, "sessions": []},
    ]
    assert refused["terminals"] == []


def test_each_terminal_carries_the_sessions_the_client_sees_oldest_first(
    config_dir, monkeypatch
):
    runtime = FakeRuntime()
    devices = DeviceRegistry()
    machine = devices.create("lepton")
    devices.issue_token(machine.id)
    runtime.agent_sessions.online.add(machine.id.lower())
    client_id = ClientRegistry().create("alice")
    held = [
        {"session_id": "late", "started_at": 1790762400, "is_shared": True},
        {"session_id": "panel", "started_at": 1790760000, "owner": "hub"},
        {
            "session_id": "early",
            "started_at": 1790758800,
            "account": "root",
            "owner": f"client:{client_id}",
            "is_persistent": True,
            "is_attached": True,
            "attached_count": 2,
        },
    ]
    monkeypatch.setattr(
        runtime.agent_sessions,
        "reports",
        lambda: {machine.id: {"machine": {"sessions": held}}},
    )

    before = channel_state.client_state(runtime, client_id)
    (terminal,) = before["terminals"]
    held.pop()
    after = channel_state.client_state(runtime, client_id)

    assert [entry["session_id"] for entry in terminal["sessions"]] == [
        "early",
        "late",
    ]
    assert terminal["sessions"][0] == {
        "session_id": "early",
        "device_id": machine.id,
        "device_name": "lepton",
        "account": "root",
        "started_at": 1790758800,
        "title": "",
        "owner": f"client:{client_id}",
        "owner_name": "alice",
        "is_owned": True,
        "is_attached": True,
        "is_persistent": True,
        "is_shared": False,
        "attached_count": 2,
    }
    assert terminal["sessions"][1]["is_owned"] is False
    assert after["hash"] != before["hash"]


def test_every_entry_names_the_machine_that_provides_it(config_dir, monkeypatch):
    monkeypatch.setattr(channel_state.socket, "gethostname", lambda: "neutrino")
    runtime = FakeRuntime()
    devices = DeviceRegistry()
    argon = devices.create("argon")
    muon = devices.create(None)
    runtime.device_hostname[muon.id] = "muon"
    runtime.device_address[argon.id] = "192.168.100.7"
    runtime.published_services.entries = [
        dict(ENTRY, id="web_gitea_argon", device_id=argon.id),
        dict(ENTRY, id="web_gitea_muon", device_id=muon.id),
        dict(ENTRY, id="ai_gateway", type="ai", payload={"endpoint": "http://x/v1"}),
        dict(
            ENTRY,
            id="declared_on_argon",
            source="declared",
            payload={"url": "http://192.168.100.7:8080/"},
        ),
        dict(
            ENTRY,
            id="declared_elsewhere",
            type="port",
            source="declared",
            payload={"host": "203.0.113.9", "port": 22},
        ),
    ]
    client_id = ClientRegistry().create("alice")

    state = channel_state.client_state(runtime, client_id)

    assert {entry["id"]: entry["device_name"] for entry in state["services"]} == {
        "web_gitea_argon": "argon",
        "web_gitea_muon": "muon",
        "ai_gateway": "neutrino",
        "declared_on_argon": "argon",
        "declared_elsewhere": "",
    }
    assert all("device_id" not in entry for entry in state["services"])


def test_a_device_filter_keeps_only_that_devices_entries_and_terminals(
    config_dir, monkeypatch
):
    monkeypatch.setattr(clients_services, "machine_id", lambda: "hub-machine")
    runtime = FakeRuntime()
    devices = DeviceRegistry()
    hub = devices.create("neutrino", machine_id="hub-machine")
    devices.issue_token(hub.id)
    argon = devices.create("argon")
    devices.issue_token(argon.id)
    runtime.device_address[argon.id] = "192.168.100.7"
    runtime.published_services.entries = [
        dict(ENTRY, id="web_on_argon", device_id=argon.id),
        dict(ENTRY, id="web_on_hub"),
        dict(
            ENTRY,
            id="declared_on_argon",
            source="declared",
            payload={"url": "http://192.168.100.7:8080/"},
        ),
        dict(
            ENTRY,
            id="declared_elsewhere",
            source="declared",
            payload={"url": "http://203.0.113.9/"},
        ),
        dict(ENTRY, id="port_on_hub", type="port", payload={"host": "h"}),
    ]
    registry = ClientRegistry()
    client_id = registry.create("alice")

    registry.set_default_permission(
        ["web", "port", "terminal"], {"web": [argon.id], "terminal": [hub.id]}
    )
    state = channel_state.client_state(runtime, client_id)

    assert [entry["id"] for entry in state["services"]] == [
        "web_on_argon",
        "declared_on_argon",
        "port_on_hub",
    ]
    assert [entry["device_id"] for entry in state["terminals"]] == [hub.id]

    registry.set_default_permission(["web"], {"web": [hub.id]})

    assert [
        entry["id"]
        for entry in channel_state.client_state(runtime, client_id)["services"]
    ] == ["web_on_hub"]


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
