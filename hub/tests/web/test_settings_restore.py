"""What a config backup carries out of the box, and writes when unpacked.

Restore runs as root, so an archive is hostile input even though the person
uploading it is signed in: backups get passed around, and one built elsewhere
can name any path it likes. A member whose name merely starts with `config/`
proves nothing — `config/../../etc/passwd` starts that way — so what these
pin is that the destination is checked after the path resolves.

The passphrase half pins the order. The archive is settled in memory —
manifest, every digest, the wrapped key opening — before a byte is written,
so a refused restore is one that changed nothing, and the data key lands as
state only once everything else has.
"""

import hashlib
import io
import json
import stat
import tarfile

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import neutrino_hub.utils.json_file
from neutrino_hub.modules.credentials.vault import SecretVault
from neutrino_hub.web.dependencies import require_session
from neutrino_hub.web.routers import settings as settings_router
from neutrino_hub.web.routers.settings import _checked_member, _renamed_member

PASSPHRASE = "correct horse battery"  # scan: allow
SEALED_PASSWORD = "hunter2hunter2"  # scan: allow


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
    checked = _checked_member(_renamed_member(member(name)))
    assert checked.name.split("/")[0] == settings_router.UTILS_CONFIG_DIR.name


def test_the_archive_root_is_mapped_to_the_real_directory(monkeypatch, tmp_path):
    """An installed hub keeps config/ at /etc/neutrino/hub; the archive says config."""
    real = tmp_path / "hub"
    real.mkdir()
    monkeypatch.setattr(settings_router, "UTILS_CONFIG_DIR", real, raising=True)

    renamed = _renamed_member(member("config/xray/nodes.json"))

    assert renamed.name == "hub/xray/nodes.json"
    assert _checked_member(renamed).name == "hub/xray/nodes.json"


def test_a_member_outside_the_config_root_is_refused():
    with pytest.raises(HTTPException) as raised:
        _renamed_member(member("etc/passwd"))
    assert raised.value.status_code == 400


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
        _checked_member(_renamed_member(member(name)))
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
    root = settings_router.UTILS_CONFIG_DIR.name
    assert _checked_member(member(f"{root}/xray", tarfile.DIRTYPE)).isdir()


@pytest.fixture
def client(monkeypatch, tmp_path):
    """The Settings router over a config directory and state root of its own."""
    # Named like an installed box's directory, not like a checkout's, so the
    # archive-root mapping is what these tests exercise.
    config_dir = tmp_path / "hub"
    config_dir.mkdir()
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setattr(
        neutrino_hub.utils.json_file, "UTILS_CONFIG_DIR", config_dir, raising=True
    )
    monkeypatch.setattr(settings_router, "UTILS_CONFIG_DIR", config_dir, raising=True)
    monkeypatch.setattr("neutrino_hub.utils.constants.UTILS_STATE_ROOT", state_dir)
    app = FastAPI()
    app.include_router(settings_router.router)
    app.dependency_overrides[require_session] = lambda: None
    with TestClient(app) as opened:
        yield opened, config_dir


def seed_config(config_dir) -> str:
    """Initialize the vault and store one secret and one ordinary file."""
    (config_dir / "xray").mkdir()
    (config_dir / "xray" / "nodes.json").write_text(json.dumps({"nodes": []}))
    SecretVault().initialize(PASSPHRASE)
    record = SecretVault().add(
        kind="login", name="a password", secret={"password": SEALED_PASSWORD}
    )
    return record.id


def wipe_box(config_dir) -> None:
    """Leave the box with an empty ``config/`` and a locked vault."""
    for path in sorted(config_dir.rglob("*"), reverse=True):
        path.unlink() if path.is_file() else path.rmdir()
    state_key = config_dir.parent / "state" / "vault.key"
    state_key.unlink(missing_ok=True)


def download_backup(opened) -> bytes:
    """Ask for a backup and hand back the archive."""
    response = opened.post("/api/settings/backup")
    assert response.status_code == 200
    return response.content


def archive_contents(archive_bytes: bytes) -> dict:
    """Every regular member's bytes, in archive order."""
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as archive:
        return {
            entry.name: archive.extractfile(entry).read()
            for entry in archive.getmembers()
            if entry.isreg()
        }


def repacked(contents: dict) -> bytes:
    """An archive built by hand, for the tests that forge or damage one."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, blob in contents.items():
            entry = tarfile.TarInfo(name)
            entry.size = len(blob)
            archive.addfile(entry, io.BytesIO(blob))
    return buffer.getvalue()


def upload_restore(opened, payload: bytes, passphrase: str, name="backup.tar.gz"):
    return opened.post(
        "/api/settings/restore",
        files={"file": (name, payload, "application/gzip")},
        data={"vault_passphrase": passphrase},
    )


def test_a_backup_is_the_manifest_the_digests_and_the_plain_tree(client):
    opened, config_dir = client
    seed_config(config_dir)

    contents = archive_contents(download_backup(opened))
    names = list(contents)

    assert names[0] == "neutrino_backup.json"
    assert names[1] == "SHA256SUMS"
    assert json.loads(contents["neutrino_backup.json"]) == {
        "kind": "neutrino_config_backup",
        "version": 2,
    }
    listed = {
        path: digest
        for digest, _, path in (
            line.partition("  ")
            for line in contents["SHA256SUMS"].decode().splitlines()
        )
    }
    for name in names[2:]:
        assert name.startswith("config/")
        assert (
            listed[name[len("config/") :]] == hashlib.sha256(contents[name]).hexdigest()
        )
    assert set(listed) == {name[len("config/") :] for name in names[2:]}


def test_a_backup_carries_the_wrapped_key_and_no_key_file(client):
    opened, config_dir = client
    seed_config(config_dir)

    contents = archive_contents(download_backup(opened))

    store = json.loads(contents["config/credentials/vault.json"])
    assert "wrapped_key" in store
    assert not any(name.endswith("vault.key") for name in contents)


def test_a_backup_restores_the_vault_it_left_with(client):
    opened, config_dir = client
    secret_id = seed_config(config_dir)
    archive_bytes = download_backup(opened)
    wipe_box(config_dir)

    response = upload_restore(opened, archive_bytes, PASSPHRASE)

    assert response.status_code == 200
    assert response.json() == {"is_restored": True}
    assert SecretVault().open(secret_id) == {"password": SEALED_PASSWORD}
    state_key = config_dir.parent / "state" / "vault.key"
    assert stat.S_IMODE(state_key.stat().st_mode) == 0o600


def test_a_restored_key_replaces_the_one_already_on_the_box(client):
    """The restored store needs its own key, not the key this box was using."""
    opened, config_dir = client
    secret_id = seed_config(config_dir)
    archive_bytes = download_backup(opened)
    wipe_box(config_dir)
    stale_id = seed_config(config_dir)

    assert upload_restore(opened, archive_bytes, PASSPHRASE).status_code == 200
    assert SecretVault().open(secret_id) == {"password": SEALED_PASSWORD}
    assert SecretVault().get(stale_id) is None


def test_a_restore_without_a_passphrase_writes_nothing(client):
    opened, config_dir = client
    seed_config(config_dir)
    archive_bytes = download_backup(opened)
    wipe_box(config_dir)

    response = upload_restore(opened, archive_bytes, "")

    assert response.status_code == 400
    assert response.json()["detail"] == {"code": "vault_passphrase_needed"}
    assert list(config_dir.rglob("*")) == []


def test_a_wrong_passphrase_writes_nothing(client):
    opened, config_dir = client
    seed_config(config_dir)
    archive_bytes = download_backup(opened)
    wipe_box(config_dir)

    response = upload_restore(opened, archive_bytes, "not the passphrase")

    assert response.status_code == 400
    assert response.json()["detail"] == {"code": "vault_passphrase_wrong"}
    assert list(config_dir.rglob("*")) == []
    assert not (config_dir.parent / "state" / "vault.key").exists()


def test_a_wrong_file_extension_is_refused_by_name(client):
    opened, config_dir = client
    seed_config(config_dir)
    archive_bytes = download_backup(opened)
    wipe_box(config_dir)

    response = upload_restore(opened, archive_bytes, PASSPHRASE, name="backup.bin")

    assert response.status_code == 400
    assert response.json()["detail"] == {"code": "backup_wrong_extension"}
    assert list(config_dir.rglob("*")) == []


def test_a_foreign_tarball_is_refused_before_anything_is_read(client):
    opened, config_dir = client

    response = upload_restore(
        opened, repacked({"config/xray/nodes.json": b"{}"}), PASSPHRASE
    )

    assert response.status_code == 400
    assert response.json()["detail"] == {"code": "backup_unrecognized"}
    assert list(config_dir.rglob("*")) == []


def test_another_kind_or_version_is_refused(client):
    opened, config_dir = client

    forged = repacked(
        {
            "neutrino_backup.json": json.dumps({"kind": "acme", "version": 2}).encode(),
            "SHA256SUMS": b"",
        }
    )
    response = upload_restore(opened, forged, PASSPHRASE)

    assert response.status_code == 400
    assert response.json()["detail"] == {"code": "backup_unrecognized"}


def test_a_tampered_member_fails_its_digest(client):
    opened, config_dir = client
    seed_config(config_dir)
    contents = archive_contents(download_backup(opened))
    tampered = bytearray(contents["config/xray/nodes.json"])
    tampered[-1] ^= 0x01
    contents["config/xray/nodes.json"] = bytes(tampered)
    wipe_box(config_dir)

    response = upload_restore(opened, repacked(contents), PASSPHRASE)

    assert response.status_code == 400
    assert response.json()["detail"] == {"code": "backup_corrupt"}
    assert list(config_dir.rglob("*")) == []


def test_a_member_the_digest_list_does_not_name_is_refused(client):
    opened, config_dir = client
    seed_config(config_dir)
    contents = archive_contents(download_backup(opened))
    contents["config/xray/extra.json"] = b"{}"
    wipe_box(config_dir)

    response = upload_restore(opened, repacked(contents), PASSPHRASE)

    assert response.status_code == 400
    assert response.json()["detail"] == {"code": "backup_corrupt"}
    assert list(config_dir.rglob("*")) == []


def test_an_archive_without_a_vault_store_is_refused(client):
    opened, config_dir = client
    seed_config(config_dir)
    contents = archive_contents(download_backup(opened))
    del contents["config/credentials/vault.json"]
    sums = "".join(
        f"{hashlib.sha256(blob).hexdigest()}  {name[len('config/') :]}\n"
        for name, blob in contents.items()
        if name.startswith("config/")
    ).encode()
    contents["SHA256SUMS"] = sums
    wipe_box(config_dir)

    response = upload_restore(opened, repacked(contents), PASSPHRASE)

    assert response.status_code == 400
    assert response.json()["detail"] == {"code": "backup_corrupt"}
    assert list(config_dir.rglob("*")) == []


def test_a_truncated_archive_writes_nothing(client):
    opened, config_dir = client
    seed_config(config_dir)
    archive_bytes = download_backup(opened)
    wipe_box(config_dir)

    response = upload_restore(opened, archive_bytes[:60], PASSPHRASE)

    assert response.status_code == 400
    assert response.json()["detail"] == {"code": "backup_unrecognized"}
    assert list(config_dir.rglob("*")) == []
