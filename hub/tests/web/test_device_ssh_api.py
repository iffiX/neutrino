"""How a device's SSH block stores and echoes credential references.

A device's ssh block holds ids into the vault — ``key_id``, ``password_id``,
``sudo_password_id`` — and no secret material. What these pin is that a save
stores exactly the ids it was given, that a stale id is refused as a coded
400, and that no view of a device ever carries a plaintext password field.
"""

import json

import asyncssh
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.credentials.vault import SecretVault
from neutrino_hub.modules.devices.key_registry import KeyRegistry
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers import devices as devices_router
from tests.conftest import unlock_vault

MAC = "aa:bb:cc:dd:ee:ff"
LOGIN_PASSWORD = "a-password"  # scan: allow
SUDO_PASSWORD = "a-sudo-password"  # scan: allow


class FakeRuntime:
    def __init__(self):
        self.client_metrics = {}
        self.client_platform = {}


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    unlock_vault(monkeypatch, tmp_path)
    app = FastAPI()
    app.include_router(devices_router.router)
    app.dependency_overrides[require_session] = lambda: None
    app.dependency_overrides[get_runtime] = FakeRuntime
    with TestClient(app) as client:
        yield client, tmp_path


def stored_password(password: str) -> str:
    record = SecretVault().add(
        kind="password", name="a password", secret={"password": password}
    )
    return record.id


def stored_key() -> str:
    key = asyncssh.generate_private_key("ssh-ed25519")
    record = KeyRegistry().add(
        name="a key", private_key=key.export_private_key().decode()
    )
    return record.id


def annotate(client, ssh: dict):
    return client.put(
        f"/api/devices/{MAC}",
        json={
            "name": "xenode",
            "ssh": {"host": "192.168.100.2", "port": 22, "username": "iffi", **ssh},
        },
    )


def test_valid_references_are_stored_and_echoed(api):
    client, tmp_path = api
    password_id = stored_password(LOGIN_PASSWORD)
    sudo_password_id = stored_password(SUDO_PASSWORD)

    saved = annotate(
        client,
        {
            "auth": "password",
            "password_id": password_id,
            "sudo_password_id": sudo_password_id,
        },
    )

    assert saved.status_code == 200
    view = saved.json()["ssh"]
    assert view["password_id"] == password_id
    assert view["sudo_password_id"] == sudo_password_id
    assert "password" not in view
    assert "sudo_password" not in view

    stored = json.loads((tmp_path / "devices" / "devices.json").read_text())
    block = stored["devices"][MAC]["ssh"]
    assert block == {
        "host": "192.168.100.2",
        "port": 22,
        "username": "iffi",
        "auth": "password",
        "password_id": password_id,
        "sudo_password_id": sudo_password_id,
    }


def test_a_key_reference_is_stored_and_named(api):
    client, _ = api
    key_id = stored_key()

    saved = annotate(client, {"auth": "key", "key_id": key_id})

    assert saved.status_code == 200
    view = saved.json()["ssh"]
    assert view["key_id"] == key_id
    assert view["key_name"] == "a key"
    assert view["password_id"] is None
    assert view["sudo_password_id"] is None


def test_a_bogus_password_id_is_refused(api):
    client, tmp_path = api

    refused = annotate(client, {"auth": "password", "password_id": "absent"})

    assert refused.status_code == 400
    assert refused.json()["detail"] == {
        "code": "unknown_credential",
        "field": "password_id",
    }
    assert not (tmp_path / "devices" / "devices.json").exists()


def test_a_bogus_sudo_password_id_is_refused(api):
    client, _ = api
    password_id = stored_password(LOGIN_PASSWORD)

    refused = annotate(
        client,
        {
            "auth": "password",
            "password_id": password_id,
            "sudo_password_id": "absent",
        },
    )

    assert refused.status_code == 400
    assert refused.json()["detail"]["field"] == "sudo_password_id"


def test_a_password_id_offered_as_a_key_is_refused(api):
    client, _ = api
    password_id = stored_password(LOGIN_PASSWORD)

    refused = annotate(client, {"auth": "key", "key_id": password_id})

    assert refused.status_code == 400
    assert refused.json()["detail"] == {
        "code": "unknown_credential",
        "field": "key_id",
    }
