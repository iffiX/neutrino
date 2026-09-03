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

from neutrino_hub.modules.credentials.vault import SecretVault, VaultLockedError
from neutrino_hub.modules.services.config import DeclaredServiceRegistry, DeclaredShare
from neutrino_hub.web.app import _vault_locked
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers import credentials as credentials_router
from tests.conftest import unlock_vault

PUBLIC_KEY = "ssh-ed25519 AAAAC3Nz"  # scan: allow
STORED_PASSWORD = "hunter2hunter2"  # scan: allow
STORED_ACCOUNT_PASSWORD = "svc-pw-1"  # scan: allow
REPLACEMENT_PASSWORD = "next-one"  # scan: allow


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
                        "is_wol_enabled": False,
                        "ssh": {"host": "192.168.100.2", "username": "root", **ssh},
                    }
                }
            }
        )
    )


def test_key_roundtrip(client):
    key = asyncssh.generate_private_key("ssh-ed25519")
    created = client.post(
        "/api/credentials/ssh_keys",
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

    listed = client.get("/api/credentials/ssh_keys").json()["keys"]
    assert [item["name"] for item in listed] == ["work laptop"]

    renamed = client.put(
        f"/api/credentials/ssh_keys/{view['id']}", json={"name": "home desktop"}
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "home desktop"

    assert client.delete(f"/api/credentials/ssh_keys/{view['id']}").status_code == 200
    assert client.get("/api/credentials/ssh_keys").json() == {"keys": []}


def test_deleting_a_key_clears_device_references(client, tmp_path):
    key = asyncssh.generate_private_key("ssh-ed25519")
    created = client.post(
        "/api/credentials/ssh_keys",
        json={"name": "work laptop", "private_key": key.export_private_key().decode()},
    )
    key_id = created.json()["id"]
    write_device(tmp_path, {"key_id": key_id})

    listed = client.get("/api/credentials/ssh_keys").json()["keys"]
    assert listed[0]["device_count"] == 1

    response = client.delete(f"/api/credentials/ssh_keys/{key_id}")
    assert response.status_code == 200
    assert response.json() == {"cleared": {"device_count": 1}}

    ssh = read_device_ssh(tmp_path)
    assert ssh["key_id"] is None
    assert ssh["host"] == "192.168.100.2"
    assert client.get("/api/credentials/ssh_keys").json() == {"keys": []}


def test_key_refusals(client):
    pasted_public_key = client.post(
        "/api/credentials/ssh_keys",
        json={"name": "wrong file", "private_key": PUBLIC_KEY},
    )
    assert pasted_public_key.status_code == 400
    assert "public key" in pasted_public_key.json()["detail"]
    assert (
        client.put(
            "/api/credentials/ssh_keys/absent", json={"name": "anything"}
        ).status_code
        == 404
    )
    assert client.delete("/api/credentials/ssh_keys/absent").status_code == 200


def test_login_roundtrip(client):
    assert client.get("/api/credentials/logins").json() == {"logins": []}

    created = client.post(
        "/api/credentials/logins",
        json={"name": "lab machines", "username": None, "password": STORED_PASSWORD},
    )
    assert created.status_code == 200
    view = created.json()
    assert view["name"] == "lab machines"
    assert view["username"] is None
    assert view["device_count"] == 0
    assert view["service_count"] == 0
    assert "password" not in view

    listed = client.get("/api/credentials/logins").json()["logins"]
    assert [item["name"] for item in listed] == ["lab machines"]

    renamed = client.put(
        f"/api/credentials/logins/{view['id']}", json={"name": "workshop"}
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "workshop"
    assert SecretVault().open(view["id"]) == {"password": STORED_PASSWORD}

    blank_password = client.put(
        f"/api/credentials/logins/{view['id']}", json={"password": ""}
    )
    assert blank_password.status_code == 200
    assert SecretVault().open(view["id"]) == {"password": STORED_PASSWORD}

    replaced = client.put(
        f"/api/credentials/logins/{view['id']}",
        json={"password": REPLACEMENT_PASSWORD},
    )
    assert replaced.status_code == 200
    assert SecretVault().open(view["id"]) == {"password": REPLACEMENT_PASSWORD}

    assert client.delete(f"/api/credentials/logins/{view['id']}").status_code == 200
    assert client.get("/api/credentials/logins").json() == {"logins": []}


def test_a_login_with_a_username_seals_and_lists_it(client):
    created = client.post(
        "/api/credentials/logins",
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

    listed = client.get("/api/credentials/logins").json()["logins"]
    assert listed[0]["username"] == "backup"

    renamed_user = client.put(
        f"/api/credentials/logins/{view['id']}",
        json={"name": "NAS archive", "username": "archive"},
    )
    assert renamed_user.status_code == 200
    assert renamed_user.json()["name"] == "NAS archive"
    assert renamed_user.json()["username"] == "archive"
    assert SecretVault().open(view["id"]) == {
        "username": "archive",
        "password": STORED_ACCOUNT_PASSWORD,
    }

    replaced = client.put(
        f"/api/credentials/logins/{view['id']}",
        json={"password": REPLACEMENT_PASSWORD},
    )
    assert replaced.status_code == 200
    assert replaced.json()["username"] == "archive"
    assert SecretVault().open(view["id"]) == {
        "username": "archive",
        "password": REPLACEMENT_PASSWORD,
    }


def test_a_username_sent_as_null_clears_the_stored_one(client):
    created = client.post(
        "/api/credentials/logins",
        json={"name": "NAS", "username": "backup", "password": STORED_PASSWORD},
    ).json()

    cleared = client.put(
        f"/api/credentials/logins/{created['id']}",
        json={"name": "NAS", "username": None},
    )

    assert cleared.status_code == 200
    assert cleared.json()["username"] is None
    listed = client.get("/api/credentials/logins").json()["logins"]
    assert listed[0]["username"] is None


def test_an_absent_username_keeps_the_stored_one(client):
    created = client.post(
        "/api/credentials/logins",
        json={"name": "NAS", "username": "backup", "password": STORED_PASSWORD},
    ).json()

    kept = client.put(
        f"/api/credentials/logins/{created['id']}", json={"name": "NAS renamed"}
    )

    assert kept.status_code == 200
    assert kept.json()["username"] == "backup"


def test_login_refusals(client):
    blank_name = client.post(
        "/api/credentials/logins", json={"name": "  ", "password": STORED_PASSWORD}
    )
    assert blank_name.status_code == 400
    blank_password = client.post(
        "/api/credentials/logins", json={"name": "lab machines", "password": ""}
    )
    assert blank_password.status_code == 400
    assert blank_password.json()["detail"]["code"] == "login_password_needed"
    refused = client.put("/api/credentials/logins/absent", json={"name": "x"})
    assert refused.status_code == 404
    assert refused.json()["detail"]["code"] == "unknown_login"
    assert client.delete("/api/credentials/logins/absent").status_code == 404


def declare_samba_share(login_id: str) -> None:
    """Store one declared Samba service whose share names the login."""
    DeclaredServiceRegistry().add(
        name="nas",
        kind="samba",
        host="192.168.100.7",
        port=None,
        shares=[DeclaredShare(name="media", login_id=login_id)],
    )


def read_device_ssh(tmp_path) -> dict:
    """Read the stored test device's SSH block back off disk."""
    data = json.loads((tmp_path / "devices" / "devices.json").read_text())
    return data["devices"]["aa:bb:cc:dd:ee:ff"]["ssh"]


def read_shares(tmp_path) -> list:
    """Read the declared Samba service's shares back off disk."""
    data = json.loads((tmp_path / "services" / "declared.json").read_text())
    return data["services"][0]["shares"]


def test_deleting_a_login_clears_its_references(client, tmp_path):
    created = client.post(
        "/api/credentials/logins",
        json={"name": "lab machines", "password": STORED_PASSWORD},
    )
    login_id = created.json()["id"]
    write_device(tmp_path, {"password_id": login_id, "sudo_password_id": login_id})
    declare_samba_share(login_id)

    listed = client.get("/api/credentials/logins").json()["logins"]
    assert listed[0]["device_count"] == 1
    assert listed[0]["service_count"] == 1

    response = client.delete(f"/api/credentials/logins/{login_id}")
    assert response.status_code == 200
    assert response.json() == {"cleared": {"device_count": 1, "service_count": 1}}

    ssh = read_device_ssh(tmp_path)
    assert ssh["password_id"] is None
    assert ssh["sudo_password_id"] is None
    assert ssh["host"] == "192.168.100.2"
    assert ssh["username"] == "root"
    assert read_shares(tmp_path) == [{"name": "media", "login_id": None}]
    assert client.get("/api/credentials/logins").json() == {"logins": []}


def test_deleting_an_unreferenced_login_touches_nothing(client, tmp_path):
    kept = client.post(
        "/api/credentials/logins",
        json={"name": "kept", "password": STORED_PASSWORD},
    ).json()
    spare = client.post(
        "/api/credentials/logins",
        json={"name": "spare", "password": STORED_PASSWORD},
    ).json()
    write_device(tmp_path, {"password_id": kept["id"]})
    declare_samba_share(kept["id"])

    response = client.delete(f"/api/credentials/logins/{spare['id']}")

    assert response.status_code == 200
    assert response.json() == {"cleared": {"device_count": 0, "service_count": 0}}
    assert read_device_ssh(tmp_path)["password_id"] == kept["id"]
    assert read_shares(tmp_path) == [{"name": "media", "login_id": kept["id"]}]


def test_a_login_of_another_kind_is_not_addressable(client):
    key = asyncssh.generate_private_key("ssh-ed25519")
    created = client.post(
        "/api/credentials/ssh_keys",
        json={"name": "work laptop", "private_key": key.export_private_key().decode()},
    )
    key_id = created.json()["id"]
    assert client.get("/api/credentials/logins").json() == {"logins": []}
    assert (
        client.put(f"/api/credentials/logins/{key_id}", json={"name": "x"}).status_code
        == 404
    )
    assert client.delete(f"/api/credentials/logins/{key_id}").status_code == 404
    assert len(client.get("/api/credentials/ssh_keys").json()["keys"]) == 1


def test_a_locked_vault_answers_with_its_code(client, tmp_path):
    (tmp_path / "state" / "vault.key").unlink()

    refused = client.post(
        "/api/credentials/logins",
        json={"name": "lab machines", "password": STORED_PASSWORD},
    )

    assert refused.status_code == 400
    assert refused.json()["detail"] == {"code": "vault_locked", "params": {}}


# --- Tokens ---


def test_token_roundtrip(client):
    assert client.get("/api/credentials/tokens").json() == {"tokens": []}

    created = client.post(
        "/api/credentials/tokens",
        json={"name": "relay key", "value": "sk-one"},  # scan: allow
    )
    assert created.status_code == 200
    view = created.json()
    assert view["name"] == "relay key"
    assert view["provider_count"] == 0
    assert "value" not in view

    listed = client.get("/api/credentials/tokens").json()["tokens"]
    assert [item["name"] for item in listed] == ["relay key"]

    renamed = client.put(
        f"/api/credentials/tokens/{view['id']}", json={"name": "relay key 2"}
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "relay key 2"
    assert SecretVault().open(view["id"]) == {"value": "sk-one"}

    blank_value = client.put(
        f"/api/credentials/tokens/{view['id']}", json={"value": ""}
    )
    assert blank_value.status_code == 200
    assert SecretVault().open(view["id"]) == {"value": "sk-one"}

    replaced = client.put(
        f"/api/credentials/tokens/{view['id']}", json={"value": "sk-two"}  # scan: allow
    )
    assert replaced.status_code == 200
    assert SecretVault().open(view["id"]) == {"value": "sk-two"}

    assert client.delete(f"/api/credentials/tokens/{view['id']}").status_code == 200
    assert client.get("/api/credentials/tokens").json() == {"tokens": []}


def test_token_refusals(client):
    blank_value = client.post(
        "/api/credentials/tokens", json={"name": "relay key", "value": ""}
    )
    assert blank_value.status_code == 400
    assert blank_value.json()["detail"] == {"code": "token_value_needed", "params": {}}
    refused = client.put("/api/credentials/tokens/absent", json={"name": "x"})
    assert refused.status_code == 404
    assert refused.json()["detail"]["code"] == "unknown_token"
    assert client.delete("/api/credentials/tokens/absent").status_code == 404


def test_deleting_a_token_clears_provider_references(client):
    from neutrino_hub.modules.ai.registry import AiProviderRegistry

    created = client.post(
        "/api/credentials/tokens",
        json={"name": "relay key", "value": "sk-one"},  # scan: allow
    )
    token_id = created.json()["id"]
    AiProviderRegistry().add(
        name="relay", kind="custom", base_url="", secret_id=token_id
    )

    listed = client.get("/api/credentials/tokens").json()["tokens"]
    assert listed[0]["provider_count"] == 1

    response = client.delete(f"/api/credentials/tokens/{token_id}")
    assert response.status_code == 200
    assert response.json() == {"cleared": {"provider_count": 1, "node_count": 0}}
    assert AiProviderRegistry().list_records()[0].secret_id is None
    assert client.get("/api/credentials/tokens").json() == {"tokens": []}


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


def test_deleting_a_token_disables_the_nodes_it_keyed(client, tmp_path):
    created = client.post(
        "/api/credentials/tokens",
        json={"name": "node secret", "value": "sk-node"},  # scan: allow
    )
    token_id = created.json()["id"]
    write_node(tmp_path, token_id)

    listed = client.get("/api/credentials/tokens").json()["tokens"]
    assert listed[0]["node_count"] == 1
    assert listed[0]["provider_count"] == 0

    response = client.delete(f"/api/credentials/tokens/{token_id}")
    assert response.status_code == 200
    assert response.json() == {"cleared": {"provider_count": 0, "node_count": 1}}

    node = json.loads((tmp_path / "xray" / "nodes.json").read_text())["nodes"][0]
    assert node["secret_id"] is None
    assert node["is_enabled"] is False
    assert client.get("/api/credentials/tokens").json() == {"tokens": []}


def test_deleting_a_token_leaves_unrelated_nodes_alone(client, tmp_path):
    created = client.post(
        "/api/credentials/tokens",
        json={"name": "spare key", "value": "sk-spare"},  # scan: allow
    )
    token_id = created.json()["id"]
    write_node(tmp_path, "0" * 32)

    response = client.delete(f"/api/credentials/tokens/{token_id}")

    assert response.status_code == 200
    assert response.json() == {"cleared": {"provider_count": 0, "node_count": 0}}
    node = json.loads((tmp_path / "xray" / "nodes.json").read_text())["nodes"][0]
    assert node["secret_id"] == "0" * 32
    assert node["is_enabled"] is True


def test_a_token_of_another_kind_is_not_addressable(client):
    login = client.post(
        "/api/credentials/logins",
        json={"name": "not a token", "password": STORED_PASSWORD},
    ).json()
    assert client.get("/api/credentials/tokens").json() == {"tokens": []}
    assert (
        client.put(
            f"/api/credentials/tokens/{login['id']}", json={"name": "x"}
        ).status_code
        == 404
    )
    assert client.delete(f"/api/credentials/tokens/{login['id']}").status_code == 404
