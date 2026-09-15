"""The material a ``service`` stream closes with, judged for one client now.

A desktop's material is its address in the client's scope, its port and
the seat password; the gateway's is the base URL at the hub's address in
that scope, the key and a model. A client that is switched off, an entry
that is not published, a share that stopped, and a locked vault each close
with their code and no material.
"""

import pytest

from neutrino_hub.modules.clients import services
from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.modules.clients.services import service_material
from neutrino_hub.modules.services.device_shares import DeviceShareRegistry
from neutrino_hub.modules.services.host_scope import HostScope, link_scope

ENTRY = {
    "id": "web_gitea",
    "type": "web",
    "title": "Gitea",
    "payload": {"url": "http://192.168.100.1:3000"},
    "is_healthy": True,
    "source": "module",
    "description": "",
    "description_code": "",
    "description_params": {},
    "record_id": None,
    "detail_code": None,
}
RDP_ENTRY = {**ENTRY, "id": "rdp_s1", "type": "rdp", "payload": {"host": "h"}}
AI_ENTRY = {**ENTRY, "id": "ai", "type": "ai", "payload": {"endpoint": "http://x"}}
LAN = HostScope(
    id="192.168.100.0/24", cidr="192.168.100.0/24", hub_address="192.168.100.1"
)
OVERLAY = HostScope(id="overlay", cidr="100.64.0.0/16", hub_address="100.64.0.1")


class StubPublishedServices:
    def __init__(self, entries):
        self.entries = list(entries)

    def entries_for(self, scope):
        return list(self.entries)


class StubDesiredStates:
    def seat_password(self, key):
        return "seat-pass" if key == "dev" else ""  # scan: allow


class FakeRuntime:
    def __init__(self, entries=(ENTRY, RDP_ENTRY, AI_ENTRY)):
        self.client_scope = {}
        self.device_interfaces = {}
        self.published_services = StubPublishedServices(entries)
        self.device_shares = DeviceShareRegistry()
        self.desired_states = StubDesiredStates()
        self.served_models = None


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def credential(monkeypatch):
    """The gateway credential minted for a client, without a gateway."""
    minted: list = []

    def fake(registry, client, *, hub_host, served_models):
        minted.append((client.id, hub_host))
        return {"base_url": f"http://{hub_host}:8317", "api_key": "k", "model": "m"}

    monkeypatch.setattr(services, "client_credential", fake)
    return minted


def sharing(runtime) -> None:
    runtime.device_shares.declare(
        device_id="dev",
        share_id="s1",
        hostname="desk",
        host="192.168.100.7",
        port=21118,
    )
    runtime.device_interfaces["dev"] = [
        {"name": "wt0", "mac": "", "addresses": ["100.64.9.2"]},
        {"name": "enp1s0", "mac": "", "addresses": ["192.168.100.7"]},
    ]


def test_a_desktops_material_is_its_share_and_the_seat_password(config_dir):
    runtime = FakeRuntime()
    sharing(runtime)
    client_id = ClientRegistry().create("alice")
    runtime.client_scope[client_id] = LAN

    code, params = service_material(runtime, client_id, "rdp_s1")

    assert code == ""
    assert params == {
        "host": "192.168.100.7",
        "port": 21118,
        "password": "seat-pass",  # scan: allow
    }


def test_a_desktops_address_is_the_one_in_the_clients_scope_now(config_dir):
    runtime = FakeRuntime()
    sharing(runtime)
    client_id = ClientRegistry().create("alice")

    runtime.client_scope[client_id] = OVERLAY
    on_overlay = service_material(runtime, client_id, "rdp_s1")[1]["host"]
    runtime.client_scope[client_id] = link_scope("203.0.113.1")
    elsewhere = service_material(runtime, client_id, "rdp_s1")[1]["host"]
    del runtime.client_scope[client_id]
    unsettled = service_material(runtime, client_id, "rdp_s1")[1]["host"]

    assert (on_overlay, elsewhere, unsettled) == (
        "100.64.9.2",
        "192.168.100.7",
        "192.168.100.7",
    )


def test_a_desktop_that_stopped_sharing_is_rdp_not_shared(config_dir):
    runtime = FakeRuntime()
    client_id = ClientRegistry().create("alice")

    assert service_material(runtime, client_id, "rdp_s1") == (
        "rdp_not_shared",
        {"service_id": "rdp_s1"},
    )


def test_the_gateways_material_is_minted_for_the_clients_scope(config_dir, credential):
    runtime = FakeRuntime()
    client_id = ClientRegistry().create("alice")
    runtime.client_scope[client_id] = LAN

    code, params = service_material(runtime, client_id, "ai")

    assert code == ""
    assert params == {
        "base_url": "http://192.168.100.1:8317",
        "api_key": "k",
        "model": "m",
    }
    assert credential == [(client_id, "192.168.100.1")]


def test_a_locked_vault_mints_no_key_and_says_so(config_dir, monkeypatch):
    runtime = FakeRuntime()
    client_id = ClientRegistry().create("alice")
    monkeypatch.setattr(services, "client_credential", lambda *a, **k: None)

    assert service_material(runtime, client_id, "ai") == ("vault_locked", {})


def test_an_entry_that_is_not_published_is_service_unknown(config_dir):
    runtime = FakeRuntime()
    client_id = ClientRegistry().create("alice")

    assert service_material(runtime, client_id, "rdp_s9") == (
        "service_unknown",
        {"service_id": "rdp_s9"},
    )


def test_a_type_with_no_material_closes_empty(config_dir):
    runtime = FakeRuntime()
    client_id = ClientRegistry().create("alice")

    assert service_material(runtime, client_id, "web_gitea") == ("", {})


def test_a_disabled_or_forgotten_client_is_handed_nothing(config_dir, credential):
    runtime = FakeRuntime()
    client_id = ClientRegistry().create("alice")
    ClientRegistry().set_disabled(client_id, True)

    assert service_material(runtime, client_id, "ai") == ("client_disabled", {})
    assert service_material(runtime, "nobody", "ai") == ("binding_unknown", {})
    assert credential == []
