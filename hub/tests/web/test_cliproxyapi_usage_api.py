"""The usage and journal endpoints: shapes, filters, and refusals."""

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.cliproxyapi.usage_store import CliproxyApiUsageStore
from neutrino_hub.modules.credentials.vault import SecretVault
from neutrino_hub.modules.devices.registry import DeviceClientInfo, ManagedDevice
from neutrino_hub.system.systemd_ctl import SystemdServiceController
from neutrino_hub.web.dependencies import require_session
from neutrino_hub.web.routers import ai as ai_router
from neutrino_hub.web.routers import cliproxyapi as cliproxyapi_router
from tests.conftest import unlock_vault

NOW = datetime.now(timezone.utc)


class StubDeviceRegistry:
    """Serves one device that holds client key ``k1``."""

    def all_stored(self):
        return [
            ManagedDevice(
                mac_address="aa:bb:cc:dd:ee:01",
                name="laptop",
                client=DeviceClientInfo(ai_key_id="k1"),
            )
        ]


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    unlock_vault(monkeypatch, tmp_path)
    monkeypatch.setattr(cliproxyapi_router, "DeviceRegistry", StubDeviceRegistry)
    app = FastAPI()
    app.include_router(cliproxyapi_router.router)
    app.include_router(ai_router.router)
    app.dependency_overrides[require_session] = lambda: None
    with TestClient(app) as test_client:
        yield test_client


def seed_usage(provider_id: str = "p1") -> None:
    """One success on key k1 through one provider, as of right now."""
    CliproxyApiUsageStore().ingest(
        [
            {
                "timestamp": NOW.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                "api_key": "client-key-one",
                "source": "sk-upstream",
                "failed": False,
                "token_breakdown": {
                    "input": {
                        "total_tokens": 100,
                        "cache_read_tokens": 20,
                        "cache_write_tokens": 5,
                    },
                    "output": {"total_tokens": 10},
                },
            }
        ],
        key_ids={"client-key-one": "k1"},
        key_names={"k1": "laptop key"},
        provider_ids={"sk-upstream": provider_id},
    )


def stored_provider(client) -> str:
    token_id = (
        SecretVault().add(kind="token", name="key", secret={"value": "sk-upstream"}).id
    )
    view = client.post(
        "/api/ai/providers",
        json={
            "name": "Relay",
            "kind": "custom",
            "base_url": "u",
            "secret_id": token_id,
        },
    ).json()
    return view["id"]


def test_an_empty_store_answers_zeros_in_shape(client):
    answer = client.get("/api/cliproxyapi/usage?range=day")
    assert answer.status_code == 200
    body = answer.json()
    assert body["range"] == "day"
    assert body["generated_at"].endswith("Z")
    assert body["rates"] == {"rpm": 0.0, "tpm": 0.0}
    assert body["totals"]["requests"] == 0
    assert len(body["series"]) == 24
    assert body["series"][0]["bucket"].endswith(":00:00Z")
    assert body["keys"] == []
    assert body["providers"] == []


def test_usage_lands_on_keys_devices_and_providers(client):
    provider_id = stored_provider(client)
    seed_usage(provider_id)
    body = client.get("/api/cliproxyapi/usage?range=week").json()
    assert body["totals"]["requests"] == 1
    assert body["totals"]["input_tokens"] == 100
    assert body["totals"]["cache_read_tokens"] == 20
    assert body["totals"]["cache_write_tokens"] == 5
    assert body["series"][-1]["requests"] == 1
    key = body["keys"][0]
    assert key["key_id"] == "k1"
    assert key["name"] == "laptop key"
    assert key["device_name"] == "laptop"
    assert key["first_seen_at"].endswith("Z")
    providers = {entry["provider_id"]: entry for entry in body["providers"]}
    assert set(providers) == {provider_id}
    row = providers[provider_id]
    assert row["name"] == "Relay"
    assert row["kind"] == "custom"
    assert row["requests"] == 1
    assert len(row["health"]) == 5
    assert row["health"][-1]["requests"] == 1


def test_the_key_filter_narrows_and_an_unknown_key_is_a_404(client):
    seed_usage()
    narrowed = client.get("/api/cliproxyapi/usage?range=day&key_id=k1")
    assert narrowed.status_code == 200
    body = narrowed.json()
    assert body["totals"]["requests"] == 1
    assert body["rates"]["rpm"] > 0
    # The filter never shrinks the key list: the filter itself is built from it.
    assert [key["key_id"] for key in body["keys"]] == ["k1"]

    unknown = client.get("/api/cliproxyapi/usage?range=day&key_id=nope")
    assert unknown.status_code == 404
    assert unknown.json()["detail"] == {
        "code": "unknown_key",
        "params": {"key_id": "nope"},
    }


def test_an_unknown_range_is_a_coded_422(client):
    answer = client.get("/api/cliproxyapi/usage?range=fortnight")
    assert answer.status_code == 422
    assert answer.json()["detail"] == {
        "code": "invalid_range",
        "params": {"range": "fortnight"},
    }


def test_the_journal_returns_lines_most_recent_last(client, monkeypatch):
    asked = {}

    def fake_journal(self, name, *, line_count):
        asked["name"] = name
        asked["line_count"] = line_count
        return "older line\nnewer line\n"

    monkeypatch.setattr(SystemdServiceController, "journal", fake_journal)
    answer = client.get("/api/cliproxyapi/journal?lines=7")
    assert answer.status_code == 200
    assert answer.json() == {"lines": ["older line", "newer line"]}
    assert asked == {"name": "cliproxyapi", "line_count": 7}


def test_the_status_carries_the_day_counters(client, monkeypatch):
    seed_usage()
    monkeypatch.setattr(
        SystemdServiceController,
        "status",
        lambda self, name: type("S", (), {"is_active": False})(),
    )
    body = client.get("/api/cliproxyapi").json()
    assert body["requests_today"] == 1
    assert body["tokens_today"] == 110
