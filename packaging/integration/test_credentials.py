"""The Credentials page against a live box: four collections over one vault.

What matters here is what no unit test can promise about the running panel:
that secrets go in and never come back out, that a reference held by a device
blocks a delete, and that a passphrase backup leaves the master key out of the
tarball and a restore puts the whole vault back.

The backup roundtrip restores the same box's own config over itself, which is
safe on the disposable machines these tests are for and on nothing else.
"""

import io
import secrets
import subprocess
import tarfile
import tempfile
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


def test_password_lifecycle(panel):
    name = f"itest login {_suffix()}"
    status, created = panel.call(
        "POST",
        "/credentials/passwords",
        {"name": name, "password": "pw-one"},  # scan: allow
    )
    assert status == 200, created
    assert "password" not in created
    assert created["device_count"] == 0

    listed = panel.read("/credentials/passwords")["passwords"]
    assert any(entry["id"] == created["id"] for entry in listed)

    status, renamed = panel.call(
        "PUT", f"/credentials/passwords/{created['id']}", {"name": name + " renamed"}
    )
    assert status == 200 and renamed["name"] == name + " renamed"

    assert panel.status("DELETE", f"/credentials/passwords/{created['id']}") == 200
    listed = panel.read("/credentials/passwords")["passwords"]
    assert not any(entry["id"] == created["id"] for entry in listed)


def test_password_referenced_by_a_device_blocks_delete(panel):
    status, password = panel.call(
        "POST",
        "/credentials/passwords",
        {"name": f"itest sudo {_suffix()}", "password": "pw-sudo"},  # scan: allow
    )
    assert status == 200, password

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
                "password_id": password["id"],
                "sudo_password_id": password["id"],
            },
        },
    )
    assert status == 200, device
    ssh_view = device["ssh"]
    assert ssh_view["password_id"] == password["id"]
    assert "password" not in ssh_view and "sudo_password" not in ssh_view

    assert panel.status("DELETE", f"/credentials/passwords/{password['id']}") == 409
    assert (
        panel.status("DELETE", f"/credentials/passwords/{password['id']}?force=true")
        == 200
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


def test_service_account_lifecycle(panel):
    status, created = panel.call(
        "POST",
        "/credentials/service_accounts",
        {
            "name": f"itest nas {_suffix()}",
            "username": "smbuser",
            "password": "pw",  # scan: allow
        },
    )
    assert status == 200, created
    assert "password" not in created

    status, changed = panel.call(
        "PUT",
        f"/credentials/service_accounts/{created['id']}",
        {"username": "smbuser2"},
    )
    assert status == 200 and changed["username"] == "smbuser2"

    assert (
        panel.status("DELETE", f"/credentials/service_accounts/{created['id']}") == 200
    )


def test_ai_provider_key_is_write_only(panel):
    status, created = panel.call(
        "POST",
        "/credentials/ai_providers",
        {
            "name": f"itest relay {_suffix()}",
            "kind": "custom",
            "base_url": "https://relay.invalid/v1",
            "api_key": "sk-itest",  # scan: allow
        },
    )
    assert status == 200, created
    assert created["has_api_key"] is True
    assert "api_key" not in created

    status, kept = panel.call(
        "PUT", f"/credentials/ai_providers/{created['id']}", {"api_key": ""}
    )
    assert status == 200 and kept["has_api_key"] is True

    assert panel.status("DELETE", f"/credentials/ai_providers/{created['id']}") == 200


def test_backup_wraps_the_key_and_restores_the_vault(panel):
    marker = f"itest backup {_suffix()}"
    status, secret = panel.call(
        "POST",
        "/credentials/passwords",
        {"name": marker, "password": "pw-backup"},  # scan: allow
    )
    assert status == 200, secret

    status, plain = panel.download("POST", "/settings/backup", {"passphrase": ""})
    assert status == 200
    with tarfile.open(fileobj=io.BytesIO(plain), mode="r:gz") as archive:
        assert "config/credentials/vault.key" in archive.getnames()

    passphrase = "itest-roundtrip-pp"
    status, wrapped = panel.download(
        "POST", "/settings/backup", {"passphrase": passphrase}
    )
    assert status == 200
    with tarfile.open(fileobj=io.BytesIO(wrapped), mode="r:gz") as archive:
        names = archive.getnames()
        assert "config/credentials/vault.key" not in names
        assert "config/credentials/vault.key.new" not in names
        assert "config/credentials/vault.key.wrapped" in names

    status, refused = panel.upload(
        "/settings/restore", filename="backup.tar.gz", content=wrapped
    )
    assert status == 400 and refused["detail"]["code"] == "backup_passphrase_needed"

    status, refused = panel.upload(
        "/settings/restore",
        filename="backup.tar.gz",
        content=wrapped,
        fields={"passphrase": "not-the-passphrase"},
    )
    assert status == 400 and refused["detail"]["code"] == "backup_passphrase_wrong"

    status, restored = panel.upload(
        "/settings/restore",
        filename="backup.tar.gz",
        content=wrapped,
        fields={"passphrase": passphrase},
    )
    assert status == 200, restored
    assert restored["is_restored"] is True

    listed = panel.read("/credentials/passwords")["passwords"]
    survivor = next(entry for entry in listed if entry["name"] == marker)
    assert panel.status("DELETE", f"/credentials/passwords/{survivor['id']}") == 200
