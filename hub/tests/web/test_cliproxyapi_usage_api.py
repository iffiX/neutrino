"""The usage and journal endpoints: shapes, filters, and refusals."""

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.cliproxyapi import accounts as accounts_module
from neutrino_hub.modules.cliproxyapi.usage_store import CliproxyApiUsageStore
from neutrino_hub.modules.credentials.vault import SecretVault
from neutrino_hub.modules.clients.registry import Client
from neutrino_hub.system.systemd_ctl import SystemdServiceController
from neutrino_hub.web.dependencies import require_session
from neutrino_hub.web.routers import ai as ai_router
from neutrino_hub.web.routers import cliproxyapi as cliproxyapi_router
from tests.conftest import unlock_vault

NOW = datetime.now(timezone.utc)

# One signed-in account, as GET /v0/management/auth-files reports it, trimmed
# to what the usage answer reads.
AUTH_FILE_ROW = {
    "name": "claude-person.json",
    # A runtime diagnostic label the gateway derives, not a credential.
    "auth_index": "a14afd0dfcb7d3e3",  # scan: allow
    "provider": "claude",
    "label": "person@example.com",
    "email": "person@example.com",
    "account_type": "oauth",
    "status": "active",
    "success": 12,
    "failed": 1,
}


class StubAuthFiles:
    """The management API's auth-file list, empty until a test signs one in.

    Attributes:
        files: What the auth-files route lists.
    """

    def __init__(self):
        self.files = []

    def request(self, method, url, **kwargs):
        return _Answer({"files": self.files})


class _Answer:
    status_code = 200
    is_success = True

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class StubClientRegistry:
    """Serves one client that holds gateway key ``k1``."""

    def all(self):
        return [Client(id="c1", name="laptop", ai_key_id="k1")]


@pytest.fixture
def gateway(monkeypatch):
    """A stubbed auth-file list, with the panel pointed at it."""
    stub = StubAuthFiles()
    monkeypatch.setattr(accounts_module.httpx, "request", stub.request)
    monkeypatch.setattr(
        cliproxyapi_router, "read_management_key", lambda: "probe-management-key"
    )
    return stub


@pytest.fixture
def client(monkeypatch, tmp_path, gateway):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    unlock_vault(monkeypatch, tmp_path)
    monkeypatch.setattr(cliproxyapi_router, "ClientRegistry", StubClientRegistry)
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


def seed_account_usage() -> None:
    """One success on key k1 through the signed-in account, as of right now."""
    CliproxyApiUsageStore().ingest(
        [
            {
                "timestamp": NOW.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                "api_key": "client-key-one",
                "source": "person@example.com",
                "auth_index": AUTH_FILE_ROW["auth_index"],
                "failed": False,
                "token_breakdown": {
                    "input": {"total_tokens": 40, "cache_read_tokens": 0},
                    "output": {"total_tokens": 5},
                },
            }
        ],
        key_ids={"client-key-one": "k1"},
        key_names={"k1": "laptop key"},
        provider_ids={},
        account_ids={AUTH_FILE_ROW["auth_index"]: AUTH_FILE_ROW["name"]},
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
    assert key["client_name"] == "laptop"
    assert key["first_seen_at"].endswith("Z")
    providers = {entry["provider_id"]: entry for entry in body["providers"]}
    assert set(providers) == {provider_id}
    row = providers[provider_id]
    assert row["name"] == "Relay"
    assert row["kind"] == "custom"
    assert row["requests"] == 1
    assert len(row["health"]) == 5
    assert row["health"][-1]["requests"] == 1


def test_an_account_gets_a_row_of_its_own_after_the_providers(client, gateway):
    """Usage an account served is a row, not a hole in the totals."""
    gateway.files = [AUTH_FILE_ROW]
    provider_id = stored_provider(client)
    seed_usage(provider_id)
    seed_account_usage()

    body = client.get("/api/cliproxyapi/usage?range=week").json()
    assert [row["provider_id"] for row in body["providers"]] == [
        provider_id,
        "claude-person.json",
    ]
    provider, account = body["providers"]
    assert provider["is_account"] is False
    assert provider["name"] == "Relay"
    assert provider["requests"] == 1

    assert account["is_account"] is True
    assert account["name"] == "person@example.com"
    assert account["kind"] == "claude"
    assert account["requests"] == 1
    assert account["input_tokens"] == 40
    assert account["health"][-1]["requests"] == 1
    assert body["totals"]["requests"] == 2


def test_an_account_the_gateway_dropped_keeps_its_cells_and_loses_its_row(
    client, gateway
):
    """Signing out is the deleted-provider behavior: stored, no longer served."""
    seed_account_usage()
    gateway.files = []

    body = client.get("/api/cliproxyapi/usage?range=week").json()
    assert body["providers"] == []
    assert body["totals"]["requests"] == 1


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
