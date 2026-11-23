"""The AI page's API: providers over their own prefix, keys by reference, and each served name's context length."""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.ai.context_lengths import read_set_lengths
from neutrino_hub.modules.cliproxyapi.ops import write_ollama_providers
from neutrino_hub.modules.credentials.vault import SecretVault
from neutrino_hub.modules.devices.registry import DeviceRegistry
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers.hub import ai as ai_router
from tests.conftest import unlock_vault


class HostnameRuntime:
    """The runtime's hostnames, as the machines reported them."""

    def __init__(self):
        self.device_hostname: dict = {}


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    unlock_vault(monkeypatch, tmp_path)
    app = FastAPI()
    app.include_router(ai_router.router)
    app.dependency_overrides[require_session] = lambda: None
    runtime = HostnameRuntime()
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as test_client:
        test_client.hostnames = runtime.device_hostname
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


def test_each_machines_ollama_is_listed_by_the_machines_name(client):
    assert client.get("/api/hub/ai/ollama").json() == {"providers": []}
    named = DeviceRegistry().create("zeta").id
    unnamed = DeviceRegistry().create(None).id
    client.hostnames[unnamed] = "alpha-host"
    write_ollama_providers(
        [
            {"device_id": named, "address": "127.0.0.1:40001", "models": ["a:1"]},
            {"device_id": unnamed, "address": "127.0.0.1:40002", "models": ["b:1"]},
        ]
    )

    assert client.get("/api/hub/ai/ollama").json() == {
        "providers": [
            {"device_id": unnamed, "name": "alpha-host", "models": ["b:1"]},
            {"device_id": named, "name": "zeta", "models": ["a:1"]},
        ]
    }


# --- the context lengths: read, set, refused ---


class ContextRuntime:
    """The runtime's context view over the stored set lengths, its recomputes counted."""

    def __init__(self):
        self.served_models = None
        self.notes = 0

    def context_view(self) -> dict:
        lengths = read_set_lengths()
        return {
            "cloud": [
                {
                    "model": name,
                    "sources": [{"origin": "provider", "id": "p1", "name": "relay"}],
                    "context_length": lengths.get(name),
                    "default_context_length": 200000,
                }
                for name in ("gpt-x", "lab-mini")
            ],
            "ollama": [
                {
                    "model": "qwen2.5:0.5b",
                    "machines": [
                        {
                            "device_id": "dev",
                            "name": "argon",
                            "setting_context_length": 65536,
                            "trained_context_length": 32768,
                        }
                    ],
                    "sources": [],
                    "cloud_context_length": 0,
                    "context_length": 32768,
                }
            ],
        }

    def note_context_lengths(self) -> None:
        self.notes += 1


@pytest.fixture
def context_client(monkeypatch, tmp_path):
    from fastapi.exceptions import RequestValidationError

    from neutrino_hub.web.app import _body_invalid

    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    unlock_vault(monkeypatch, tmp_path)
    write_ollama_providers(
        [{"device_id": "dev", "address": "127.0.0.1:1", "models": ["qwen2.5:0.5b"]}]
    )
    monkeypatch.setattr(
        ai_router,
        "gateway_models",
        lambda served: ["gpt-x", "lab-mini", "qwen2.5:0.5b"],
    )
    app = FastAPI()
    app.include_router(ai_router.router)
    app.add_exception_handler(RequestValidationError, _body_invalid)
    app.dependency_overrides[require_session] = lambda: None
    runtime = ContextRuntime()
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as test_client:
        test_client.runtime = runtime
        yield test_client


def stored_lengths(tmp_path) -> dict:
    return json.loads((tmp_path / "ai/context_lengths.json").read_text())["lengths"]


def test_the_context_view_names_each_cloud_name_s_sources_and_each_ollama_name_s_machines(
    context_client,
):
    view = context_client.get("/api/hub/ai/context").json()

    assert [row["model"] for row in view["cloud"]] == ["gpt-x", "lab-mini"]
    assert view["cloud"][0]["sources"] == [
        {"origin": "provider", "id": "p1", "name": "relay"}
    ]
    assert view["ollama"][0]["machines"][0]["name"] == "argon"


def test_a_set_length_is_stored_and_a_null_takes_its_name_back(
    context_client, tmp_path
):
    answer = context_client.post(
        "/api/hub/ai/context/set", json={"lengths": {"gpt-x": 100000, "lab-mini": 4096}}
    )

    assert answer.status_code == 200
    assert stored_lengths(tmp_path) == {"gpt-x": 100000, "lab-mini": 4096}
    assert answer.json()["cloud"][0]["context_length"] == 100000
    assert context_client.runtime.notes == 1

    again = context_client.post(
        "/api/hub/ai/context/set", json={"lengths": {"gpt-x": None, "gone": None}}
    )

    assert again.status_code == 200
    assert stored_lengths(tmp_path) == {"lab-mini": 4096}
    assert again.json()["cloud"][0]["context_length"] is None


@pytest.mark.parametrize("length", [4095, 10000001])
def test_a_length_out_of_bounds_is_refused_and_nothing_is_stored(
    context_client, tmp_path, length
):
    answer = context_client.post(
        "/api/hub/ai/context/set", json={"lengths": {"gpt-x": length}}
    )

    assert answer.status_code == 400
    assert answer.json()["detail"] == {
        "code": "context_length_invalid",
        "params": {
            "model": "gpt-x",
            "context_length": length,
            "min": 4096,
            "max": 10000000,
        },
    }
    assert not (tmp_path / "ai/context_lengths.json").exists()
    assert context_client.runtime.notes == 0


@pytest.mark.parametrize("model", ["qwen2.5:0.5b", "never-served"])
def test_a_length_for_no_cloud_name_served_is_refused(context_client, model):
    answer = context_client.post(
        "/api/hub/ai/context/set", json={"lengths": {model: 8192}}
    )

    assert answer.status_code == 400
    assert answer.json()["detail"] == {
        "code": "model_not_served",
        "params": {"model": model},
    }


@pytest.mark.parametrize("value", [8192.5, "8192", True])
def test_a_value_that_is_no_whole_number_nor_null_is_body_invalid(
    context_client, value
):
    answer = context_client.post(
        "/api/hub/ai/context/set", json={"lengths": {"gpt-x": value}}
    )

    assert answer.status_code == 400
    assert answer.json()["detail"]["code"] == "body_invalid"
