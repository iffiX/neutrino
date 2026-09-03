"""The Credentials and AI pages against a live box, and the backup roundtrip.

What matters here is what no unit test can promise about the running panel:
that secrets go in and never come back out, that a reference held by a device
blocks a delete, and that a backup proves itself — manifest, every member's
digest, the vault passphrase opening the wrapped key — before a restore puts
the whole vault back.

The backup roundtrip restores the same box's own config over itself, which is
safe on the disposable machines these tests are for and on nothing else.
"""

import hashlib
import io
import os
import json
import secrets
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path

import pytest

TEST_MAC = "02:00:00:00:00:71"


def _suffix() -> str:
    return secrets.token_hex(3)


def _throwaway_key_text() -> str:
    """A fresh ed25519 private key, generated locally and used nowhere."""
    keygen = subprocess.run(["which", "ssh-keygen"], capture_output=True)
    if keygen.returncode != 0:
        pytest.skip("ssh-keygen is not on this machine")
    with tempfile.TemporaryDirectory() as workdir:
        path = Path(workdir) / "key"
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-N", "", "-q", "-f", str(path)],
            check=True,
        )
        return path.read_text()


def test_login_lifecycle(panel):
    name = f"itest login {_suffix()}"
    status, created = panel.call(
        "POST",
        "/credentials/logins",
        {"name": name, "password": "pw-one"},  # scan: allow
    )
    assert status == 200, created
    assert "password" not in created
    assert created["device_count"] == 0
    assert created["service_count"] == 0

    listed = panel.read("/credentials/logins")["logins"]
    assert any(entry["id"] == created["id"] for entry in listed)

    status, renamed = panel.call(
        "PUT", f"/credentials/logins/{created['id']}", {"name": name + " renamed"}
    )
    assert status == 200 and renamed["name"] == name + " renamed"

    assert panel.status("DELETE", f"/credentials/logins/{created['id']}") == 200
    listed = panel.read("/credentials/logins")["logins"]
    assert not any(entry["id"] == created["id"] for entry in listed)


def test_a_login_carries_its_username_but_never_its_password(panel):
    status, created = panel.call(
        "POST",
        "/credentials/logins",
        {
            "name": f"itest nas {_suffix()}",
            "username": "smbuser",
            "password": "pw",  # scan: allow
        },
    )
    assert status == 200, created
    assert created["username"] == "smbuser"
    assert "password" not in created

    status, changed = panel.call(
        "PUT", f"/credentials/logins/{created['id']}", {"username": "smbuser2"}
    )
    assert status == 200 and changed["username"] == "smbuser2"

    assert panel.status("DELETE", f"/credentials/logins/{created['id']}") == 200


def test_a_login_referenced_by_a_device_blocks_delete(panel):
    status, login = panel.call(
        "POST",
        "/credentials/logins",
        {"name": f"itest sudo {_suffix()}", "password": "pw-sudo"},  # scan: allow
    )
    assert status == 200, login

    status, device = panel.call(
        "PUT",
        f"/devices/{TEST_MAC}",
        {
            "name": "itest box",
            "ssh": {
                "host": "192.0.2.71",
                "port": 22,
                "username": "itest",
                "auth": "password",
                "password_id": login["id"],
                "sudo_password_id": login["id"],
            },
        },
    )
    assert status == 200, device
    ssh_view = device["ssh"]
    assert ssh_view["password_id"] == login["id"]
    assert "password" not in ssh_view and "sudo_password" not in ssh_view

    status, refused = panel.call("DELETE", f"/credentials/logins/{login['id']}")
    assert status == 409
    assert refused["detail"]["code"] == "login_in_use"
    assert (
        panel.status("DELETE", f"/credentials/logins/{login['id']}?force=true") == 200
    )
    assert panel.status("DELETE", f"/devices/{TEST_MAC}") == 200


def test_device_refuses_a_bogus_credential_reference(panel):
    status, answer = panel.call(
        "PUT",
        f"/devices/{TEST_MAC}",
        {
            "name": "itest box",
            "ssh": {
                "host": "192.0.2.71",
                "port": 22,
                "username": "itest",
                "auth": "password",
                "password_id": "0" * 32,
            },
        },
    )
    assert status == 400, answer
    assert answer["detail"]["code"] == "unknown_credential"
    panel.call("DELETE", f"/devices/{TEST_MAC}")


def test_ssh_key_material_never_reads_back(panel):
    status, created = panel.call(
        "POST",
        "/credentials/ssh_keys",
        {"name": f"itest key {_suffix()}", "private_key": _throwaway_key_text()},
    )
    assert status == 200, created
    assert created["fingerprint"].startswith("SHA256:")
    assert "private_key" not in created and "passphrase" not in created

    assert panel.status("DELETE", f"/credentials/ssh_keys/{created['id']}") == 200


def test_a_provider_references_a_token_and_outlives_neither_way(panel):
    status, token = panel.call(
        "POST",
        "/credentials/tokens",
        {"name": f"itest relay key {_suffix()}", "value": "sk-itest"},  # scan: allow
    )
    assert status == 200, token
    assert "value" not in token

    status, created = panel.call(
        "POST",
        "/ai/providers",
        {
            "name": f"itest relay {_suffix()}",
            "kind": "custom",
            "base_url": "https://relay.invalid/v1",
            "secret_id": token["id"],
        },
    )
    assert status == 200, created
    assert created["secret_id"] == token["id"]
    assert "api_key" not in created

    listed = panel.read("/credentials/tokens")["tokens"]
    referenced = next(entry for entry in listed if entry["id"] == token["id"])
    assert referenced["provider_count"] == 1

    status, refused = panel.call("DELETE", f"/credentials/tokens/{token['id']}")
    assert status == 409, refused
    assert refused["detail"]["code"] == "token_in_use"
    assert refused["detail"]["params"]["provider_count"] == 1

    assert panel.status("DELETE", f"/ai/providers/{created['id']}") == 200
    # The provider is gone; the token stays until deleted on its own page.
    assert panel.status("DELETE", f"/credentials/tokens/{token['id']}") == 200


def test_a_provider_refuses_a_bogus_token_reference(panel):
    status, answer = panel.call(
        "POST",
        "/ai/providers",
        {
            "name": f"itest relay {_suffix()}",
            "kind": "custom",
            "base_url": "https://relay.invalid/v1",
            "secret_id": "0" * 32,
        },
    )
    assert status == 400, answer
    assert answer["detail"] == {
        "code": "unknown_credential",
        "params": {"field": "secret_id"},
    }


def _archive_contents(archive_bytes: bytes) -> dict:
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as archive:
        return {
            member.name: archive.extractfile(member).read()
            for member in archive.getmembers()
            if member.isreg()
        }


def test_backup_is_plain_digested_and_restores_the_vault(panel, vault_passphrase):
    marker = f"itest backup {_suffix()}"
    status, secret = panel.call(
        "POST",
        "/credentials/logins",
        {"name": marker, "password": "pw-backup"},  # scan: allow
    )
    assert status == 200, secret

    status, archive_bytes = panel.download("POST", "/settings/backup")
    assert status == 200
    contents = _archive_contents(archive_bytes)
    names = list(contents)
    assert names[0] == "neutrino_backup.json"
    assert names[1] == "SHA256SUMS"
    assert json.loads(contents["neutrino_backup.json"]) == {
        "kind": "neutrino_config_backup",
        "version": 2,
    }

    listed = {}
    for line in contents["SHA256SUMS"].decode().splitlines():
        digest, _, member_path = line.partition("  ")
        listed[member_path] = digest
    for name in names[2:]:
        assert name.startswith("config/")
        relative = name[len("config/") :]
        assert listed[relative] == hashlib.sha256(contents[name]).hexdigest()

    # The vault travels wrapped: no key file, and the store carries the wrap.
    assert not any(name.endswith("vault.key") for name in names)
    store = json.loads(contents["config/credentials/vault.json"])
    assert "wrapped_key" in store
    assert "pw-backup" not in contents["config/credentials/vault.json"].decode()

    status, refused = panel.upload(
        "/settings/restore", filename="backup.bin", content=archive_bytes
    )
    assert status == 400 and refused["detail"]["code"] == "backup_wrong_extension"

    status, refused = panel.upload(
        "/settings/restore", filename="backup.tar.gz", content=archive_bytes
    )
    assert status == 400 and refused["detail"]["code"] == "vault_passphrase_needed"

    status, refused = panel.upload(
        "/settings/restore",
        filename="backup.tar.gz",
        content=archive_bytes,
        fields={"vault_passphrase": "Not-the-passphrase-1!"},
    )
    assert status == 400 and refused["detail"]["code"] == "vault_passphrase_wrong"

    status, restored = panel.upload(
        "/settings/restore",
        filename="backup.tar.gz",
        content=archive_bytes,
        fields={"vault_passphrase": vault_passphrase},
    )
    assert status == 200, restored
    assert restored["is_restored"] is True

    # The restore applies itself and restarts the panel. The upload returns
    # before any of that happens, so waiting for a working login is not
    # enough — the OLD panel still answers. The restart is only over once
    # the panel has been seen down and then up again.
    deadline = time.monotonic() + 150
    is_down_seen = False
    while time.monotonic() < deadline:
        time.sleep(2)
        # A dead socket reads as status 0 by the client's own contract.
        code = panel.status("GET", "/auth/session")
        if code == 0:
            is_down_seen = True
            continue
        if is_down_seen:
            break
    else:
        raise AssertionError("the panel never restarted after the restore")
    panel.sign_in(os.environ["NEUTRINO_PANEL_PASSWORD"])

    listed = panel.read("/credentials/logins")["logins"]
    survivor = next(entry for entry in listed if entry["name"] == marker)
    assert panel.status("DELETE", f"/credentials/logins/{survivor['id']}") == 200
