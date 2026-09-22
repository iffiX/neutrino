"""The AI page's API: providers over their own prefix, keys by reference."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.credentials.vault import SecretVault
from neutrino_hub.web.dependencies import require_session
from neutrino_hub.web.routers.hub import ai as ai_router
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
    assert client.get("/api/hub/ai").json() == {"providers": []}
    token_id = stored_token()

    created = client.post(
        "/api/hub/ai/provider/add",
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

    listed = client.get("/api/hub/ai").json()["providers"]
    assert [p["name"] for p in listed] == ["Anthropic direct"]

    updated = client.post(
        "/api/hub/ai/provider/set",
        json={"provider_id": view["id"], "name": "Renamed"},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Renamed"
    assert updated.json()["secret_id"] == token_id

    removed = client.post(
        "/api/hub/ai/provider/remove", json={"provider_id": view["id"]}
    )
    assert removed.status_code == 200
    assert client.get("/api/hub/ai").json() == {"providers": []}
    # The token outlives the provider: its lifecycle is the Credentials page's.
    assert SecretVault().get(token_id) is not None


def test_a_null_reference_clears_and_a_missing_one_keeps(client):
    token_id = stored_token()
    view = client.post(
        "/api/hub/ai/provider/add",
        json={"name": "relay", "kind": "custom", "base_url": "", "secret_id": token_id},
    ).json()

    kept = client.post(
        "/api/hub/ai/provider/set",
        json={"provider_id": view["id"], "base_url": "https://r"},
    )
    assert kept.json()["secret_id"] == token_id

    cleared = client.post(
        "/api/hub/ai/provider/set", json={"provider_id": view["id"], "secret_id": None}
    )
    assert cleared.status_code == 200
    assert cleared.json()["secret_id"] is None


def test_a_provider_without_a_reference_is_allowed(client):
    created = client.post(
        "/api/hub/ai/provider/add",
        json={"name": "relay", "kind": "custom", "base_url": "", "secret_id": None},
    )
    assert created.status_code == 200
    assert created.json()["secret_id"] is None


@pytest.mark.parametrize("verb", ["add", "set"])
def test_a_reference_the_vault_does_not_hold_is_refused(client, verb):
    body = {"name": "relay", "kind": "custom", "base_url": "", "secret_id": "0" * 32}
    if verb == "add":
        refused = client.post("/api/hub/ai/provider/add", json=body)
    else:
        token_id = stored_token()
        view = client.post(
            "/api/hub/ai/provider/add",
            json={**body, "secret_id": token_id},
        ).json()
        refused = client.post(
            "/api/hub/ai/provider/set",
            json={"provider_id": view["id"], "secret_id": "0" * 32},
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
        "/api/hub/ai/provider/add",
        json={"name": "relay", "kind": "custom", "base_url": "", "secret_id": login_id},
    )
    assert refused.status_code == 400
    assert refused.json()["detail"]["code"] == "unknown_credential"


def test_the_stored_order_is_the_served_order(client):
    first = client.post(
        "/api/hub/ai/provider/add",
        json={"name": "first", "kind": "custom", "base_url": ""},
    ).json()
    second = client.post(
        "/api/hub/ai/provider/add",
        json={"name": "second", "kind": "custom", "base_url": ""},
    ).json()
    listed = client.get("/api/hub/ai").json()["providers"]
    assert [p["id"] for p in listed] == [first["id"], second["id"]]

    reordered = client.post(
        "/api/hub/ai/provider/order/set",
        json={"provider_ids": [second["id"], first["id"]]},
    )
    assert reordered.status_code == 200
    assert [p["id"] for p in reordered.json()["providers"]] == [
        second["id"],
        first["id"],
    ]
    listed = client.get("/api/hub/ai").json()["providers"]
    assert [p["id"] for p in listed] == [second["id"], first["id"]]


def test_an_order_that_is_not_a_permutation_is_refused(client):
    stored = client.post(
        "/api/hub/ai/provider/add",
        json={"name": "only", "kind": "custom", "base_url": ""},
    ).json()

    refused = client.post(
        "/api/hub/ai/provider/order/set", json={"provider_ids": ["absent"]}
    )
    assert refused.status_code == 400
    assert refused.json()["detail"] == {
        "code": "provider_order_mismatch",
        "params": {"missing": [stored["id"]], "unknown": ["absent"], "duplicate": []},
    }

    doubled = client.post(
        "/api/hub/ai/provider/order/set",
        json={"provider_ids": [stored["id"], stored["id"]]},
    )
    assert doubled.status_code == 400
    assert doubled.json()["detail"]["params"]["duplicate"] == [stored["id"]]

    listed = client.get("/api/hub/ai").json()["providers"]
    assert [p["id"] for p in listed] == [stored["id"]]


def test_provider_refusals(client):
    unknown_kind = client.post(
        "/api/hub/ai/provider/add",
        json={"name": "x", "kind": "nonsense", "base_url": ""},
    )
    assert unknown_kind.status_code == 400
    absent = {"provider_id": "absent"}
    assert client.post("/api/hub/ai/provider/set", json=absent).status_code == 404
    assert client.post("/api/hub/ai/provider/remove", json=absent).status_code == 404
