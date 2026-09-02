"""The Credentials tab's API.

The provider and key halves of the router share one file, and each serializes
through its own view helper. The provider endpoints once broke without any
test noticing — a second helper of the same name shadowed the first at import
— so this file walks every provider endpoint end to end.
"""

import asyncssh
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.web.dependencies import require_session
from neutrino_hub.web.routers import credentials as credentials_router

PUBLIC_KEY = "ssh-ed25519 AAAAC3Nz"  # scan: allow


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    app = FastAPI()
    app.include_router(credentials_router.router)
    app.dependency_overrides[require_session] = lambda: None
    with TestClient(app) as test_client:
        yield test_client


def test_provider_roundtrip(client):
    assert client.get("/api/credentials/ai_providers").json() == {"providers": []}

    created = client.post(
        "/api/credentials/ai_providers",
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

    listed = client.get("/api/credentials/ai_providers").json()["providers"]
    assert [p["name"] for p in listed] == ["Anthropic direct"]

    updated = client.put(
        f"/api/credentials/ai_providers/{view['id']}",
        json={"name": "Renamed", "api_key": ""},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Renamed"
    assert updated.json()["has_api_key"] is True

    assert (
        client.delete(f"/api/credentials/ai_providers/{view['id']}").status_code == 200
    )
    assert client.get("/api/credentials/ai_providers").json() == {"providers": []}


def test_provider_refusals(client):
    unknown_kind = client.post(
        "/api/credentials/ai_providers",
        json={"name": "x", "kind": "nonsense", "base_url": "", "api_key": "k"},
    )
    assert unknown_kind.status_code == 400
    assert (
        client.put("/api/credentials/ai_providers/absent", json={}).status_code == 404
    )
    assert client.delete("/api/credentials/ai_providers/absent").status_code == 404


def test_key_listing_is_untouched_by_provider_traffic(client):
    client.post(
        "/api/credentials/ai_providers",
        json={"name": "p", "kind": "openai", "base_url": "", "api_key": "k"},
    )
    assert client.get("/api/credentials/ssh_keys").json() == {"keys": []}


def test_key_roundtrip(client):
    key = asyncssh.generate_private_key("ssh-ed25519")
    created = client.post(
        "/api/credentials/ssh_keys",
        json={
            "name": "work laptop",
            "private_key": key.export_private_key().decode(),
            "passphrase": "",
        },
    )
    assert created.status_code == 200
    view = created.json()
    assert view["fingerprint"] == key.get_fingerprint()
    assert view["key_type"] == "ssh-ed25519"
    assert view["has_passphrase"] is False
    assert view["device_count"] == 0
    assert "private_key" not in view

    listed = client.get("/api/credentials/ssh_keys").json()["keys"]
    assert [item["name"] for item in listed] == ["work laptop"]

    renamed = client.put(
        f"/api/credentials/ssh_keys/{view['id']}", json={"name": "home desktop"}
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "home desktop"

    assert client.delete(f"/api/credentials/ssh_keys/{view['id']}").status_code == 200
    assert client.get("/api/credentials/ssh_keys").json() == {"keys": []}


def test_key_refusals(client):
    pasted_public_key = client.post(
        "/api/credentials/ssh_keys",
        json={"name": "wrong file", "private_key": PUBLIC_KEY},
    )
    assert pasted_public_key.status_code == 400
    assert "public key" in pasted_public_key.json()["detail"]
    assert (
        client.put(
            "/api/credentials/ssh_keys/absent", json={"name": "anything"}
        ).status_code
        == 404
    )
    assert client.delete("/api/credentials/ssh_keys/absent").status_code == 200
