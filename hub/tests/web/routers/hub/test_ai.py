"""The AI page's API: providers over their own prefix, keys by reference, the vendor presets, and each served name's context length and price."""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.ai.context_lengths import read_set_lengths
from neutrino_hub.modules.ai.model_prices import read_set_prices
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
    assert client.get("/api/hub/ai").json()["providers"] == []
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
    assert client.get("/api/hub/ai").json()["providers"] == []
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


# --- the context lengths and the prices: read, set, refused ---


# The models.dev price of each name's first source, as the runtime gives it.
DEFAULT_PRICES = {
    "gpt-x": {"input": 1.25, "output": 10.0, "cache_read": 0.125, "currency": "USD"}
}


class ContextRuntime:
    """The runtime's context view over the stored set lengths, its recomputes counted."""

    def __init__(self):
        self.served_models = None
        self.notes = 0

    def model_view(self) -> dict:
        lengths = read_set_lengths()
        prices = read_set_prices()
        return {
            "cloud": [
                {
                    "model": name,
                    "sources": [{"origin": "provider", "id": "p1", "name": "relay"}],
                    "context_length": lengths.get(name),
                    "default_context_length": 200000,
                    "price": prices.get(name),
                    "default_price": DEFAULT_PRICES.get(name),
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


def test_the_model_view_names_each_cloud_name_s_sources_and_each_ollama_name_s_machines(
    context_client,
):
    view = context_client.get("/api/hub/ai/model").json()

    assert [row["model"] for row in view["cloud"]] == ["gpt-x", "lab-mini"]
    assert view["cloud"][0]["sources"] == [
        {"origin": "provider", "id": "p1", "name": "relay", "price": None}
    ]
    assert view["ollama"][0]["machines"][0]["name"] == "argon"


def test_a_set_length_is_stored_and_a_null_takes_its_name_back(
    context_client, tmp_path
):
    answer = context_client.post(
        "/api/hub/ai/model/set", json={"lengths": {"gpt-x": 100000, "lab-mini": 4096}}
    )

    assert answer.status_code == 200
    assert stored_lengths(tmp_path) == {"gpt-x": 100000, "lab-mini": 4096}
    assert answer.json()["cloud"][0]["context_length"] == 100000
    assert context_client.runtime.notes == 1

    again = context_client.post(
        "/api/hub/ai/model/set", json={"lengths": {"gpt-x": None, "gone": None}}
    )

    assert again.status_code == 200
    assert stored_lengths(tmp_path) == {"lab-mini": 4096}
    assert again.json()["cloud"][0]["context_length"] is None


@pytest.mark.parametrize("length", [4095, 10000001])
def test_a_length_out_of_bounds_is_refused_and_nothing_is_stored(
    context_client, tmp_path, length
):
    answer = context_client.post(
        "/api/hub/ai/model/set", json={"lengths": {"gpt-x": length}}
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
        "/api/hub/ai/model/set", json={"lengths": {model: 8192}}
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
        "/api/hub/ai/model/set", json={"lengths": {"gpt-x": value}}
    )

    assert answer.status_code == 400
    assert answer.json()["detail"]["code"] == "body_invalid"


def stored_prices(tmp_path) -> dict:
    return json.loads((tmp_path / "ai/prices.json").read_text())["prices"]


def test_a_set_price_is_stored_and_a_null_takes_its_name_back(context_client, tmp_path):
    answer = context_client.post(
        "/api/hub/ai/model/set",
        json={
            "prices": {
                "gpt-x": {"input": 2.5, "output": 15, "currency": "USD"},
                "lab-mini": {"input": 1, "output": 2.123456, "currency": "CNY"},
            }
        },
    )

    assert answer.status_code == 200
    assert stored_prices(tmp_path) == {
        "gpt-x": {"input": 2.5, "output": 15, "currency": "USD"},
        "lab-mini": {"input": 1, "output": 2.123456, "currency": "CNY"},
    }
    cloud = {row["model"]: row for row in answer.json()["cloud"]}
    assert cloud["gpt-x"]["price"] == {"input": 2.5, "output": 15.0, "currency": "USD"}
    assert cloud["gpt-x"]["default_price"] == DEFAULT_PRICES["gpt-x"]
    assert cloud["lab-mini"]["default_price"] is None
    # A price restarts nothing and hands no state on.
    assert context_client.runtime.notes == 0

    again = context_client.post(
        "/api/hub/ai/model/set", json={"prices": {"gpt-x": None}}
    )
    assert again.status_code == 200
    assert stored_prices(tmp_path) == {
        "lab-mini": {"input": 1, "output": 2.123456, "currency": "CNY"}
    }


def test_lengths_and_prices_are_stored_in_one_write_each(context_client, tmp_path):
    answer = context_client.post(
        "/api/hub/ai/model/set",
        json={
            "lengths": {"gpt-x": 100000},
            "prices": {"gpt-x": {"input": 3, "output": 4, "currency": "USD"}},
        },
    )

    assert answer.status_code == 200
    assert stored_lengths(tmp_path) == {"gpt-x": 100000}
    assert stored_prices(tmp_path)["gpt-x"]["input"] == 3
    assert context_client.runtime.notes == 1


def test_a_price_equal_to_the_default_is_stored_as_none(context_client, tmp_path):
    context_client.post(
        "/api/hub/ai/model/set",
        json={"prices": {"gpt-x": {"input": 2, "output": 3, "currency": "USD"}}},
    )

    answer = context_client.post(
        "/api/hub/ai/model/set",
        json={"prices": {"gpt-x": {"input": 1.25, "output": 10, "currency": "USD"}}},
    )

    assert answer.status_code == 200
    assert stored_prices(tmp_path) == {}
    # The same numbers in CNY are another price.
    context_client.post(
        "/api/hub/ai/model/set",
        json={"prices": {"gpt-x": {"input": 1.25, "output": 10, "currency": "CNY"}}},
    )
    assert stored_prices(tmp_path)["gpt-x"]["currency"] == "CNY"


def test_a_price_whose_name_is_no_longer_served_is_kept(context_client, tmp_path):
    (tmp_path / "ai").mkdir(exist_ok=True)
    (tmp_path / "ai/prices.json").write_text(
        json.dumps({"prices": {"gone": {"input": 1, "output": 2, "currency": "USD"}}})
    )

    answer = context_client.post(
        "/api/hub/ai/model/set",
        json={"prices": {"gpt-x": {"input": 2, "output": 3, "currency": "USD"}}},
    )

    assert answer.status_code == 200
    assert set(stored_prices(tmp_path)) == {"gone", "gpt-x"}


@pytest.mark.parametrize(
    "price, number",
    [
        ({"input": -0.01, "output": 1, "currency": "USD"}, -0.01),
        ({"input": 1, "output": 10000.5, "currency": "USD"}, 10000.5),
        ({"input": 0.0000001, "output": 1, "currency": "USD"}, 0.0000001),
    ],
)
def test_a_price_number_out_of_range_or_too_fine_is_refused(
    context_client, tmp_path, price, number
):
    answer = context_client.post(
        "/api/hub/ai/model/set", json={"prices": {"gpt-x": price}}
    )

    assert answer.status_code == 400
    assert answer.json()["detail"] == {
        "code": "price_invalid",
        "params": {"model": "gpt-x", "price": number, "min": 0, "max": 10000},
    }
    assert not (tmp_path / "ai/prices.json").exists()


def test_a_currency_other_than_usd_and_cny_is_refused(context_client, tmp_path):
    answer = context_client.post(
        "/api/hub/ai/model/set",
        json={"prices": {"gpt-x": {"input": 1, "output": 2, "currency": "EUR"}}},
    )

    assert answer.status_code == 400
    assert answer.json()["detail"] == {
        "code": "currency_invalid",
        "params": {"model": "gpt-x", "currency": "EUR"},
    }
    assert not (tmp_path / "ai/prices.json").exists()


@pytest.mark.parametrize("model", ["qwen2.5:0.5b", "never-served"])
def test_a_price_for_no_cloud_name_served_is_refused(context_client, model):
    answer = context_client.post(
        "/api/hub/ai/model/set",
        json={"prices": {model: {"input": 1, "output": 2, "currency": "USD"}}},
    )

    assert answer.status_code == 400
    assert answer.json()["detail"] == {
        "code": "model_not_served",
        "params": {"model": model},
    }


@pytest.mark.parametrize(
    "value", [3, "cheap", {"input": "1", "output": 2, "currency": "USD"}, {"input": 1}]
)
def test_a_price_that_is_no_price_object_nor_null_is_body_invalid(
    context_client, value
):
    answer = context_client.post(
        "/api/hub/ai/model/set", json={"prices": {"gpt-x": value}}
    )

    assert answer.status_code == 400
    assert answer.json()["detail"]["code"] == "body_invalid"


# --- a default price: the first source in serving order models.dev prices ---


@pytest.fixture
def priced_client(monkeypatch, tmp_path):
    """The model routes over a real runtime's view, its sources and prices stubbed."""
    from neutrino_hub.modules.ai.context_lengths import AiContextLengthResolver
    from neutrino_hub.modules.ai.registry import AiProviderRecord
    from neutrino_hub.web import panel_runtime as runtime_module
    from neutrino_hub.web.panel_runtime import PanelRuntime

    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    unlock_vault(monkeypatch, tmp_path)
    providers = [
        AiProviderRecord(
            id="relay", name="A relay", kind="custom", base_url="https://r.example/v1"
        ),
        AiProviderRecord(
            id="ds-plan",
            name="Zhipu plan",
            kind="custom",
            base_url="https://open.bigmodel.cn/api/coding/paas/v4",
            models=[{"name": "glm-5.3", "alias": "shared"}],
        ),
        AiProviderRecord(
            id="ds",
            name="Another DeepSeek",
            kind="custom",
            base_url="https://api.deepseek.com",
            models=[{"name": "deepseek-v4-pro", "alias": "shared"}],
        ),
    ]
    providers[0].models = [{"name": "shared", "alias": ""}]
    resolver = AiContextLengthResolver(
        known_models=[],
        catalog={
            "channels": {},
            "accounts": [
                {"name": "kimi-person.json", "provider": "kimi", "models": ["kimi-k3"]}
            ],
        },
        providers=providers,
        set_lengths={},
        ollama_machines=[],
        ollama_names=set(),
    )
    monkeypatch.setattr(
        runtime_module,
        "prices_in_force",
        lambda: {
            "fetched_at": "2026-11-26T00:00:00Z",
            "providers": {
                "zhipuai": {"glm-5.3": {"input": 4, "output": 18, "cache_read": 0.8}},
                "deepseek": {"deepseek-v4-pro": {"input": 0.28, "output": 1.1}},
                "moonshotai": {"kimi-k3": {"input": 0.6, "output": 2.5}},
            },
        },
    )
    monkeypatch.setattr(
        runtime_module, "gateway_models", lambda served: ["kimi-k3", "shared"]
    )
    monkeypatch.setattr(
        ai_router, "gateway_models", lambda served: ["kimi-k3", "shared"]
    )
    panel = object.__new__(PanelRuntime)
    panel.served_models = None
    monkeypatch.setattr(panel, "_context_resolver", lambda: resolver, raising=False)
    monkeypatch.setattr(panel, "note_context_lengths", lambda: None, raising=False)
    app = FastAPI()
    app.include_router(ai_router.router)
    app.dependency_overrides[require_session] = lambda: None
    app.dependency_overrides[get_runtime] = lambda: panel
    with TestClient(app) as test_client:
        yield test_client


def test_a_default_price_is_the_first_source_in_serving_order_that_has_one(
    priced_client,
):
    cloud = {
        row["model"]: row
        for row in priced_client.get("/api/hub/ai/model").json()["cloud"]
    }

    # The relay is first in the list but models.dev prices no custom relay;
    # the Zhipu plan is next and priced, ahead of DeepSeek below it.
    assert cloud["shared"]["default_price"] == {
        "input": 4.0,
        "output": 18.0,
        "cache_read": 0.8,
        "currency": "USD",
    }
    assert cloud["shared"]["price"] is None
    # An account's name is priced at its login's provider, a cache price
    # models.dev does not give left out.
    assert cloud["kimi-k3"]["default_price"] == {
        "input": 0.6,
        "output": 2.5,
        "currency": "USD",
    }


def source_prices(client, model: str) -> dict:
    """Each source's price of a name, by the source's id."""
    rows = client.get("/api/hub/ai/model").json()["cloud"]
    (row,) = [row for row in rows if row["model"] == model]
    return {source["id"]: source["price"] for source in row["sources"]}


def test_each_source_carries_the_price_of_its_own_upstream(priced_client):
    prices = source_prices(priced_client, "shared")

    assert prices["relay"] is None
    assert prices["ds-plan"] == {
        "input": 4.0,
        "output": 18.0,
        "cache_read": 0.8,
        "currency": "USD",
    }
    assert prices["ds"] == {"input": 0.28, "output": 1.1, "currency": "USD"}
    assert source_prices(priced_client, "kimi-k3")["kimi-person.json"] == {
        "input": 0.6,
        "output": 2.5,
        "currency": "USD",
    }


def test_a_persons_price_replaces_each_sources_input_and_output(priced_client):
    answer = priced_client.post(
        "/api/hub/ai/model/set",
        json={"prices": {"shared": {"input": 2, "output": 9, "currency": "CNY"}}},
    )
    assert answer.status_code == 200

    prices = source_prices(priced_client, "shared")
    # The cache read keeps models.dev's ratio to the input, in the person's currency.
    assert prices["ds-plan"] == {
        "input": 2.0,
        "output": 9.0,
        "cache_read": 0.4,
        "currency": "CNY",
    }
    assert prices["ds"] == {"input": 2.0, "output": 9.0, "currency": "CNY"}
    assert prices["relay"] == {"input": 2.0, "output": 9.0, "currency": "CNY"}


def test_a_price_equal_to_a_real_default_is_stored_as_none(priced_client, tmp_path):
    answer = priced_client.post(
        "/api/hub/ai/model/set",
        json={"prices": {"shared": {"input": 4, "output": 18, "currency": "USD"}}},
    )

    assert answer.status_code == 200
    assert stored_prices(tmp_path) == {}


# --- the vendor presets ---


def test_the_provider_list_carries_the_presets_and_each_providers_vendor(client):
    token_id = stored_token()
    preset = client.post(
        "/api/hub/ai/provider/add",
        json={
            "name": "Zhipu GLM",
            "kind": "custom",
            "base_url": "https://OPEN.bigmodel.cn/api/coding/paas/v4/",
            "secret_id": token_id,
            "models": [{"name": "glm-5.3", "alias": ""}],
        },
    )
    custom = client.post(
        "/api/hub/ai/provider/add",
        json={"name": "relay", "kind": "custom", "base_url": "https://r.example/v1"},
    )
    kind = client.post(
        "/api/hub/ai/provider/add",
        json={"name": "Anthropic", "kind": "anthropic", "base_url": ""},
    )

    assert (preset.json()["vendor"], preset.json()["endpoint"]) == ("zhipu", "plan_cn")
    listed = client.get("/api/hub/ai").json()
    vendors = {
        row["name"]: (row["vendor"], row["endpoint"]) for row in listed["providers"]
    }
    assert vendors == {
        "Zhipu GLM": ("zhipu", "plan_cn"),
        "relay": ("", ""),
        "Anthropic": ("", ""),
    }
    assert custom.status_code == kind.status_code == 200
    assert [vendor["id"] for vendor in listed["vendors"]][:2] == ["deepseek", "kimi"]
    assert listed["vendors"][1]["endpoints"][0] == {
        "id": "api_cn",
        "base_url": "https://api.moonshot.cn/v1",
        "price_provider": "moonshotai-cn",
        "is_plan": False,
        "models": ["kimi-k3.1-pro", "kimi-k3.1-pro-highspeed", "kimi-k3"],
    }


def test_a_provider_saved_from_a_preset_is_stored_in_the_records_own_shape(
    client, tmp_path
):
    client.post(
        "/api/hub/ai/provider/add",
        json={
            "name": "DeepSeek",
            "kind": "custom",
            "base_url": "https://api.deepseek.com",
            "models": [{"name": "deepseek-flash", "alias": ""}],
        },
    )

    (stored,) = json.loads((tmp_path / "ai/providers.json").read_text())["providers"]
    assert "vendor" not in stored and "endpoint" not in stored
    assert stored["kind"] == "custom"
    assert stored["base_url"] == "https://api.deepseek.com"
