"""The Credentials tab's API.

The provider, key and login quarters of the router share one file, and each
serializes through its own view helper. The provider
endpoints once broke without any test noticing — a second helper of the same
name shadowed the first at import — so this file walks every endpoint end to
end.
"""

import json
from types import SimpleNamespace

import asyncssh
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.exceptions import VaultLockedError
from neutrino_hub.modules.credentials.vault import SecretVault
from neutrino_hub.modules.overlay.relay_config import (
    OverlayRelayConfig,
    read_relay,
    write_relay,
)
from neutrino_hub.web.app import _vault_locked
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers.hub import credential as credentials_router
from tests.conftest import unlock_vault

PUBLIC_KEY = "ssh-ed25519 AAAAC3Nz"  # scan: allow
STORED_PASSWORD = "hunter2hunter2"  # scan: allow
STORED_ACCOUNT_PASSWORD = "svc-pw-1"  # scan: allow


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    unlock_vault(monkeypatch, tmp_path)
    app = FastAPI()
    app.add_exception_handler(VaultLockedError, _vault_locked)
    app.include_router(credentials_router.router)
    app.dependency_overrides[require_session] = lambda: None
    app.dependency_overrides[get_runtime] = lambda: SimpleNamespace(
        is_config_dirty=False
    )
    with TestClient(app) as test_client:
        yield test_client


def write_device(tmp_path, ssh: dict) -> None:
    """Store one device whose SSH block references stored secrets."""
    path = tmp_path / "devices"
    path.mkdir(parents=True, exist_ok=True)
    (path / "devices.json").write_text(
        json.dumps(
            {
                "devices": {
                    "aa:bb:cc:dd:ee:ff": {
                        "name": "xenode",
                        "ssh": {"host": "192.168.100.2", "username": "root", **ssh},
                    }
                }
            }
        )
    )


def test_key_roundtrip(client):
    key = asyncssh.generate_private_key("ssh-ed25519")
    created = client.post(
        "/api/hub/credential/ssh_key/add",
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

    listed = client.get("/api/hub/credential/ssh_key").json()["keys"]
    assert [item["name"] for item in listed] == ["work laptop"]

    assert (
        client.post(
            "/api/hub/credential/ssh_key/remove", json={"key_id": view["id"]}
        ).status_code
        == 200
    )
    assert client.get("/api/hub/credential/ssh_key").json() == {"keys": []}


def test_deleting_a_key_clears_device_references(client, tmp_path):
    key = asyncssh.generate_private_key("ssh-ed25519")
    created = client.post(
        "/api/hub/credential/ssh_key/add",
        json={"name": "work laptop", "private_key": key.export_private_key().decode()},
    )
    key_id = created.json()["id"]
    write_device(tmp_path, {"key_id": key_id})

    listed = client.get("/api/hub/credential/ssh_key").json()["keys"]
    assert listed[0]["device_count"] == 1

    response = client.post(
        "/api/hub/credential/ssh_key/remove", json={"key_id": key_id}
    )
    assert response.status_code == 200
    assert response.json() == {"cleared": {"device_count": 1}}

    ssh = read_device_ssh(tmp_path)
    assert ssh["key_id"] is None
    assert ssh["host"] == "192.168.100.2"
    assert client.get("/api/hub/credential/ssh_key").json() == {"keys": []}


def test_key_refusals(client):
    pasted_public_key = client.post(
        "/api/hub/credential/ssh_key/add",
        json={"name": "wrong file", "private_key": PUBLIC_KEY},
    )
    assert pasted_public_key.status_code == 400
    assert pasted_public_key.json()["detail"]["code"] == "key_is_public"
    assert (
        client.post(
            "/api/hub/credential/ssh_key/remove", json={"key_id": "absent"}
        ).status_code
        == 200
    )


def test_login_roundtrip(client):
    assert client.get("/api/hub/credential/login").json() == {"logins": []}

    created = client.post(
        "/api/hub/credential/login/add",
        json={"name": "lab machines", "username": None, "password": STORED_PASSWORD},
    )
    assert created.status_code == 200
    view = created.json()
    assert view["name"] == "lab machines"
    assert view["username"] is None
    assert view["device_count"] == 0
    assert "password" not in view

    listed = client.get("/api/hub/credential/login").json()["logins"]
    assert [item["name"] for item in listed] == ["lab machines"]

    assert SecretVault().open(view["id"]) == {"password": STORED_PASSWORD}

    assert (
        client.post(
            "/api/hub/credential/login/remove", json={"login_id": view["id"]}
        ).status_code
        == 200
    )
    assert client.get("/api/hub/credential/login").json() == {"logins": []}


def test_a_login_with_a_username_seals_and_lists_it(client):
    created = client.post(
        "/api/hub/credential/login/add",
        json={
            "name": "NAS backup",
            "username": "backup",
            "password": STORED_ACCOUNT_PASSWORD,
        },
    )
    assert created.status_code == 200
    view = created.json()
    assert view["username"] == "backup"
    assert SecretVault().open(view["id"]) == {
        "username": "backup",
        "password": STORED_ACCOUNT_PASSWORD,
    }

    listed = client.get("/api/hub/credential/login").json()["logins"]
    assert listed[0]["username"] == "backup"


def test_login_refusals(client):
    blank_name = client.post(
        "/api/hub/credential/login/add",
        json={"name": "  ", "password": STORED_PASSWORD},
    )
    assert blank_name.status_code == 400
    blank_password = client.post(
        "/api/hub/credential/login/add", json={"name": "lab machines", "password": ""}
    )
    assert blank_password.status_code == 400
    assert blank_password.json()["detail"]["code"] == "login_password_needed"
    refused = client.post(
        "/api/hub/credential/login/remove", json={"login_id": "absent"}
    )
    assert refused.status_code == 404
    assert refused.json()["detail"]["code"] == "unknown_login"


def read_device_ssh(tmp_path) -> dict:
    """Read the stored test device's SSH block back off disk."""
    data = json.loads((tmp_path / "devices" / "devices.json").read_text())
    return data["devices"]["aa:bb:cc:dd:ee:ff"]["ssh"]


def test_deleting_a_login_clears_its_references(client, tmp_path):
    created = client.post(
        "/api/hub/credential/login/add",
        json={"name": "lab machines", "password": STORED_PASSWORD},
    )
    login_id = created.json()["id"]
    write_device(tmp_path, {"login_id": login_id})

    listed = client.get("/api/hub/credential/login").json()["logins"]
    assert listed[0]["device_count"] == 1

    response = client.post(
        "/api/hub/credential/login/remove", json={"login_id": login_id}
    )
    assert response.status_code == 200
    assert response.json() == {"cleared": {"device_count": 1}}

    ssh = read_device_ssh(tmp_path)
    assert ssh["login_id"] is None
    assert ssh["host"] == "192.168.100.2"
    assert ssh["username"] == "root"
    assert client.get("/api/hub/credential/login").json() == {"logins": []}


def test_deleting_an_unreferenced_login_touches_nothing(client, tmp_path):
    kept = client.post(
        "/api/hub/credential/login/add",
        json={"name": "kept", "password": STORED_PASSWORD},
    ).json()
    spare = client.post(
        "/api/hub/credential/login/add",
        json={"name": "spare", "password": STORED_PASSWORD},
    ).json()
    write_device(tmp_path, {"login_id": kept["id"]})

    response = client.post(
        "/api/hub/credential/login/remove", json={"login_id": spare["id"]}
    )

    assert response.status_code == 200
    assert response.json() == {"cleared": {"device_count": 0}}
    assert read_device_ssh(tmp_path)["login_id"] == kept["id"]


def test_a_login_of_another_kind_is_not_addressable(client):
    key = asyncssh.generate_private_key("ssh-ed25519")
    created = client.post(
        "/api/hub/credential/ssh_key/add",
        json={"name": "work laptop", "private_key": key.export_private_key().decode()},
    )
    key_id = created.json()["id"]
    assert client.get("/api/hub/credential/login").json() == {"logins": []}
    assert (
        client.post(
            "/api/hub/credential/login/remove", json={"login_id": key_id}
        ).status_code
        == 404
    )
    assert len(client.get("/api/hub/credential/ssh_key").json()["keys"]) == 1


def test_a_locked_vault_answers_with_its_code(client, tmp_path):
    (tmp_path / "state" / "vault.key").unlink()

    refused = client.post(
        "/api/hub/credential/login/add",
        json={"name": "lab machines", "password": STORED_PASSWORD},
    )

    assert refused.status_code == 400
    assert refused.json()["detail"] == {"code": "vault_locked", "params": {}}


# --- Tokens ---


def test_token_roundtrip(client):
    assert client.get("/api/hub/credential/token").json() == {"tokens": []}

    created = client.post(
        "/api/hub/credential/token/add",
        json={"name": "relay key", "value": "sk-one"},  # scan: allow
    )
    assert created.status_code == 200
    view = created.json()
    assert view["name"] == "relay key"
    assert view["provider_count"] == 0
    assert "value" not in view

    listed = client.get("/api/hub/credential/token").json()["tokens"]
    assert [item["name"] for item in listed] == ["relay key"]

    assert SecretVault().open(view["id"]) == {"value": "sk-one"}

    assert (
        client.post(
            "/api/hub/credential/token/remove", json={"token_id": view["id"]}
        ).status_code
        == 200
    )
    assert client.get("/api/hub/credential/token").json() == {"tokens": []}


def test_token_refusals(client):
    blank_value = client.post(
        "/api/hub/credential/token/add", json={"name": "relay key", "value": ""}
    )
    assert blank_value.status_code == 400
    assert blank_value.json()["detail"] == {"code": "token_value_needed", "params": {}}
    refused = client.post(
        "/api/hub/credential/token/remove", json={"token_id": "absent"}
    )
    assert refused.status_code == 404
    assert refused.json()["detail"]["code"] == "unknown_token"


def test_deleting_a_token_clears_provider_references(client):
    from neutrino_hub.modules.ai.registry import AiProviderRegistry

    created = client.post(
        "/api/hub/credential/token/add",
        json={"name": "relay key", "value": "sk-one"},  # scan: allow
    )
    token_id = created.json()["id"]
    AiProviderRegistry().add(
        name="relay", kind="custom", base_url="", secret_id=token_id
    )

    listed = client.get("/api/hub/credential/token").json()["tokens"]
    assert listed[0]["provider_count"] == 1

    response = client.post(
        "/api/hub/credential/token/remove", json={"token_id": token_id}
    )
    assert response.status_code == 200
    assert response.json() == {"cleared": {"provider_count": 1, "node_count": 0}}
    assert AiProviderRegistry().list_records()[0].secret_id is None
    assert client.get("/api/hub/credential/token").json() == {"tokens": []}


def write_node(tmp_path, secret_id: str) -> None:
    """Store one xray node whose secret reference names the token."""
    path = tmp_path / "xray"
    path.mkdir(parents=True, exist_ok=True)
    (path / "nodes.json").write_text(
        json.dumps(
            {
                "nodes": [
                    {
                        "id": "hk1",
                        "name": "Tokyo",
                        "address": "203.0.113.10",
                        "is_enabled": True,
                        "protocol": "shadowsocks",
                        "secret_id": secret_id,
                        "shadowsocks": {"port": 5800, "method": "aes-256-gcm"},
                    }
                ]
            }
        )
    )


@pytest.mark.feature("proxy")
def test_deleting_a_token_disables_the_nodes_it_keyed(client, tmp_path):
    created = client.post(
        "/api/hub/credential/token/add",
        json={"name": "node secret", "value": "sk-node"},  # scan: allow
    )
    token_id = created.json()["id"]
    write_node(tmp_path, token_id)

    listed = client.get("/api/hub/credential/token").json()["tokens"]
    assert listed[0]["node_count"] == 1
    assert listed[0]["provider_count"] == 0

    response = client.post(
        "/api/hub/credential/token/remove", json={"token_id": token_id}
    )
    assert response.status_code == 200
    assert response.json() == {"cleared": {"provider_count": 0, "node_count": 1}}

    node = json.loads((tmp_path / "xray" / "nodes.json").read_text())["nodes"][0]
    assert node["secret_id"] is None
    assert node["is_enabled"] is False
    assert client.get("/api/hub/credential/token").json() == {"tokens": []}


def test_deleting_a_token_leaves_unrelated_nodes_alone(client, tmp_path):
    created = client.post(
        "/api/hub/credential/token/add",
        json={"name": "spare key", "value": "sk-spare"},  # scan: allow
    )
    token_id = created.json()["id"]
    write_node(tmp_path, "0" * 32)

    response = client.post(
        "/api/hub/credential/token/remove", json={"token_id": token_id}
    )

    assert response.status_code == 200
    assert response.json() == {"cleared": {"provider_count": 0, "node_count": 0}}
    node = json.loads((tmp_path / "xray" / "nodes.json").read_text())["nodes"][0]
    assert node["secret_id"] == "0" * 32
    assert node["is_enabled"] is True


def test_a_token_of_another_kind_is_not_addressable(client):
    login = client.post(
        "/api/hub/credential/login/add",
        json={"name": "not a token", "password": STORED_PASSWORD},
    ).json()
    assert client.get("/api/hub/credential/token").json() == {"tokens": []}
    assert (
        client.post(
            "/api/hub/credential/token/remove", json={"token_id": login["id"]}
        ).status_code
        == 404
    )


class ConvergingRuntime:
    """A runtime whose converge step is counted."""

    def __init__(self):
        self.is_config_dirty = False
        self.converged = 0

    async def converge_network(self, *, only=None):
        self.converged += 1
        return []


def stored_key(client) -> str:
    key = asyncssh.generate_private_key("ssh-ed25519")
    created = client.post(
        "/api/hub/credential/ssh_key/add",
        json={"name": "relay", "private_key": key.export_private_key().decode()},
    )
    return created.json()["id"]


def test_the_key_the_relay_names_is_marked(client):
    key_id = stored_key(client)
    other_id = stored_key(client)
    write_relay(
        OverlayRelayConfig(is_enabled=True, host="vps", account="r", key_id=key_id)
    )

    listed = client.get("/api/hub/credential/ssh_key").json()["keys"]

    marks = {item["id"]: item["is_relay_key"] for item in listed}
    assert marks == {key_id: True, other_id: False}


def test_deleting_the_relays_key_clears_it_from_the_relay_and_converges(client):
    runtime = ConvergingRuntime()
    client.app.dependency_overrides[get_runtime] = lambda: runtime
    key_id = stored_key(client)
    write_relay(
        OverlayRelayConfig(is_enabled=True, host="vps", account="r", key_id=key_id)
    )

    response = client.post(
        "/api/hub/credential/ssh_key/remove", json={"key_id": key_id}
    )

    assert response.status_code == 200
    relay = read_relay()
    assert relay.key_id == ""
    assert (relay.is_enabled, relay.host) == (True, "vps")
    assert runtime.converged == 1


def test_deleting_another_key_leaves_the_relay_and_converges_nothing(client):
    runtime = ConvergingRuntime()
    client.app.dependency_overrides[get_runtime] = lambda: runtime
    key_id = stored_key(client)
    other_id = stored_key(client)
    write_relay(
        OverlayRelayConfig(is_enabled=True, host="vps", account="r", key_id=key_id)
    )

    client.post("/api/hub/credential/ssh_key/remove", json={"key_id": other_id})

    assert read_relay().key_id == key_id
    assert runtime.converged == 0


def stored_login(client) -> str:
    created = client.post(
        "/api/hub/credential/login/add",
        json={"name": "relay", "username": None, "password": STORED_PASSWORD},
    )
    return created.json()["id"]


def test_the_login_the_relay_names_is_marked(client):
    login_id = stored_login(client)
    other_id = stored_login(client)
    write_relay(
        OverlayRelayConfig(is_enabled=True, host="vps", account="r", login_id=login_id)
    )

    listed = client.get("/api/hub/credential/login").json()["logins"]

    marks = {item["id"]: item["is_relay_login"] for item in listed}
    assert marks == {login_id: True, other_id: False}


def test_deleting_the_relays_login_clears_it_from_the_relay_and_converges(client):
    runtime = ConvergingRuntime()
    client.app.dependency_overrides[get_runtime] = lambda: runtime
    login_id = stored_login(client)
    write_relay(
        OverlayRelayConfig(is_enabled=True, host="vps", account="r", login_id=login_id)
    )

    response = client.post(
        "/api/hub/credential/login/remove", json={"login_id": login_id}
    )

    assert response.status_code == 200
    relay = read_relay()
    assert relay.login_id == ""
    assert (relay.is_enabled, relay.host) == (True, "vps")
    assert runtime.converged == 1


def test_deleting_another_login_leaves_the_relay_and_converges_nothing(client):
    runtime = ConvergingRuntime()
    client.app.dependency_overrides[get_runtime] = lambda: runtime
    login_id = stored_login(client)
    other_id = stored_login(client)
    write_relay(
        OverlayRelayConfig(is_enabled=True, host="vps", account="r", login_id=login_id)
    )

    client.post("/api/hub/credential/login/remove", json={"login_id": other_id})

    assert read_relay().login_id == login_id
    assert runtime.converged == 0


# --- generated by the hub ---


class GeneratedRuntime:
    """A runtime over the real module files, recording pushes and events."""

    def __init__(self, *, is_online=True):
        from neutrino_hub.modules.devices.desired_state import DesiredStateStore

        self.is_config_dirty = False
        self.desired_states = DesiredStateStore()
        self.online = is_online
        self.pushed: list = []
        self.refreshed = 0
        self.published: list = []
        self.agent_sessions = SimpleNamespace(is_online=self._is_online)
        self.published_services = SimpleNamespace(schedule_refresh=self._refresh)
        self.events = SimpleNamespace(publish=self._publish)

    def device_names(self) -> dict:
        from neutrino_hub.modules.devices.registry import DeviceRegistry

        return {device.id: device.name for device in DeviceRegistry().all_stored()}

    def push_desired_state(self, key):
        self.pushed.append(key)

    def _is_online(self, key):
        return self.online

    def _refresh(self):
        self.refreshed += 1

    def _publish(self, event_type, key="", data=None):
        self.published.append((event_type, key))


@pytest.fixture
def generated(monkeypatch, tmp_path):
    """A machine whose file share and SSH server enable two accounts, with a
    seat password, behind the router."""
    from neutrino_hub.modules.devices.registry import DeviceRegistry

    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    unlock_vault(monkeypatch, tmp_path)
    runtime = GeneratedRuntime()
    device = DeviceRegistry().create("lab", machine_id="m1")
    states = runtime.desired_states
    states.write(
        device.id, "accounts", {"accounts": [{"account": "lab"}, {"account": "bob"}]}
    )
    states.set_enabled_accounts(device.id, "samba", ["lab", "bob"])
    states.set_enabled_accounts(device.id, "ssh_server", ["lab"])
    states.ensure_seat_password(device.id)
    app = FastAPI()
    app.add_exception_handler(VaultLockedError, _vault_locked)
    app.include_router(credentials_router.router)
    app.dependency_overrides[require_session] = lambda: None
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as test_client:
        yield test_client, runtime, device.id


def test_the_generated_list_names_each_secret_and_holds_no_value(generated):
    client, runtime, device_id = generated

    machines = client.get("/api/hub/credential/generated").json()["machines"]

    fingerprint = runtime.desired_states.account_key_fingerprint(device_id, "lab")
    assert fingerprint.startswith("SHA256:")
    assert machines == [
        {
            "device_id": device_id,
            "name": "lab",
            "items": [
                {"kind": "smb_password", "account": "lab", "fingerprint": ""},
                {"kind": "smb_password", "account": "bob", "fingerprint": ""},
                {"kind": "seat_password", "account": "", "fingerprint": ""},
                {"kind": "ssh_key", "account": "lab", "fingerprint": fingerprint},
            ],
        }
    ]


def test_reveal_opens_a_password_and_writes_its_line(generated, caplog):
    client, runtime, device_id = generated
    caplog.set_level("INFO", logger="neutrino_hub.web.routers.hub.credential")

    smb = client.post(
        "/api/hub/credential/generated/reveal",
        json={"device_id": device_id, "kind": "smb_password", "account": "bob"},
    )
    seat = client.post(
        "/api/hub/credential/generated/reveal",
        json={"device_id": device_id, "kind": "seat_password", "account": ""},
    )

    assert smb.json()["value"] == runtime.desired_states.account_secret(
        device_id, "samba", "bob", "password_sealed"
    )
    assert seat.json()["value"] == runtime.desired_states.seat_password(device_id)
    lines = [
        r.getMessage()
        for r in caplog.records
        if "credential_revealed" in r.getMessage()
    ]
    assert len(lines) == 2
    assert device_id in lines[0] and "smb_password bob" in lines[0]
    assert smb.json()["value"] not in lines[0]


def test_reveal_refuses_a_key_an_unknown_secret_and_a_locked_vault(generated, tmp_path):
    client, _, device_id = generated

    key = client.post(
        "/api/hub/credential/generated/reveal",
        json={"device_id": device_id, "kind": "ssh_key", "account": "lab"},
    )
    unknown = client.post(
        "/api/hub/credential/generated/reveal",
        json={"device_id": device_id, "kind": "smb_password", "account": "eve"},
    )
    (tmp_path / "state" / "vault.key").unlink()
    locked = client.post(
        "/api/hub/credential/generated/reveal",
        json={"device_id": device_id, "kind": "smb_password", "account": "lab"},
    )

    assert key.status_code == 400
    assert key.json()["detail"] == {
        "code": "unsupported_kind",
        "params": {"kind": "ssh_key"},
    }
    assert unknown.status_code == 404
    assert unknown.json()["detail"] == {
        "code": "generated_credential_unknown",
        "params": {},
    }
    assert locked.status_code == 400
    assert locked.json()["detail"]["code"] == "vault_locked"


@pytest.mark.parametrize(
    "kind, account",
    [("smb_password", "lab"), ("seat_password", ""), ("ssh_key", "lab")],
)
def test_rotate_seals_a_new_secret_and_pushes_the_machine(generated, kind, account):
    client, runtime, device_id = generated
    states = runtime.desired_states

    def current():
        if kind == "seat_password":
            return states.seat_password(device_id)
        if kind == "ssh_key":
            return states.account_key_fingerprint(device_id, account)
        return states.account_secret(device_id, "samba", account, "password_sealed")

    before = current()
    reply = client.post(
        "/api/hub/credential/generated/rotate",
        json={"device_id": device_id, "kind": kind, "account": account},
    )

    assert reply.status_code == 200
    assert current() and current() != before
    assert runtime.pushed == [device_id]
    assert runtime.refreshed == 1
    assert reply.json()["machines"][0]["device_id"] == device_id


def test_rotating_one_account_leaves_the_others(generated):
    client, runtime, device_id = generated
    states = runtime.desired_states
    bob = states.account_secret(device_id, "samba", "bob", "password_sealed")

    client.post(
        "/api/hub/credential/generated/rotate",
        json={"device_id": device_id, "kind": "smb_password", "account": "lab"},
    )

    assert states.account_secret(device_id, "samba", "bob", "password_sealed") == bob


def test_rotate_refuses_an_unknown_secret_and_waits_for_an_offline_machine(
    generated,
):
    client, runtime, device_id = generated
    runtime.online = False

    unknown = client.post(
        "/api/hub/credential/generated/rotate",
        json={"device_id": "gone", "kind": "seat_password", "account": ""},
    )
    offline = client.post(
        "/api/hub/credential/generated/rotate",
        json={"device_id": device_id, "kind": "ssh_key", "account": "lab"},
    )

    assert unknown.status_code == 404
    assert offline.status_code == 200
    assert runtime.pushed == []
