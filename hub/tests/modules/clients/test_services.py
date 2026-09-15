"""The material a ``service`` stream closes with, judged for one client now.

A desktop's material is its address, port and the seat password; the
gateway's is the base URL, the key and a model. A client that is switched
off, an entry that is not published, a share that stopped, and a locked
vault each close with their code and no material.
"""

import pytest

from neutrino_hub.modules.clients import services
from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.modules.clients.services import service_material
from neutrino_hub.modules.services.device_shares import DeviceShareRegistry

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


class StubPublishedServices:
    def __init__(self, entries):
        self.entries = list(entries)

    def entries_for(self, target_host):
        return list(self.entries)


class StubDesiredStates:
    def seat_password(self, key):
        return "seat-pass" if key == "dev" else ""  # scan: allow


class FakeRuntime:
    def __init__(self, entries=(ENTRY, RDP_ENTRY, AI_ENTRY)):
        self.client_catalog_host = {}
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


def test_a_desktops_material_is_its_share_and_the_seat_password(config_dir):
    runtime = FakeRuntime()
    runtime.device_shares.declare(
        device_id="dev",
        share_id="s1",
        hostname="desk",
        host="192.168.100.7",
        port=21118,
    )
    client_id = ClientRegistry().create("alice")

    code, params = service_material(runtime, client_id, "rdp_s1")

    assert code == ""
    assert params == {
        "host": "192.168.100.7",
        "port": 21118,
        "password": "seat-pass",  # scan: allow
    }


def test_a_desktop_that_stopped_sharing_is_rdp_not_shared(config_dir):
    runtime = FakeRuntime()
    client_id = ClientRegistry().create("alice")

    assert service_material(runtime, client_id, "rdp_s1") == (
        "rdp_not_shared",
        {"service_id": "rdp_s1"},
    )


def test_the_gateways_material_is_minted_for_the_clients_host(config_dir, credential):
    runtime = FakeRuntime()
    client_id = ClientRegistry().create("alice")
    runtime.client_catalog_host[client_id] = "192.168.100.1"

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
