"""The accounts endpoints: listing, signing in, polling, and signing out.

The stub answers exactly what CLIProxyAPI 7.2.146's management API answered a
probe of the pinned binary, trimmed to the fields the panel reads.
"""

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.cliproxyapi import accounts as accounts_module
from neutrino_hub.modules.cliproxyapi.ops import CliproxyApiConfigApplier
from neutrino_hub.web.dependencies import require_session
from neutrino_hub.web.routers import cliproxyapi as cliproxyapi_router
from tests.conftest import unlock_vault

# One signed-in Claude account, as GET /v0/management/auth-files reports it.
AUTH_FILE_ROW = {
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


class _Answer:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self.is_success = 200 <= status_code < 300
        self._payload = payload

    def json(self):
        return self._payload


def _response(status_code, payload):
    return _Answer(status_code, payload)


@pytest.fixture
def gateway(monkeypatch, tmp_path):
    """A stubbed management API, with the panel pointed at it."""
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    unlock_vault(monkeypatch, tmp_path)
    stub = StubGateway()
    monkeypatch.setattr(accounts_module.httpx, "request", stub.request)
    monkeypatch.setattr(
        cliproxyapi_router, "read_management_key", lambda: "probe-management-key"
    )
    return stub


@pytest.fixture
def client(gateway):
    app = FastAPI()
    app.include_router(cliproxyapi_router.router)
    app.dependency_overrides[require_session] = lambda: None
    with TestClient(app) as test_client:
        yield test_client


def test_lists_no_accounts_and_the_flows_that_exist(client):
    """An empty gateway still says which logins it can start."""
    answer = client.get("/api/cliproxyapi/accounts")
    assert answer.status_code == 200
    body = answer.json()
    assert body["accounts"] == []
    assert "anthropic" in body["login_kinds"]
    assert "codex" in body["login_kinds"]
    # 7.2.146 carries no Gemini OAuth flow; a Google model needs a key.
    assert "gemini" not in body["login_kinds"]


def test_lists_an_account_without_its_file_or_history(client, gateway):
    """The row carries who is signed in, not where the token lives."""
    gateway.files = [AUTH_FILE_ROW]
    body = client.get("/api/cliproxyapi/accounts").json()
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


def test_deleting_an_account_signs_it_out(client, gateway):
    """A revocation acts at once and answers with what is left."""
    gateway.files = [AUTH_FILE_ROW]
    answer = client.delete("/api/cliproxyapi/accounts/claude-person.json")
    assert answer.status_code == 200
    assert answer.json()["accounts"] == []
    assert gateway.files == []


def test_deleting_an_account_the_gateway_lacks_is_404(client):
    """Signing out something already gone is worded, not a crash."""
    answer = client.delete("/api/cliproxyapi/accounts/gone.json")
    assert answer.status_code == 404
    assert answer.json()["detail"]["code"] == "unknown_account"


def test_starting_a_login_returns_the_url_to_open(client):
    """A redirect flow hands back the URL and the handle to poll."""
    answer = client.post("/api/cliproxyapi/account_logins", json={"kind": "anthropic"})
    assert answer.status_code == 200
    body = answer.json()
    assert body["state"] == AUTH_URL_ANSWER["state"]
    assert body["url"].startswith("https://claude.ai/oauth/authorize")
    assert body["flow"] == "redirect"
    assert body["kind"] == "anthropic"


def test_starting_a_device_login_carries_the_code_to_type(client):
    """A device flow says what to type and how long it stays open."""
    body = client.post("/api/cliproxyapi/account_logins", json={"kind": "kimi"}).json()
    assert body["flow"] == "device"
    assert body["user_code"] == "DNUT-SUG9"
    assert body["expires_in"] == 1800


def test_an_unknown_kind_is_refused(client):
    """A flow this gateway does not carry is named, not attempted."""
    answer = client.post("/api/cliproxyapi/account_logins", json={"kind": "gemini"})
    assert answer.status_code == 422
    detail = answer.json()["detail"]
    assert detail["code"] == "unsupported_kind"
    assert detail["params"]["kind"] == "gemini"


def test_polling_reports_pending_then_complete(client, gateway):
    """The happy path: open, waiting, then signed in."""
    state = AUTH_URL_ANSWER["state"]
    gateway.login_status = [{"status": "wait"}, {"status": "ok"}]
    first = client.get(f"/api/cliproxyapi/account_logins/{state}").json()
    assert first["status"] == "pending"
    second = client.get(f"/api/cliproxyapi/account_logins/{state}").json()
    assert second["status"] == "complete"


def test_submitting_the_code_reports_the_flow_state(client, gateway):
    """The code goes back, and the outcome arrives on the poll after it."""
    state = AUTH_URL_ANSWER["state"]
    gateway.login_status = [{"status": "wait"}]
    answer = client.put(
        f"/api/cliproxyapi/account_logins/{state}/code", json={"code": "abc123"}
    )
    assert answer.status_code == 200
    assert answer.json()["status"] == "pending"
    posted = [c for c in gateway.calls if c[1].endswith("oauth-callback")]
    assert posted[0][3] == {"state": state, "code": "abc123"}


def test_a_pasted_redirect_address_is_reduced_to_its_code(client, gateway):
    """The browser lands on a dead loopback URL, so the address bar is enough."""
    state = AUTH_URL_ANSWER["state"]
    client.put(
        f"/api/cliproxyapi/account_logins/{state}/code",
        json={"code": f"http://localhost:54545/callback?code=xyz789&state={state}"},
    )
    posted = [c for c in gateway.calls if c[1].endswith("oauth-callback")]
    assert posted[0][3]["code"] == "xyz789"


def test_a_login_the_gateway_forgot_is_expired(client):
    """A flow that timed out is worded as expired, not unreachable."""
    answer = client.put(
        "/api/cliproxyapi/account_logins/deadbeef/code", json={"code": "abc"}
    )
    assert answer.status_code == 404
    assert answer.json()["detail"]["code"] == "login_expired"


def test_cancelling_a_login_drops_it(client, gateway):
    """Closing the sign-in without finishing leaves nothing waiting."""
    answer = client.delete(
        f"/api/cliproxyapi/account_logins/{AUTH_URL_ANSWER['state']}"
    )
    assert answer.status_code == 204
    assert any(c[1].endswith("oauth-session") for c in gateway.calls)


def test_a_failed_exchange_reports_the_gateways_own_reason(client, gateway):
    """What the provider refused is passed through, not reworded."""
    gateway.login_status = [
        {"error": "Failed to exchange authorization code for tokens", "status": "error"}
    ]
    body = client.get(
        f"/api/cliproxyapi/account_logins/{AUTH_URL_ANSWER['state']}"
    ).json()
    assert body["status"] == "failed"
    assert body["message"] == "Failed to exchange authorization code for tokens"


def test_a_gateway_that_is_down_is_worded(client, gateway):
    """Nothing here works with the gateway stopped, and it says so."""
    gateway.is_down = True
    answer = client.get("/api/cliproxyapi/accounts")
    assert answer.status_code == 502
    assert answer.json()["detail"]["code"] == "gateway_unreachable"


def test_no_management_key_is_worded(client, monkeypatch):
    """Before the first apply there is no key, and every route needs one."""
    monkeypatch.setattr(cliproxyapi_router, "read_management_key", lambda: "")
    answer = client.get("/api/cliproxyapi/accounts")
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
