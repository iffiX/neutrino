"""The AI page's API: providers over their own prefix, keys by reference."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.credentials.vault import SecretVault
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


def stored_token(value: str = "sk-test") -> str:  # scan: allow
    return SecretVault().add(kind="token", name="a key", secret={"value": value}).id


def test_provider_roundtrip(client):
    assert client.get("/api/ai/providers").json() == {"providers": []}
    token_id = stored_token()

    created = client.post(
        "/api/ai/providers",
        json={
            "name": "Anthropic direct",
            "kind": "anthropic",
            "base_url": "",
            "secret_id": token_id,
            "models": [{"name": "claude-sonnet-4-5", "alias": "sonnet"}],
        },
    )
    assert created.status_code == 200
    view = created.json()
    assert view["secret_id"] == token_id
    assert "api_key" not in view and "has_api_key" not in view

    listed = client.get("/api/ai/providers").json()["providers"]
    assert [p["name"] for p in listed] == ["Anthropic direct"]

    updated = client.put(
        f"/api/ai/providers/{view['id']}",
        json={"name": "Renamed"},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Renamed"
    assert updated.json()["secret_id"] == token_id

    assert client.delete(f"/api/ai/providers/{view['id']}").status_code == 200
    assert client.get("/api/ai/providers").json() == {"providers": []}
    # The token outlives the provider: its lifecycle is the Credentials page's.
    assert SecretVault().get(token_id) is not None


def test_a_null_reference_clears_and_a_missing_one_keeps(client):
    token_id = stored_token()
    view = client.post(
        "/api/ai/providers",
        json={"name": "relay", "kind": "custom", "base_url": "", "secret_id": token_id},
    ).json()

    kept = client.put(f"/api/ai/providers/{view['id']}", json={"base_url": "https://r"})
    assert kept.json()["secret_id"] == token_id

    cleared = client.put(f"/api/ai/providers/{view['id']}", json={"secret_id": None})
    assert cleared.status_code == 200
    assert cleared.json()["secret_id"] is None


def test_a_provider_without_a_reference_is_allowed(client):
    created = client.post(
        "/api/ai/providers",
        json={"name": "relay", "kind": "custom", "base_url": "", "secret_id": None},
    )
    assert created.status_code == 200
    assert created.json()["secret_id"] is None


@pytest.mark.parametrize("verb", ["post", "put"])
def test_a_reference_the_vault_does_not_hold_is_refused(client, verb):
    body = {"name": "relay", "kind": "custom", "base_url": "", "secret_id": "0" * 32}
    if verb == "post":
        refused = client.post("/api/ai/providers", json=body)
    else:
        token_id = stored_token()
        view = client.post(
            "/api/ai/providers",
            json={**body, "secret_id": token_id},
        ).json()
        refused = client.put(
            f"/api/ai/providers/{view['id']}", json={"secret_id": "0" * 32}
        )
    assert refused.status_code == 400
    assert refused.json()["detail"] == {
        "code": "unknown_credential",
        "params": {"field": "secret_id"},
    }


def test_a_reference_to_another_kind_is_refused(client):
    login_id = (
        SecretVault().add(kind="login", name="not a token", secret={"password": "p"}).id
    )
    refused = client.post(
        "/api/ai/providers",
        json={"name": "relay", "kind": "custom", "base_url": "", "secret_id": login_id},
    )
    assert refused.status_code == 400
    assert refused.json()["detail"]["code"] == "unknown_credential"


def test_provider_refusals(client):
    unknown_kind = client.post(
        "/api/ai/providers",
        json={"name": "x", "kind": "nonsense", "base_url": ""},
    )
    assert unknown_kind.status_code == 400
    assert client.put("/api/ai/providers/absent", json={}).status_code == 404
    assert client.delete("/api/ai/providers/absent").status_code == 404
