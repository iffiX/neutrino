"""The AI page's API: providers over their own prefix, keys write-only."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.web.dependencies import require_session
from neutrino_hub.web.routers import ai as ai_router
from tests.conftest import unlock_vault


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    unlock_vault(monkeypatch, tmp_path)
    app = FastAPI()
    app.include_router(ai_router.router)
    app.dependency_overrides[require_session] = lambda: None
    with TestClient(app) as test_client:
        yield test_client


def test_provider_roundtrip(client):
    assert client.get("/api/ai/providers").json() == {"providers": []}

    created = client.post(
        "/api/ai/providers",
        json={
            "name": "Anthropic direct",
            "kind": "anthropic",
            "base_url": "",
            "api_key": "sk-test",  # scan: allow
            "models": [{"name": "claude-sonnet-4-5", "alias": "sonnet"}],
        },
    )
    assert created.status_code == 200
    view = created.json()
    assert view["has_api_key"] is True
    assert "api_key" not in view

    listed = client.get("/api/ai/providers").json()["providers"]
    assert [p["name"] for p in listed] == ["Anthropic direct"]

    updated = client.put(
        f"/api/ai/providers/{view['id']}",
        json={"name": "Renamed", "api_key": ""},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Renamed"
    assert updated.json()["has_api_key"] is True

    assert client.delete(f"/api/ai/providers/{view['id']}").status_code == 200
    assert client.get("/api/ai/providers").json() == {"providers": []}


def test_provider_refusals(client):
    unknown_kind = client.post(
        "/api/ai/providers",
        json={"name": "x", "kind": "nonsense", "base_url": "", "api_key": "k"},
    )
    assert unknown_kind.status_code == 400
    assert client.put("/api/ai/providers/absent", json={}).status_code == 404
    assert client.delete("/api/ai/providers/absent").status_code == 404
