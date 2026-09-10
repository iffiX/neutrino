"""The client keys endpoint: sealed where they are stored, whole where shown."""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.cliproxyapi import ops as cliproxyapi_ops
from neutrino_hub.modules.cliproxyapi.ops import CliproxyApiConfigApplier
from neutrino_hub.exceptions import VaultLockedError
from neutrino_hub.modules.devices.agent_sessions import AgentSessionRegistry
from neutrino_hub.modules.devices.constants import AGENT_SESSION_KIND_CLIENT
from neutrino_hub.system.systemd_ctl import SystemdServiceController
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers import cliproxyapi as cliproxyapi_router
from tests.conftest import unlock_vault

CONFIG_RELATIVE = "cliproxyapi/cliproxyapi.json"


def _inactive_service(self, name):
    return type("Service", (), {"is_active": False})()


class FakeRuntime:
    """Only what a key change reaches for: the client sockets, none open."""

    def __init__(self):
        self.client_sessions = AgentSessionRegistry(kind=AGENT_SESSION_KIND_CLIENT)


@pytest.fixture
def client(monkeypatch, tmp_path):
    """The AI page's routes over a config root of its own, nothing installed.

    The gateway is declared absent so a key change renders and stops: a test
    that reached ``systemctl restart`` would bounce the gateway it runs on.
    """
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    unlock_vault(monkeypatch, tmp_path)
    monkeypatch.setattr(cliproxyapi_ops, "UTILS_GENERATED_DIR", tmp_path / "generated")
    monkeypatch.setattr(
        CliproxyApiConfigApplier, "is_installed", property(lambda self: False)
    )
    monkeypatch.setattr(SystemdServiceController, "status", _inactive_service)
    app = FastAPI()
    app.include_router(cliproxyapi_router.router)
    app.dependency_overrides[require_session] = lambda: None
    app.dependency_overrides[get_runtime] = FakeRuntime
    with TestClient(app) as test_client:
        yield test_client


def _stored(tmp_path) -> dict:
    return json.loads((tmp_path / CONFIG_RELATIVE).read_text(encoding="utf-8"))


def test_a_generated_key_is_served_whole_and_stored_sealed(client, tmp_path):
    created = client.post("/api/cliproxyapi/keys", json={"name": "laptop"})
    assert created.status_code == 200
    keys = created.json()["client_keys"]
    assert len(keys) == 1
    assert keys[0]["name"] == "laptop"
    material = keys[0]["key"]
    assert material

    stored = _stored(tmp_path)
    assert set(stored["client_keys"][0]) == {"id", "name", "key_sealed", "created_at"}
    assert material not in json.dumps(stored)

    # The status view unseals server-side: the panel keeps its current shape.
    assert client.get("/api/cliproxyapi").json()["client_keys"] == keys


def test_a_revoked_key_leaves_nothing_behind(client, tmp_path):
    keys = client.post("/api/cliproxyapi/keys", json={"name": "laptop"}).json()
    key_id = keys["client_keys"][0]["id"]

    revoked = client.delete(f"/api/cliproxyapi/keys/{key_id}")

    assert revoked.status_code == 200
    assert revoked.json()["client_keys"] == []
    assert _stored(tmp_path)["client_keys"] == []


def test_a_locked_vault_refuses_rather_than_serving_a_blank_key(
    client, monkeypatch, tmp_path
):
    client.post("/api/cliproxyapi/keys", json={"name": "laptop"})
    monkeypatch.setattr(
        "neutrino_hub.utils.constants.UTILS_STATE_ROOT", tmp_path / "locked"
    )
    with pytest.raises(VaultLockedError):
        client.get("/api/cliproxyapi")
