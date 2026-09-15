"""The gateway block of the AI page: keys, accounts, usage and the journal.

The client keys are sealed where they are stored and whole where shown. The
accounts stub answers exactly what CLIProxyAPI 7.2.146's management API
answered a probe of the pinned binary, trimmed to the fields the panel
reads. Usage answers come from the store the panel's collector fills.
"""

import json
from datetime import datetime, timezone

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.exceptions import VaultLockedError
from neutrino_hub.modules.cliproxyapi import accounts as accounts_module
from neutrino_hub.modules.cliproxyapi import ops as cliproxyapi_ops
from neutrino_hub.modules.cliproxyapi import usage_store as usage_store_module
from neutrino_hub.modules.cliproxyapi.ops import CliproxyApiConfigApplier
from neutrino_hub.modules.cliproxyapi.usage_store import CliproxyApiUsageStore
from neutrino_hub.modules.clients.registry import Client
from neutrino_hub.modules.credentials.vault import SecretVault
from neutrino_hub.modules.channel.constants import CHANNEL_ROLE_CLIENT
from neutrino_hub.modules.channel.sessions import ChannelSessionRegistry
from neutrino_hub.system.systemd_ctl import SystemdServiceController
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers.hub import ai as ai_router
from neutrino_hub.web.routers.hub import ai_gateway as cliproxyapi_router
from tests.conftest import unlock_vault

LOGIN_PATH = "/api/hub/ai/gateway/account_login"


# --- the client keys: sealed where they are stored, whole where shown ---


CONFIG_RELATIVE = "cliproxyapi/cliproxyapi.json"


def _inactive_service(self, name):
    return type("Service", (), {"is_active": False})()


class KeysRuntime:
    """Only what a key change reaches for: the client sockets, none open."""

    def __init__(self):
        self.client_sessions = ChannelSessionRegistry(CHANNEL_ROLE_CLIENT)


@pytest.fixture
def keys_client(monkeypatch, tmp_path):
    """The gateway routes over a config root of its own, nothing installed.

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
    app.dependency_overrides[get_runtime] = KeysRuntime
    with TestClient(app) as test_client:
        yield test_client


def _stored(tmp_path) -> dict:
    return json.loads((tmp_path / CONFIG_RELATIVE).read_text(encoding="utf-8"))


def test_a_generated_key_is_served_whole_and_stored_sealed(keys_client, tmp_path):
    created = keys_client.post("/api/hub/ai/gateway/key/add", json={"name": "laptop"})
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
    assert keys_client.get("/api/hub/ai/gateway").json()["client_keys"] == keys


def test_a_revoked_key_leaves_nothing_behind(keys_client, tmp_path):
    keys = keys_client.post(
        "/api/hub/ai/gateway/key/add", json={"name": "laptop"}
    ).json()
    key_id = keys["client_keys"][0]["id"]

    revoked = keys_client.post(
        "/api/hub/ai/gateway/key/remove", json={"key_id": key_id}
    )

    assert revoked.status_code == 200
    assert revoked.json()["client_keys"] == []
    assert _stored(tmp_path)["client_keys"] == []


def test_a_locked_vault_refuses_rather_than_serving_a_blank_key(
    keys_client, monkeypatch, tmp_path
):
    keys_client.post("/api/hub/ai/gateway/key/add", json={"name": "laptop"})
    monkeypatch.setattr(
        "neutrino_hub.utils.constants.UTILS_STATE_ROOT", tmp_path / "locked"
    )
    with pytest.raises(VaultLockedError):
        keys_client.get("/api/hub/ai/gateway")


# --- the accounts: listing, signing in, polling, and signing out ---


# One signed-in Claude account, as GET /v0/management/auth-files reports it.
ACCOUNT_ROW = {
    "account": "person@example.com",
    "account_type": "oauth",
    # A runtime diagnostic label the gateway derives, not a credential.
    "auth_index": "a14afd0dfcb7d3e3",  # scan: allow
    "created_at": "2026-09-04T17:59:47.075469741+08:00",
    "disabled": False,
    "email": "person@example.com",
    "failed": 0,
    "success": 12,
    "id": "claude-person.json",
    "label": "person@example.com",
    "modtime": "2026-09-04T17:59:47.075686814+08:00",
    "name": "claude-person.json",
    "path": "/var/lib/neutrino/cliproxyapi/auth/claude-person.json",
    "provider": "claude",
    "quota": {"signals": {}},
    "recent_requests": [{"time": "17:20-17:30", "success": 0, "failed": 0}],
    "runtime_only": False,
    "size": 139,
    "source": "file",
    "status": "active",
    "status_message": "",
    "type": "claude",
    "unavailable": False,
    "updated_at": "2026-09-04T17:59:47.075686814+08:00",
}
# GET /v0/management/anthropic-auth-url, whose redirect lands on a loopback
# address only the gateway's own box could serve.
AUTH_URL_ANSWER = {
    # The flow's one-time handle; it authorizes nothing and is long expired.
    "state": "1fcbe3daac3266d8345939083d1e5f68",  # scan: allow
    "status": "ok",
    "url": (
        "https://claude.ai/oauth/authorize?client_id=9d1c250a"
        "&redirect_uri=http%3A%2F%2Flocalhost%3A54545%2Fcallback"
        "&state=1fcbe3daac3266d8345939083d1e5f68"
    ),
}
# GET /v0/management/kimi-auth-url: a device flow the gateway finishes itself.
DEVICE_URL_ANSWER = {
    "expires_in": 1800,
    "flow": "device",
    "state": "kmi-1788515872655562421",
    "status": "ok",
    "url": "https://www.kimi.com/code/authorize_device?user_code=DNUT-SUG9",
    "user_code": "DNUT-SUG9",
}


class StubGateway:
    """Stands in for the management API on loopback.

    Attributes:
        files: What the auth-files route lists.
        login_status: What a poll reports, in order; the last one repeats.
        calls: Every request made, as method and path.
    """

    def __init__(self):
        self.files = []
        self.login_status = [{"status": "wait"}]
        self.calls = []
        self.is_down = False

    def request(self, method, url, **kwargs):
        path = httpx.URL(url).path
        params = kwargs.get("params") or {}
        self.calls.append((method, path, params, kwargs.get("json")))
        if self.is_down:
            raise httpx.ConnectError("connection refused")
        if path == "/v0/management/auth-files":
            return self._auth_files(method, params)
        if path.endswith("-auth-url"):
            answer = DEVICE_URL_ANSWER if "kimi" in path else AUTH_URL_ANSWER
            return _response(200, answer)
        if path == "/v0/management/get-auth-status":
            answer = self.login_status[0]
            if len(self.login_status) > 1:
                self.login_status.pop(0)
            return _response(200, answer)
        if path == "/v0/management/oauth-session":
            if params.get("state") != AUTH_URL_ANSWER["state"]:
                return _response(404, {"error": "unknown or expired state"})
            return _response(200, {"status": "ok", "cancelled": True})
        if path == "/v0/management/oauth-callback":
            body = kwargs.get("json") or {}
            if body.get("state") != AUTH_URL_ANSWER["state"]:
                return _response(
                    404, {"error": "unknown or expired state", "status": "error"}
                )
            return _response(200, {"status": "ok"})
        return _response(404, {"error": "not found"})

    def _auth_files(self, method, params):
        if method == "GET":
            return _response(200, {"files": self.files})
        if method == "DELETE":
            name = params.get("name")
            remaining = [f for f in self.files if f["name"] != name]
            if len(remaining) == len(self.files):
                return _response(404, {"error": "not found"})
            self.files = remaining
            return _response(200, {"status": "ok"})
        return _response(404, {"error": "not found"})


class _GatewayAnswer:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self.is_success = 200 <= status_code < 300
        self._payload = payload

    def json(self):
        return self._payload


def _response(status_code, payload):
    return _GatewayAnswer(status_code, payload)


@pytest.fixture
def accounts_gateway(monkeypatch, tmp_path):
    """A stubbed management API, with the panel pointed at it."""
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    unlock_vault(monkeypatch, tmp_path)
    stub = StubGateway()
    monkeypatch.setattr(accounts_module.httpx, "request", stub.request)
    monkeypatch.setattr(
        cliproxyapi_router, "resolve_management_key", lambda: "probe-management-key"
    )
    return stub


@pytest.fixture
def accounts_client(accounts_gateway):
    del accounts_gateway
    app = FastAPI()
    app.include_router(cliproxyapi_router.router)
    app.dependency_overrides[require_session] = lambda: None
    with TestClient(app) as test_client:
        yield test_client


def test_lists_no_accounts_and_the_flows_that_exist(accounts_client):
    """An empty gateway still says which logins it can start."""
    answer = accounts_client.get("/api/hub/ai/gateway/account")
    assert answer.status_code == 200
    body = answer.json()
    assert body["accounts"] == []
    assert "anthropic" in body["login_kinds"]
    assert "codex" in body["login_kinds"]
    # 7.2.146 carries no Gemini OAuth flow; a Google model needs a key.
    assert "gemini" not in body["login_kinds"]


def test_lists_an_account_without_its_file_or_history(
    accounts_client, accounts_gateway
):
    """The row carries who is signed in, not where the token lives."""
    accounts_gateway.files = [ACCOUNT_ROW]
    body = accounts_client.get("/api/hub/ai/gateway/account").json()
    assert len(body["accounts"]) == 1
    account = body["accounts"][0]
    assert account["name"] == "claude-person.json"
    assert account["provider"] == "claude"
    assert account["label"] == "person@example.com"
    assert account["status"] == "active"
    assert account["is_disabled"] is False
    assert account["success_count"] == 12
    assert "path" not in account
    assert "recent_requests" not in account


def test_deleting_an_account_signs_it_out(accounts_client, accounts_gateway):
    """A revocation acts at once and answers with what is left."""
    accounts_gateway.files = [ACCOUNT_ROW]
    answer = accounts_client.post(
        "/api/hub/ai/gateway/account/remove", json={"name": "claude-person.json"}
    )
    assert answer.status_code == 200
    assert answer.json()["accounts"] == []
    assert accounts_gateway.files == []


def test_deleting_an_account_the_gateway_lacks_is_404(accounts_client):
    """Signing out something already gone is worded, not a crash."""
    answer = accounts_client.post(
        "/api/hub/ai/gateway/account/remove", json={"name": "gone.json"}
    )
    assert answer.status_code == 404
    assert answer.json()["detail"]["code"] == "unknown_account"


def test_starting_a_login_returns_the_url_to_open(accounts_client):
    """A redirect flow hands back the URL and the handle to poll."""
    answer = accounts_client.post(
        "/api/hub/ai/gateway/account_login/start", json={"kind": "anthropic"}
    )
    assert answer.status_code == 200
    body = answer.json()
    assert body["state"] == AUTH_URL_ANSWER["state"]
    assert body["url"].startswith("https://claude.ai/oauth/authorize")
    assert body["flow"] == "redirect"
    assert body["kind"] == "anthropic"


def test_starting_a_device_login_carries_the_code_to_type(accounts_client):
    """A device flow says what to type and how long it stays open."""
    body = accounts_client.post(
        "/api/hub/ai/gateway/account_login/start", json={"kind": "kimi"}
    ).json()
    assert body["flow"] == "device"
    assert body["user_code"] == "DNUT-SUG9"
    assert body["expires_in"] == 1800


def test_an_unknown_kind_is_refused(accounts_client):
    """A flow this gateway does not carry is named, not attempted."""
    answer = accounts_client.post(
        "/api/hub/ai/gateway/account_login/start", json={"kind": "gemini"}
    )
    assert answer.status_code == 422
    detail = answer.json()["detail"]
    assert detail["code"] == "unsupported_kind"
    assert detail["params"]["kind"] == "gemini"


def test_polling_reports_pending_then_complete(accounts_client, accounts_gateway):
    """The happy path: open, waiting, then signed in."""
    state = AUTH_URL_ANSWER["state"]
    accounts_gateway.login_status = [{"status": "wait"}, {"status": "ok"}]
    first = accounts_client.get(LOGIN_PATH, params={"state": state}).json()
    assert first["status"] == "pending"
    second = accounts_client.get(LOGIN_PATH, params={"state": state}).json()
    assert second["status"] == "complete"


def test_submitting_the_code_reports_the_flow_state(accounts_client, accounts_gateway):
    """The code goes back, and the outcome arrives on the poll after it."""
    state = AUTH_URL_ANSWER["state"]
    accounts_gateway.login_status = [{"status": "wait"}]
    answer = accounts_client.post(
        f"{LOGIN_PATH}/code/set", json={"state": state, "code": "abc123"}
    )
    assert answer.status_code == 200
    assert answer.json()["status"] == "pending"
    posted = [c for c in accounts_gateway.calls if c[1].endswith("oauth-callback")]
    assert posted[0][3] == {"state": state, "code": "abc123"}


def test_a_pasted_redirect_address_is_reduced_to_its_code(
    accounts_client, accounts_gateway
):
    """The browser lands on a dead loopback URL, so the address bar is enough."""
    state = AUTH_URL_ANSWER["state"]
    accounts_client.post(
        f"{LOGIN_PATH}/code/set",
        json={
            "state": state,
            "code": f"http://localhost:54545/callback?code=xyz789&state={state}",
        },
    )
    posted = [c for c in accounts_gateway.calls if c[1].endswith("oauth-callback")]
    assert posted[0][3]["code"] == "xyz789"


def test_a_login_the_gateway_forgot_is_expired(accounts_client):
    """A flow that timed out is worded as expired, not unreachable."""
    answer = accounts_client.post(
        f"{LOGIN_PATH}/code/set", json={"state": "deadbeef", "code": "abc"}
    )
    assert answer.status_code == 404
    assert answer.json()["detail"]["code"] == "login_expired"


def test_cancelling_a_login_drops_it(accounts_client, accounts_gateway):
    """Closing the sign-in without finishing leaves nothing waiting."""
    answer = accounts_client.post(
        f"{LOGIN_PATH}/stop", json={"state": AUTH_URL_ANSWER["state"]}
    )
    assert answer.status_code == 204
    assert any(c[1].endswith("oauth-session") for c in accounts_gateway.calls)


def test_a_failed_exchange_reports_the_gateways_own_reason(
    accounts_client, accounts_gateway
):
    """What the provider refused is passed through, not reworded."""
    accounts_gateway.login_status = [
        {"error": "Failed to exchange authorization code for tokens", "status": "error"}
    ]
    body = accounts_client.get(
        LOGIN_PATH, params={"state": AUTH_URL_ANSWER["state"]}
    ).json()
    assert body["status"] == "failed"
    assert body["message"] == "Failed to exchange authorization code for tokens"


def test_a_gateway_that_is_down_is_worded(accounts_client, accounts_gateway):
    """Nothing here works with the gateway stopped, and it says so."""
    accounts_gateway.is_down = True
    answer = accounts_client.get("/api/hub/ai/gateway/account")
    assert answer.status_code == 502
    assert answer.json()["detail"]["code"] == "gateway_unreachable"


def test_no_management_key_is_worded(accounts_client, monkeypatch):
    """Before the first apply there is no key, and every route needs one."""
    monkeypatch.setattr(cliproxyapi_router, "resolve_management_key", lambda: "")
    answer = accounts_client.get("/api/hub/ai/gateway/account")
    assert answer.status_code == 502
    assert answer.json()["detail"]["code"] == "management_key_missing"


def test_signing_in_never_makes_the_gateway_stale(monkeypatch, tmp_path):
    """Accounts are state: an auth file appearing is not a configuration change.

    The auth directory is one stable string in the YAML, so what the apply
    fingerprinted stays true however many accounts sign in afterwards.
    """
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    unlock_vault(monkeypatch, tmp_path)
    monkeypatch.setattr(CliproxyApiConfigApplier, "is_installed", True)
    applier = CliproxyApiConfigApplier()
    rendered, _ = applier._render()
    from neutrino_hub.modules.cliproxyapi.ops import (
        ensure_auth_dir,
        write_served_fingerprint,
    )

    write_served_fingerprint(rendered)
    assert applier.is_serving_stale is False
    auth_dir = ensure_auth_dir()
    (auth_dir / "claude-person.json").write_text('{"type":"claude"}')
    (auth_dir / "codex-person.json").write_text('{"type":"codex"}')
    assert applier.is_serving_stale is False


def test_the_auth_directory_is_private(monkeypatch, tmp_path):
    """Token files are readable by root alone, from the moment the dir exists."""
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    unlock_vault(monkeypatch, tmp_path)
    from neutrino_hub.modules.cliproxyapi.ops import ensure_auth_dir

    auth_dir = ensure_auth_dir()
    assert auth_dir.is_dir()
    assert auth_dir.stat().st_mode & 0o777 == 0o700


# --- usage and the journal: shapes, filters, and refusals ---


# One moment for the seeded rows and the store's clock alike, so a run
# that crosses an hour or a day boundary still lands its row in the last
# bucket.
NOW = datetime.now(timezone.utc)


class FrozenDatetime(datetime):
    """The store's clock, stopped at NOW."""

    @classmethod
    def now(cls, tz=None):
        return NOW if tz is None else NOW.astimezone(tz)


# One signed-in account, as GET /v0/management/auth-files reports it, trimmed
# to what the usage answer reads.
USAGE_ACCOUNT_ROW = {
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
        return _UsageAnswer({"files": self.files})


class _UsageAnswer:
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
def usage_gateway(monkeypatch):
    """A stubbed auth-file list, with the panel pointed at it."""
    stub = StubAuthFiles()
    monkeypatch.setattr(accounts_module.httpx, "request", stub.request)
    monkeypatch.setattr(
        cliproxyapi_router, "resolve_management_key", lambda: "probe-management-key"
    )
    return stub


@pytest.fixture
def usage_client(monkeypatch, tmp_path, usage_gateway):
    monkeypatch.setattr(usage_store_module, "datetime", FrozenDatetime)
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    unlock_vault(monkeypatch, tmp_path)
    del usage_gateway
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
                "auth_index": USAGE_ACCOUNT_ROW["auth_index"],
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
        account_ids={USAGE_ACCOUNT_ROW["auth_index"]: USAGE_ACCOUNT_ROW["name"]},
    )


def stored_provider(client) -> str:
    token_id = (
        SecretVault().add(kind="token", name="key", secret={"value": "sk-upstream"}).id
    )
    view = client.post(
        "/api/hub/ai/provider/add",
        json={
            "name": "Relay",
            "kind": "custom",
            "base_url": "u",
            "secret_id": token_id,
        },
    ).json()
    return view["id"]


def test_an_empty_store_answers_zeros_in_shape(usage_client):
    answer = usage_client.get("/api/hub/ai/gateway/usage?range=day")
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


def test_usage_lands_on_keys_devices_and_providers(usage_client):
    provider_id = stored_provider(usage_client)
    seed_usage(provider_id)
    body = usage_client.get("/api/hub/ai/gateway/usage?range=week").json()
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


def test_an_account_gets_a_row_of_its_own_after_the_providers(
    usage_client, usage_gateway
):
    """Usage an account served is a row, not a hole in the totals."""
    usage_gateway.files = [USAGE_ACCOUNT_ROW]
    provider_id = stored_provider(usage_client)
    seed_usage(provider_id)
    seed_account_usage()

    body = usage_client.get("/api/hub/ai/gateway/usage?range=week").json()
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
    usage_client, usage_gateway
):
    """Signing out is the deleted-provider behavior: stored, no longer served."""
    seed_account_usage()
    usage_gateway.files = []

    body = usage_client.get("/api/hub/ai/gateway/usage?range=week").json()
    assert body["providers"] == []
    assert body["totals"]["requests"] == 1


def test_the_key_filter_narrows_and_an_unknown_key_is_a_404(usage_client):
    seed_usage()
    narrowed = usage_client.get("/api/hub/ai/gateway/usage?range=day&key_id=k1")
    assert narrowed.status_code == 200
    body = narrowed.json()
    assert body["totals"]["requests"] == 1
    assert body["rates"]["rpm"] > 0
    # The filter never shrinks the key list: the filter itself is built from it.
    assert [key["key_id"] for key in body["keys"]] == ["k1"]

    unknown = usage_client.get("/api/hub/ai/gateway/usage?range=day&key_id=nope")
    assert unknown.status_code == 404
    assert unknown.json()["detail"] == {
        "code": "unknown_key",
        "params": {"key": "nope"},
    }


def test_an_unknown_range_is_a_coded_422(usage_client):
    answer = usage_client.get("/api/hub/ai/gateway/usage?range=fortnight")
    assert answer.status_code == 422
    assert answer.json()["detail"] == {
        "code": "invalid_range",
        "params": {"range": "fortnight"},
    }


def test_the_journal_returns_lines_most_recent_last(usage_client, monkeypatch):
    asked = {}

    def fake_journal(self, name, *, line_count):
        asked["name"] = name
        asked["line_count"] = line_count
        return "older line\nnewer line\n"

    monkeypatch.setattr(SystemdServiceController, "journal", fake_journal)
    answer = usage_client.get("/api/hub/ai/gateway/journal?lines=7")
    assert answer.status_code == 200
    assert answer.json() == {"lines": ["older line", "newer line"]}
    assert asked == {"name": "cliproxyapi", "line_count": 7}


def test_the_status_carries_the_day_counters(usage_client, monkeypatch):
    seed_usage()
    monkeypatch.setattr(
        SystemdServiceController,
        "status",
        lambda self, name: type("S", (), {"is_active": False})(),
    )
    body = usage_client.get("/api/hub/ai/gateway").json()
    assert body["requests_today"] == 1
    assert body["tokens_today"] == 110
