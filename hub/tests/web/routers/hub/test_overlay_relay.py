"""The relay section's API, with the converge step and the monitor replaced.

What is pinned is what the routes store and refuse: a host or an account
that could reach the root command line as an option, a port out of range, a
key the vault does not hold; a new server forgets the recorded host key;
and forgetting the host key starts the relay again.
"""

import asyncssh
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.devices.key_registry import KeyRegistry
from neutrino_hub.modules.overlay import relay_ops
from neutrino_hub.modules.overlay.relay_config import (
    OverlayRelayConfig,
    read_relay,
    write_relay,
)
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers.hub import overlay_relay as relay_router
from tests.conftest import unlock_vault


class FakeMonitor:
    def __init__(self):
        self.state = "connecting"

    def view(self) -> dict:
        return {
            "state": self.state,
            "last_error": "",
            "host_key_fingerprint": relay_ops.host_key_fingerprint(),
            "checked_at": "",
        }


class FakeRuntime:
    def __init__(self):
        self.relay_monitor = FakeMonitor()
        self.converged = 0
        self.restarted: list = []
        self.refusal: Exception | None = None

    async def converge_network(self, *, only=None):
        self.converged += 1
        if self.refusal is not None:
            raise self.refusal
        return []

    def apply_relay(self, *, is_restarted=False):
        self.restarted.append(is_restarted)
        return "relay_started"


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    unlock_vault(monkeypatch, tmp_path)
    monkeypatch.setattr(relay_ops, "UTILS_STATE_ROOT", tmp_path / "state")
    key = asyncssh.generate_private_key("ssh-ed25519")
    key_id = (
        KeyRegistry()
        .add(name="relay", private_key=key.export_private_key().decode())
        .id
    )
    runtime = FakeRuntime()
    app = FastAPI()
    app.include_router(relay_router.router)
    app.dependency_overrides[require_session] = lambda: None
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as client:
        yield client, runtime, key_id


def settings(key_id: str, **fields) -> dict:
    body = {
        "host": "203.0.113.5",
        "ssh_port": 22,
        "account": "relay",
        "key_id": key_id,
        "public_port": 18443,
    }
    body.update(fields)
    return body


def known_hosts(tmp_path):
    return tmp_path / "state" / "relay" / "known_hosts"


def record_host_key(tmp_path) -> None:
    blob = (
        asyncssh.generate_private_key("ssh-ed25519")
        .export_public_key("openssh")
        .decode()
        .split()[1]
    )
    known_hosts(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    known_hosts(tmp_path).write_text(f"203.0.113.5 ssh-ed25519 {blob}\n")


def test_an_unset_relay_reads_off_with_no_address(api):
    client, runtime, _ = api
    runtime.relay_monitor.state = "disabled"

    view = client.get("/api/hub/overlay/relay").json()

    assert view["is_enabled"] is False
    assert view["url"] == ""
    assert view["state"] == "disabled"
    assert (view["ssh_port"], view["public_port"]) == (22, 8443)


def test_saving_stores_the_settings_and_converges(api):
    client, runtime, key_id = api

    response = client.post("/api/hub/overlay/relay/set", json=settings(key_id))

    assert response.status_code == 200
    view = response.json()
    assert view["url"] == "https://203.0.113.5:18443"
    assert view["state"] == "connecting"
    assert read_relay() == OverlayRelayConfig(
        is_enabled=False,
        host="203.0.113.5",
        ssh_port=22,
        account="relay",
        key_id=key_id,
        public_port=18443,
    )
    assert runtime.converged == 1


def test_saving_keeps_the_switch_as_it_is(api):
    client, _, key_id = api
    write_relay(OverlayRelayConfig(is_enabled=True))

    client.post("/api/hub/overlay/relay/set", json=settings(key_id))

    assert read_relay().is_enabled is True


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("host", "-oProxyCommand=touch", "relay_host_invalid"),
        ("host", "two words", "relay_host_invalid"),
        ("host", "", "relay_host_invalid"),
        ("account", "relay@elsewhere", "relay_account_invalid"),
        ("account", "-l", "relay_account_invalid"),
    ],
)
def test_a_value_that_could_reach_the_command_line_as_an_option_is_refused(
    api, field, value, code
):
    client, runtime, key_id = api

    response = client.post(
        "/api/hub/overlay/relay/set", json=settings(key_id, **{field: value})
    )

    assert response.status_code == 400
    assert response.json()["detail"] == {"code": code, "params": {field: value}}
    assert runtime.converged == 0


@pytest.mark.parametrize("field", ["ssh_port", "public_port"])
def test_a_port_out_of_range_is_refused(api, field):
    client, _, key_id = api

    response = client.post(
        "/api/hub/overlay/relay/set", json=settings(key_id, **{field: 70000})
    )

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "port_out_of_range",
        "params": {"minimum": 1, "maximum": 65535, "value": 70000},
    }


def test_a_key_the_vault_does_not_hold_is_refused(api):
    client, _, _ = api

    response = client.post("/api/hub/overlay/relay/set", json=settings("gone"))

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "unknown_credential",
        "params": {"field": "key_id"},
    }


def test_a_new_server_forgets_the_recorded_host_key(api, tmp_path):
    client, _, key_id = api
    client.post("/api/hub/overlay/relay/set", json=settings(key_id))
    record_host_key(tmp_path)

    client.post(
        "/api/hub/overlay/relay/set", json=settings(key_id, host="198.51.100.9")
    )

    assert not known_hosts(tmp_path).exists()


def test_a_new_ssh_port_forgets_the_recorded_host_key(api, tmp_path):
    client, _, key_id = api
    client.post("/api/hub/overlay/relay/set", json=settings(key_id))
    record_host_key(tmp_path)

    client.post("/api/hub/overlay/relay/set", json=settings(key_id, ssh_port=2222))

    assert not known_hosts(tmp_path).exists()


def test_the_same_server_keeps_the_recorded_host_key(api, tmp_path):
    client, _, key_id = api
    client.post("/api/hub/overlay/relay/set", json=settings(key_id))
    record_host_key(tmp_path)

    view = client.post(
        "/api/hub/overlay/relay/set", json=settings(key_id, public_port=18444)
    ).json()

    assert known_hosts(tmp_path).exists()
    assert view["host_key_fingerprint"].startswith("SHA256:")


def test_forgetting_the_host_key_deletes_it_and_starts_the_relay_again(api, tmp_path):
    client, runtime, key_id = api
    client.post("/api/hub/overlay/relay/set", json=settings(key_id))
    record_host_key(tmp_path)

    view = client.post("/api/hub/overlay/relay/host_key/remove").json()

    assert not known_hosts(tmp_path).exists()
    assert view["host_key_fingerprint"] == ""
    assert runtime.restarted == [True]


def test_a_converge_that_fails_is_relay_apply_failed(api):
    client, runtime, key_id = api
    runtime.refusal = OSError("unit refused")

    response = client.post("/api/hub/overlay/relay/set", json=settings(key_id))

    assert response.status_code == 502
    assert response.json()["detail"] == {
        "code": "relay_apply_failed",
        "params": {"detail": "unit refused"},
    }


# --- a login in place of a key ---


def stored_login(name: str = "relay") -> str:
    from neutrino_hub.modules.credentials.vault import SecretVault

    return (
        SecretVault()
        .add(kind="login", name=name, secret={"password": "lab-only-7"})  # scan: allow
        .id
    )


def test_saving_with_a_login_stores_it_in_place_of_a_key(api):
    client, runtime, _ = api
    login_id = stored_login()

    response = client.post(
        "/api/hub/overlay/relay/set",
        json=settings(None, login_id=login_id),
    )

    assert response.status_code == 200, response.json()
    assert response.json()["login_id"] == login_id
    assert response.json()["key_id"] == ""
    assert read_relay().login_id == login_id
    assert read_relay().key_id == ""
    assert runtime.converged == 1


@pytest.mark.parametrize("both", [True, False])
def test_both_credentials_or_neither_is_refused(api, both):
    client, runtime, key_id = api
    body = (
        settings(key_id, login_id=stored_login())
        if both
        else settings(None, login_id=None)
    )

    response = client.post("/api/hub/overlay/relay/set", json=body)

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "unknown_credential",
        "params": {"field": "key_id"},
    }
    assert runtime.converged == 0


def test_a_login_the_vault_does_not_hold_is_refused(api):
    client, _, _ = api

    response = client.post(
        "/api/hub/overlay/relay/set", json=settings(None, login_id="gone")
    )

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "unknown_credential",
        "params": {"field": "login_id"},
    }
