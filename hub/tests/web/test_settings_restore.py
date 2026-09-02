"""What a config backup carries out of the box, and writes when unpacked.

Restore runs as root, so an archive is hostile input even though the person
uploading it is signed in: backups get passed around, and one built elsewhere
can name any path it likes. A member whose name merely starts with `config/`
proves nothing — `config/../../etc/passwd` starts that way — so what these
pin is that the destination is checked after the path resolves.

The passphrase half pins the order. A sealed archive is settled in memory
before a byte is written, so a refused restore is one that changed nothing,
and the master key is installed last, so no interruption leaves a restored
store nothing can open.
"""

import hashlib
import io
import json
import tarfile

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import neutrino_hub.utils.json_file
from neutrino_hub.modules.credentials.vault import (
    SecretVault,
    VAULT_SEALED_MAGIC,
    unseal_bytes,
)
from neutrino_hub.web.dependencies import require_session
from neutrino_hub.web.routers import settings as settings_router
from neutrino_hub.web.routers.settings import _checked_member

PASSPHRASE = "correct horse battery"  # scan: allow
SEALED_PASSWORD = "hunter2hunter2"  # scan: allow
KEY_MEMBER = "config/credentials/vault.key"


def member(name: str, kind: bytes = tarfile.REGTYPE) -> tarfile.TarInfo:
    """One archive entry of a given name and type."""
    entry = tarfile.TarInfo(name)
    entry.type = kind
    entry.size = 0
    return entry


@pytest.mark.parametrize(
    "name",
    [
        "config",
        "config/",
        "config/xray/nodes.json",
        "config/credentials/vault.json",
        "config/sub/../still_inside.json",
    ],
)
def test_paths_inside_config_are_accepted(name):
    assert _checked_member(member(name)).name == name


@pytest.mark.parametrize(
    "name",
    [
        "config/../../etc/passwd",
        "config/../../../root/.ssh/authorized_keys",
        "config/../.gitignore",
        "/etc/passwd",
        "../etc/passwd",
        "etc/passwd",
        "",
    ],
)
def test_paths_that_would_land_outside_config_are_refused(name):
    with pytest.raises(HTTPException) as raised:
        _checked_member(member(name))
    assert raised.value.status_code == 400


@pytest.mark.parametrize(
    "kind",
    [
        tarfile.SYMTYPE,
        tarfile.LNKTYPE,
        tarfile.CHRTYPE,
        tarfile.BLKTYPE,
        tarfile.FIFOTYPE,
    ],
)
def test_only_files_and_directories_are_unpacked(kind):
    with pytest.raises(HTTPException) as raised:
        _checked_member(member("config/anything", kind))
    assert raised.value.status_code == 400


def test_a_directory_inside_config_is_accepted():
    assert _checked_member(member("config/xray", tarfile.DIRTYPE)).isdir()


@pytest.fixture
def client(monkeypatch, tmp_path):
    """The Settings router over a config directory of its own."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr(
        neutrino_hub.utils.json_file, "UTILS_CONFIG_DIR", config_dir, raising=True
    )
    monkeypatch.setattr(settings_router, "UTILS_CONFIG_DIR", config_dir, raising=True)
    app = FastAPI()
    app.include_router(settings_router.router)
    app.dependency_overrides[require_session] = lambda: None
    with TestClient(app) as opened:
        yield opened, config_dir


def seed_config(config_dir) -> str:
    """Store one sealed secret and one ordinary file, as a live box would."""
    (config_dir / "xray").mkdir()
    (config_dir / "xray" / "nodes.json").write_text(json.dumps({"nodes": []}))
    record = SecretVault().add(
        kind="password", name="a password", secret={"password": SEALED_PASSWORD}
    )
    return record.id


def wipe_config(config_dir) -> None:
    """Leave the box with an empty ``config/``, as a fresh machine has."""
    for path in sorted(config_dir.rglob("*"), reverse=True):
        path.unlink() if path.is_file() else path.rmdir()


def download_backup(opened, passphrase: str) -> bytes:
    """Ask for a backup and hand back the envelope."""
    response = opened.post("/api/settings/backup", json={"passphrase": passphrase})
    assert response.status_code == 200
    return response.content


def read_manifest(envelope: bytes) -> dict:
    with tarfile.open(fileobj=io.BytesIO(envelope), mode="r:gz") as archive:
        assert archive.getmembers()[0].name == "neutrino_backup.json"
        return json.loads(archive.extractfile("neutrino_backup.json").read())


def read_payload(envelope: bytes) -> bytes:
    manifest = read_manifest(envelope)
    with tarfile.open(fileobj=io.BytesIO(envelope), mode="r:gz") as archive:
        return archive.extractfile(manifest["payload"]).read()


def inner_names(envelope: bytes, passphrase: str = "") -> list[str]:
    payload = read_payload(envelope)
    if passphrase:
        payload = unseal_bytes(payload, passphrase)
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        return archive.getnames()


def repacked(manifest: dict, payload: bytes) -> bytes:
    """An envelope built by hand, for the tests that forge or damage one."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, blob in (
            ("neutrino_backup.json", json.dumps(manifest).encode()),
            (manifest.get("payload", "config.tar.gz"), payload),
        ):
            entry = tarfile.TarInfo(name)
            entry.size = len(blob)
            archive.addfile(entry, io.BytesIO(blob))
    return buffer.getvalue()


def upload_restore(opened, payload: bytes, passphrase: str, name="backup.tar.gz"):
    return opened.post(
        "/api/settings/restore",
        files={"file": (name, payload, "application/gzip")},
        data={"passphrase": passphrase},
    )


def test_a_backup_is_an_envelope_with_the_manifest_first(client):
    opened, config_dir = client
    seed_config(config_dir)

    envelope = download_backup(opened, "")
    manifest = read_manifest(envelope)

    assert manifest["kind"] == "neutrino_config_backup"
    assert manifest["is_sealed"] is False
    assert manifest["payload"] == "config.tar.gz"
    assert manifest["sha256"] == hashlib.sha256(read_payload(envelope)).hexdigest()
    assert KEY_MEMBER in inner_names(envelope)


def test_a_sealed_backup_seals_the_key_inside_the_payload(client):
    opened, config_dir = client
    seed_config(config_dir)

    envelope = download_backup(opened, PASSPHRASE)
    manifest = read_manifest(envelope)
    payload = read_payload(envelope)

    assert manifest["is_sealed"] is True
    assert manifest["payload"] == "config.sealed"
    assert payload.startswith(VAULT_SEALED_MAGIC)
    names = inner_names(envelope, PASSPHRASE)
    assert KEY_MEMBER in names
    assert "config/credentials/vault.json" in names


def test_a_box_without_a_vault_still_seals_under_a_passphrase(client):
    opened, config_dir = client
    (config_dir / "xray").mkdir()
    (config_dir / "xray" / "nodes.json").write_text("{}")

    envelope = download_backup(opened, PASSPHRASE)

    assert read_manifest(envelope)["is_sealed"] is True
    assert "config/xray/nodes.json" in inner_names(envelope, PASSPHRASE)


def test_a_sealed_backup_restores_the_store_it_left_with(client):
    opened, config_dir = client
    secret_id = seed_config(config_dir)
    envelope = download_backup(opened, PASSPHRASE)
    wipe_config(config_dir)

    response = upload_restore(opened, envelope, PASSPHRASE)

    assert response.status_code == 200
    assert response.json() == {"is_restored": True}
    assert SecretVault().open(secret_id) == {"password": SEALED_PASSWORD}


def test_a_restored_key_replaces_the_one_already_on_the_box(client):
    """The restored store needs its own key, not the key this box was using."""
    opened, config_dir = client
    secret_id = seed_config(config_dir)
    envelope = download_backup(opened, PASSPHRASE)
    wipe_config(config_dir)
    stale_id = seed_config(config_dir)

    assert upload_restore(opened, envelope, PASSPHRASE).status_code == 200
    assert SecretVault().open(secret_id) == {"password": SEALED_PASSWORD}
    assert SecretVault().get(stale_id) is None


def test_a_sealed_backup_without_a_passphrase_writes_nothing(client):
    opened, config_dir = client
    seed_config(config_dir)
    envelope = download_backup(opened, PASSPHRASE)
    wipe_config(config_dir)

    response = upload_restore(opened, envelope, "")

    assert response.status_code == 400
    assert response.json()["detail"] == {"code": "backup_passphrase_needed"}
    assert list(config_dir.rglob("*")) == []


def test_a_wrong_passphrase_writes_nothing(client):
    opened, config_dir = client
    seed_config(config_dir)
    envelope = download_backup(opened, PASSPHRASE)
    wipe_config(config_dir)

    response = upload_restore(opened, envelope, "not the passphrase")

    assert response.status_code == 400
    assert response.json()["detail"] == {"code": "backup_passphrase_wrong"}
    assert list(config_dir.rglob("*")) == []


def test_a_wrong_file_extension_is_refused_by_name(client):
    opened, config_dir = client
    seed_config(config_dir)
    envelope = download_backup(opened, "")
    wipe_config(config_dir)

    response = upload_restore(opened, envelope, "", name="backup.bin")

    assert response.status_code == 400
    assert response.json()["detail"] == {"code": "backup_wrong_extension"}
    assert list(config_dir.rglob("*")) == []


def test_a_foreign_tarball_is_refused_before_anything_is_read(client):
    opened, config_dir = client
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        entry = tarfile.TarInfo("config/xray/nodes.json")
        entry.size = 2
        archive.addfile(entry, io.BytesIO(b"{}"))

    response = upload_restore(opened, buffer.getvalue(), "")

    assert response.status_code == 400
    assert response.json()["detail"] == {"code": "backup_unrecognized"}
    assert list(config_dir.rglob("*")) == []


def test_a_tampered_payload_fails_its_checksum(client):
    opened, config_dir = client
    seed_config(config_dir)
    envelope = download_backup(opened, "")
    manifest = read_manifest(envelope)
    payload = bytearray(read_payload(envelope))
    payload[-1] ^= 0x01
    wipe_config(config_dir)

    response = upload_restore(opened, repacked(manifest, bytes(payload)), "")

    assert response.status_code == 400
    assert response.json()["detail"] == {"code": "backup_corrupt"}
    assert list(config_dir.rglob("*")) == []


def test_a_truncated_envelope_writes_nothing(client):
    opened, config_dir = client
    seed_config(config_dir)
    envelope = download_backup(opened, PASSPHRASE)
    wipe_config(config_dir)

    response = upload_restore(opened, envelope[:60], PASSPHRASE)

    assert response.status_code == 400
    assert response.json()["detail"] == {"code": "backup_unrecognized"}
    assert list(config_dir.rglob("*")) == []


def test_a_plain_backup_restores_as_it_always_did(client):
    opened, config_dir = client
    secret_id = seed_config(config_dir)
    envelope = download_backup(opened, "")
    wipe_config(config_dir)

    assert upload_restore(opened, envelope, "").status_code == 200
    assert json.loads((config_dir / "xray" / "nodes.json").read_text()) == {"nodes": []}
    assert SecretVault().open(secret_id) == {"password": SEALED_PASSWORD}
