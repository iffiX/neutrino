"""The Settings page: the panel's port, its name, backup and restore, About.

Moving the port: the process serving the request is the one being restarted,
so the write happens first and the restart is queued behind the response.
The hub's name is written with the rest of the settings and lands in the
identity file. Restore runs as root, so an archive is hostile input: what
these pin is that the destination is checked after the path resolves, and
that a refused restore is one that changed nothing. About answers one
version per carried component.
"""

import hashlib
import io
import json
import stat
import sys
import tarfile
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import neutrino_hub.utils.json_file
from neutrino_hub.modules.cliproxyapi.constants import CLIPROXYAPI_VERSION
from neutrino_hub.modules.credentials.vault import SecretVault
from neutrino_hub.modules.xray.constants import XRAY_GEODATA
from neutrino_hub.web import identity
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.identity import ensure_hub_identity
from neutrino_hub.web.routers.hub import setting as settings_router
from neutrino_hub.web.routers.hub.setting import _checked_member, _renamed_member

# --- the port: the write happens first and the restart is queued behind ---


class PortRuntime:
    """Just the settings dictionary the panel keeps in memory."""

    def __init__(self):
        self.settings = {"listen_port": 8080}


@pytest.fixture
def port_client(monkeypatch, tmp_path):
    stored: dict = {"listen_port": 8080}
    restarts: list = []
    monkeypatch.setattr(settings_router, "read_config", lambda name: dict(stored))
    monkeypatch.setattr(settings_router, "hub_name", lambda: "gateway")
    monkeypatch.setattr(
        settings_router, "write_config", lambda name, data: stored.update(data)
    )
    monkeypatch.setattr(
        settings_router, "_restart_panel", lambda: restarts.append("restarted")
    )
    runtime = PortRuntime()
    app = FastAPI()
    app.include_router(settings_router.router)
    app.dependency_overrides[require_session] = lambda: None
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as opened:
        yield opened, runtime, stored, restarts


def test_the_port_is_read_back(port_client):
    opened, _, _, _ = port_client

    assert opened.get("/api/hub/setting").json()["listen_port"] == 8080


def test_a_new_port_is_written_and_the_panel_moves_to_it(port_client):
    opened, runtime, stored, restarts = port_client

    response = opened.post("/api/hub/setting/set", json={"listen_port": 9443})

    assert response.status_code == 200
    assert response.json()["listen_port"] == 9443
    assert stored["listen_port"] == 9443
    assert runtime.settings["listen_port"] == 9443
    assert restarts == ["restarted"]


def test_the_port_it_is_already_on_restarts_nothing(port_client):
    """Saving a form nobody changed must not drop the connection it was
    saved over."""
    opened, _, _, restarts = port_client

    opened.post("/api/hub/setting/set", json={"listen_port": 8080})

    assert restarts == []


@pytest.mark.parametrize("port", [0, -1, 65536, 100000])
def test_a_port_no_listener_can_take_is_refused(port_client, port):
    opened, _, stored, restarts = port_client

    response = opened.post("/api/hub/setting/set", json={"listen_port": port})

    assert response.status_code == 400
    assert stored["listen_port"] == 8080
    assert restarts == []


# --- the hub's name, written with the rest and kept in the identity file ---


class NameRuntime:
    """Just the settings dictionary the panel keeps in memory."""

    def __init__(self, settings: dict):
        self.settings = settings


@pytest.fixture
def name_client(monkeypatch, tmp_path):
    stored: dict = {"listen_port": 8080}
    restarts: list = []
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(identity.socket, "gethostname", lambda: "gateway")
    ensure_hub_identity()
    monkeypatch.setattr(settings_router, "read_config", lambda name: dict(stored))
    monkeypatch.setattr(
        settings_router, "write_config", lambda name, data: stored.update(data)
    )
    monkeypatch.setattr(
        settings_router, "_restart_panel", lambda: restarts.append("restarted")
    )
    runtime = NameRuntime(stored)
    app = FastAPI()
    app.include_router(settings_router.router)
    app.dependency_overrides[require_session] = lambda: None
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as opened:
        yield opened, tmp_path, restarts


def identity_file(config_dir) -> dict:
    return json.loads((config_dir / "web" / "identity.json").read_text())


def test_the_settings_carry_the_name(name_client):
    opened, _, _ = name_client

    assert opened.get("/api/hub/setting").json()["hub_name"] == "gateway"


def test_a_new_name_is_written_and_nothing_restarts(name_client):
    opened, config_dir, restarts = name_client
    before = identity_file(config_dir)

    response = opened.post(
        "/api/hub/setting/set", json={"listen_port": 8080, "hub_name": "lab"}
    )

    assert response.status_code == 200
    assert response.json()["hub_name"] == "lab"
    assert identity_file(config_dir) == {"id": before["id"], "name": "lab"}
    assert restarts == []


def test_a_write_naming_no_hub_name_leaves_the_stored_one(name_client):
    opened, config_dir, _ = name_client
    opened.post("/api/hub/setting/set", json={"listen_port": 8080, "hub_name": "lab"})

    response = opened.post(
        "/api/hub/setting/set", json={"listen_port": 8080, "theme": "light"}
    )

    assert response.status_code == 200
    assert response.json()["hub_name"] == "lab"
    assert identity_file(config_dir)["name"] == "lab"


def test_a_blank_name_is_refused(name_client):
    opened, config_dir, _ = name_client

    response = opened.post(
        "/api/hub/setting/set", json={"listen_port": 8080, "hub_name": "  "}
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "hub_name_required"
    assert identity_file(config_dir)["name"] == "gateway"


# --- About: one version per piece of software the hub carries ---


XRAY_OUTPUT = "Xray 25.8.3 (Xray, Penetrates Everything.) Custom\nA unified platform\n"


def about_payload(monkeypatch, xray_stdout: str = XRAY_OUTPUT) -> dict:
    """Read /about with xray's own output stubbed."""
    monkeypatch.setattr(
        settings_router,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=xray_stdout),
    )
    app = FastAPI()
    app.include_router(settings_router.router)
    app.dependency_overrides[require_session] = lambda: None
    with TestClient(app) as client:
        response = client.get("/api/hub/setting/about")
    assert response.status_code == 200, response.text
    return response.json()


def test_every_carried_component_reports_a_version(monkeypatch):
    payload = about_payload(monkeypatch)

    carried = [
        "gateway_version",
        "xray_version",
        "cliproxyapi_version",
        "python_version",
        "geodata_version",
    ]
    assert all(payload[field] != "" for field in carried)


def test_the_ai_gateway_reports_the_version_the_package_pins(monkeypatch):
    payload = about_payload(monkeypatch)

    assert payload["cliproxyapi_version"] == CLIPROXYAPI_VERSION


def test_the_interpreter_is_the_one_running_the_panel(monkeypatch):
    payload = about_payload(monkeypatch)

    assert payload["python_version"] == sys.version.split()[0]


def test_the_geodata_baseline_names_the_release_behind_each_database(monkeypatch):
    payload = about_payload(monkeypatch)

    for name, entry in XRAY_GEODATA.items():
        release = entry["url"].rsplit("/", 2)[-2]
        assert name.removesuffix(".dat") in payload["geodata_version"]
        assert release in payload["geodata_version"]


def test_xray_answers_with_its_first_line(monkeypatch):
    payload = about_payload(monkeypatch)

    assert payload["xray_version"] == XRAY_OUTPUT.splitlines()[0]


def test_an_absent_xray_binary_is_reported_not_blank(monkeypatch):
    payload = about_payload(monkeypatch, xray_stdout="")

    assert payload["xray_version"] == "not installed"


def test_the_hub_credits_every_component_it_carries(monkeypatch):
    """The binaries in the hub package first, at the exact tag each was
    built from; the modules a manifest licenses after them."""
    from neutrino_hub.modules.cliproxyapi.constants import CLIPROXYAPI_VERSION
    from neutrino_hub.modules.easytier.constants import EASYTIER_VERSION
    from neutrino_hub.modules.netbird.constants import NETBIRD_VERSION
    from neutrino_hub.modules.xray.constants import XRAY_VERSION

    credits = settings_router._acknowledgements()
    by_name = {credit.name: credit for credit in credits}

    assert [credit.name for credit in credits[:4]] == [
        "Xray-core",
        "CLIProxyAPI",
        "NetBird",
        "EasyTier",
    ]
    assert by_name["Xray-core"].version == XRAY_VERSION
    assert by_name["Xray-core"].corresponding_source.endswith(f"/tree/v{XRAY_VERSION}")
    assert by_name["CLIProxyAPI"].version == CLIPROXYAPI_VERSION
    assert by_name["NetBird"].version == NETBIRD_VERSION
    assert by_name["NetBird"].license == "BSD-3-Clause"
    assert by_name["EasyTier"].version == EASYTIER_VERSION
    assert by_name["EasyTier"].license == "LGPL-3.0"
    assert "Gitea" in by_name


# --- backup and restore: what the archive carries, and what unpacking checks ---


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
    app.dependency_overrides[settings_router.get_runtime] = lambda: _FakeRuntime()
    with TestClient(app) as opened:
        yield opened, config_dir


class _FakeTasks:
    def start(self, *, label, source):
        source.aclose()
        return SimpleNamespace(id="restore-task")


class _FakeRuntime:
    def __init__(self):
        self.tasks = _FakeTasks()


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
    response = opened.post("/api/hub/setting/backup")
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
        "/api/hub/setting/restore",
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
    assert response.json() == {"is_restored": True, "task_id": "restore-task"}
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
    assert response.json()["detail"] == {
        "code": "vault_passphrase_needed",
        "params": {},
    }
    assert list(config_dir.rglob("*")) == []


def test_a_wrong_passphrase_writes_nothing(client):
    opened, config_dir = client
    seed_config(config_dir)
    archive_bytes = download_backup(opened)
    wipe_box(config_dir)

    response = upload_restore(opened, archive_bytes, "not the passphrase")

    assert response.status_code == 400
    assert response.json()["detail"] == {"code": "vault_passphrase_wrong", "params": {}}
    assert list(config_dir.rglob("*")) == []
    assert not (config_dir.parent / "state" / "vault.key").exists()


def test_a_wrong_file_extension_is_refused_by_name(client):
    opened, config_dir = client
    seed_config(config_dir)
    archive_bytes = download_backup(opened)
    wipe_box(config_dir)

    response = upload_restore(opened, archive_bytes, PASSPHRASE, name="backup.bin")

    assert response.status_code == 400
    assert response.json()["detail"] == {"code": "backup_wrong_extension", "params": {}}
    assert list(config_dir.rglob("*")) == []


def test_a_foreign_tarball_is_refused_before_anything_is_read(client):
    opened, config_dir = client

    response = upload_restore(
        opened, repacked({"config/xray/nodes.json": b"{}"}), PASSPHRASE
    )

    assert response.status_code == 400
    assert response.json()["detail"] == {"code": "backup_unrecognized", "params": {}}
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
    assert response.json()["detail"] == {"code": "backup_unrecognized", "params": {}}


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
    assert response.json()["detail"] == {"code": "backup_corrupt", "params": {}}
    assert list(config_dir.rglob("*")) == []


def test_a_member_the_digest_list_does_not_name_is_refused(client):
    opened, config_dir = client
    seed_config(config_dir)
    contents = archive_contents(download_backup(opened))
    contents["config/xray/extra.json"] = b"{}"
    wipe_box(config_dir)

    response = upload_restore(opened, repacked(contents), PASSPHRASE)

    assert response.status_code == 400
    assert response.json()["detail"] == {"code": "backup_corrupt", "params": {}}
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
    assert response.json()["detail"] == {"code": "backup_corrupt", "params": {}}
    assert list(config_dir.rglob("*")) == []


def test_a_truncated_archive_writes_nothing(client):
    opened, config_dir = client
    seed_config(config_dir)
    archive_bytes = download_backup(opened)
    wipe_box(config_dir)

    response = upload_restore(opened, archive_bytes[:60], PASSPHRASE)

    assert response.status_code == 400
    assert response.json()["detail"] == {"code": "backup_unrecognized", "params": {}}
    assert list(config_dir.rglob("*")) == []
