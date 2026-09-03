"""The Credentials tab's API.

The provider, key and login quarters of the router share one file, and each
serializes through its own view helper. The provider
endpoints once broke without any test noticing — a second helper of the same
name shadowed the first at import — so this file walks every endpoint end to
end.
"""

import json

import asyncssh
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.credentials.vault import SecretVault, VaultLockedError
from neutrino_hub.web.app import _vault_locked
from neutrino_hub.web.dependencies import require_session
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


def test_provider_roundtrip(client):
    assert client.get("/api/credentials/ai_providers").json() == {"providers": []}

    created = client.post(
        "/api/credentials/ai_providers",
        json={
            "name": "Anthropic direct",
            "kind": "anthropic",
            "base_url": "",
            "api_key": "sk-test",  # scan: allow
            "models": [{"name": "claude-sonnet-4-5", "alias": "sonnet"}],
        },
    )
    assert created.status_code == 200
    view = created.json()
    assert view["has_api_key"] is True
    assert "api_key" not in view

    listed = client.get("/api/credentials/ai_providers").json()["providers"]
    assert [p["name"] for p in listed] == ["Anthropic direct"]

    updated = client.put(
        f"/api/credentials/ai_providers/{view['id']}",
        json={"name": "Renamed", "api_key": ""},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Renamed"
    assert updated.json()["has_api_key"] is True

    assert (
        client.delete(f"/api/credentials/ai_providers/{view['id']}").status_code == 200
    )
    assert client.get("/api/credentials/ai_providers").json() == {"providers": []}


def test_provider_refusals(client):
    unknown_kind = client.post(
        "/api/credentials/ai_providers",
        json={"name": "x", "kind": "nonsense", "base_url": "", "api_key": "k"},
    )
    assert unknown_kind.status_code == 400
    assert (
        client.put("/api/credentials/ai_providers/absent", json={}).status_code == 404
    )
    assert client.delete("/api/credentials/ai_providers/absent").status_code == 404


def test_key_listing_is_untouched_by_provider_traffic(client):
    client.post(
        "/api/credentials/ai_providers",
        json={"name": "p", "kind": "openai", "base_url": "", "api_key": "k"},
    )
    assert client.get("/api/credentials/ssh_keys").json() == {"keys": []}


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
        json={"name": "lab machines", "password": STORED_PASSWORD},
    )
    assert created.status_code == 200
    view = created.json()
    assert view["name"] == "lab machines"
    assert view["username"] == ""
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


def test_a_login_is_not_pulled_out_from_under_a_device(client, tmp_path):
    created = client.post(
        "/api/credentials/logins",
        json={"name": "lab machines", "password": STORED_PASSWORD},
    )
    login_id = created.json()["id"]
    write_device(tmp_path, {"password_id": login_id, "sudo_password_id": login_id})

    listed = client.get("/api/credentials/logins").json()["logins"]
    assert listed[0]["device_count"] == 1

    refused = client.delete(f"/api/credentials/logins/{login_id}")
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "login_in_use"
    assert refused.json()["detail"]["params"]["device_count"] == 1

    forced = client.delete(f"/api/credentials/logins/{login_id}?force=true")
    assert forced.status_code == 200
    assert client.get("/api/credentials/logins").json() == {"logins": []}


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
