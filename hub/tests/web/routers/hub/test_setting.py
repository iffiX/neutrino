"""The Settings page: the panel's port, its name, backup and restore, About.

Moving the port: the process serving the request is the one being restarted,
so the write happens first and the restart is queued behind the response.
The port also names the session cookie, so a hub on another port of the
same host cannot be signed in to with this one's. The hub's name is written
with the rest of the settings and lands in the identity file. Restore runs as root, so an archive is hostile input: what
these pin is that the destination is checked after the path resolves, and
that a refused restore is one that changed nothing. About answers one
version per carried component.
"""

import asyncio
import hashlib
import io
import json
import stat
import sys
import tarfile
from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

import neutrino_hub.utils.json_file
from neutrino_hub.modules.cliproxyapi.constants import CLIPROXYAPI_VERSION
from neutrino_hub.modules.credentials.vault import SecretVault
from neutrino_hub.modules.xray.geodata import XrayGeodataState
from neutrino_hub.web import auth as web_auth
from neutrino_hub.web import identity
from neutrino_hub.web.auth import SessionStore, hash_password
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.identity import ensure_hub_identity
from neutrino_hub.web.routers.hub import auth as auth_router
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


# --- the port names the session cookie, so two hubs on one host keep theirs ---

PANEL_PORT = 9443
PANEL_PASSWORD = "right"
OTHER_PORT_COOKIE = "neutrino_session_8080"


class CookieRuntime:
    """A panel on its own port, with a real session store behind it."""

    def __init__(self):
        self.settings = {"listen_port": PANEL_PORT, "session_ttl_hours": 1}
        self.sessions = SessionStore(
            password_hash=hash_password(PANEL_PASSWORD), session_ttl_hours=1
        )


@pytest.fixture
def cookie_client(monkeypatch, tmp_path):
    monkeypatch.setattr(
        web_auth, "WEB_LOGIN_LOCKOUT_STATE_PATH", tmp_path / "login_lockout.json"
    )
    runtime = CookieRuntime()
    app = FastAPI()
    app.include_router(auth_router.router)

    @app.get("/api/hub/thing", dependencies=[Depends(require_session)])
    def read_thing():
        return {"read": True}

    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as opened:
        yield opened


def signed_in_token(opened) -> str:
    """Log in and hand back the token the cookie carries."""
    response = opened.post("/api/hub/auth/login", json={"password": PANEL_PASSWORD})
    assert response.json()["is_authenticated"] is True
    token = response.cookies[f"neutrino_session_{PANEL_PORT}"]
    opened.cookies.clear()
    return token


def test_the_login_cookie_is_named_after_the_panel_port(cookie_client):
    response = cookie_client.post(
        "/api/hub/auth/login", json={"password": PANEL_PASSWORD}
    )

    assert response.status_code == 200
    assert f"neutrino_session_{PANEL_PORT}" in response.cookies
    assert OTHER_PORT_COOKIE not in response.cookies


def test_a_cookie_named_for_another_port_is_not_a_session(cookie_client):
    token = signed_in_token(cookie_client)

    response = cookie_client.get(
        "/api/hub/thing", headers={"cookie": f"{OTHER_PORT_COOKIE}={token}"}
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "not_authenticated"


def test_the_cookie_named_for_this_port_is_the_session(cookie_client):
    token = signed_in_token(cookie_client)

    response = cookie_client.get(
        "/api/hub/thing",
        headers={"cookie": f"neutrino_session_{PANEL_PORT}={token}"},
    )

    assert response.json() == {"read": True}


def test_logout_clears_the_cookie_this_port_named(cookie_client):
    token = signed_in_token(cookie_client)

    response = cookie_client.post(
        "/api/hub/auth/logout",
        headers={"cookie": f"neutrino_session_{PANEL_PORT}={token}"},
    )

    assert response.json()["is_authenticated"] is False
    assert f"neutrino_session_{PANEL_PORT}" in response.headers["set-cookie"]
    assert (
        cookie_client.get(
            "/api/hub/thing",
            headers={"cookie": f"neutrino_session_{PANEL_PORT}={token}"},
        ).status_code
        == 401
    )


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

    assert response.status_code == 400
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


def test_the_geodata_line_names_the_release_each_database_is(monkeypatch):
    """What the box loads, which on a box that has taken a newer release is
    not what the package carries."""
    monkeypatch.setattr(
        settings_router.geodata,
        "installed",
        lambda: XrayGeodataState(
            releases={"geoip.dat": "202609050329", "geosite.dat": "20260914091725"},
            source="release",
        ),
    )

    payload = about_payload(monkeypatch)

    assert payload["geodata_version"] == "geoip 202609050329 · geosite 20260914091725"


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


# --- updating the hub itself ---


class _UpdateTasks:
    """The registry, remembering what it was asked to start."""

    def __init__(self):
        self.started = []
        self.running_stream = None

    def start(self, *, label, source):
        self.started.append((label, source))
        return SimpleNamespace(id="update-task", label=label)

    def running(self, label: str):
        return self.running_stream


class _UpdateRuntime:
    def __init__(self):
        self.settings = {"listen_port": 8090}
        self.tasks = _UpdateTasks()


class _Release:
    def __init__(self, version: str, *, size: int = 100):
        self.version = version
        self.tag = f"v{version}"
        self.published_at = "2026-10-01T12:00:00Z"
        self.notes = "notes"
        self.page_url = f"https://example.invalid/{version}"
        self.asset_name = f"neutrino-hub_{version}_amd64.deb"
        self.asset_url = f"https://example.invalid/{self.asset_name}"
        self.asset_size = size
        self.checksums_url = "https://example.invalid/SHA256SUMS"


class _Checker:
    def __init__(self, latest=None, *, failure=None):
        self.latest_release = latest
        self.failure = failure

    def latest(self):
        if self.failure is not None:
            raise self.failure
        return self.latest_release


class _Installer:
    """An installer whose releases, unit and disk are the test's."""

    def __init__(self, state, *, latest=None, failure=None):
        self.checker = _Checker(latest, failure=failure)
        self.state = state
        self.is_active = False
        self.rollback_available = True
        self.rollback_present = False
        self.prepared = []
        self.launched = []
        self.prepare_failure = None

    def is_unit_active(self):
        return self.is_active

    def is_rollback_available(self, current):
        return self.rollback_available

    def is_rollback_present(self, current):
        return self.rollback_present

    def prepare(self, found, *, current, port, on_progress):
        on_progress("downloading")
        on_progress("100%")
        if self.prepare_failure is not None:
            raise self.prepare_failure
        self.prepared.append((found.version, current, port))
        return SimpleNamespace(to_version=found.version)

    def launch(self, plan):
        self.launched.append(plan)


@pytest.fixture
def update_box(monkeypatch, tmp_path):
    """The update routes over a stub installer and a real state file."""
    from neutrino_hub.modules.hub_update.state import HubUpdateStateFile

    state = HubUpdateStateFile(path=tmp_path / "state.json")
    installer = _Installer(state)
    monkeypatch.setattr(settings_router, "_update_installer", lambda: installer)
    monkeypatch.setattr(settings_router, "is_packaged", lambda: True)
    monkeypatch.setattr(settings_router, "HUB_VERSION", "0.3.0")
    monkeypatch.setattr(
        settings_router,
        "free_bytes",
        lambda size, *, is_rollback_fetched: (size * 4, 10_000),
    )
    monkeypatch.setattr(
        settings_router, "check_space", lambda size, *, is_rollback_fetched: None
    )
    runtime = _UpdateRuntime()
    app = FastAPI()
    app.include_router(settings_router.router)
    app.dependency_overrides[require_session] = lambda: None
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as opened:
        yield opened, installer, runtime


def _record(stage: str, **overrides):
    from neutrino_hub.modules.hub_update.state import HubUpdateRecord

    values = {
        "stage": stage,
        "from_version": "0.3.0",
        "to_version": "0.3.1",
        "started_at": "2026-09-20T15:00:00Z",
    }
    values.update(overrides)
    return HubUpdateRecord(**values)


def test_a_hub_that_never_updated_reads_its_version_and_no_record(update_box):
    opened, _, _ = update_box

    response = opened.get("/api/hub/setting/release")

    assert response.status_code == 200
    assert response.json() == {
        "current": "0.3.0",
        "is_packaged": True,
        "update": None,
        "task_id": None,
    }


def test_the_last_updates_record_is_read_as_written(update_box):
    opened, installer, _ = update_box
    installer.state.save(_record("installed", finished_at="f", output="done"))

    body = opened.get("/api/hub/setting/release").json()

    assert body["update"] == {
        "stage": "installed",
        "from_version": "0.3.0",
        "to_version": "0.3.1",
        "started_at": "2026-09-20T15:00:00Z",
        "finished_at": "f",
        "reason": "",
        "output": "done",
    }


def test_an_install_whose_unit_is_gone_reads_as_interrupted(update_box):
    opened, installer, _ = update_box
    installer.state.save(_record("installing"))
    installer.is_active = False

    body = opened.get("/api/hub/setting/release").json()

    assert body["update"]["stage"] == "failed"
    assert body["update"]["reason"] == "update_interrupted"
    assert installer.state.load().stage == "failed"


def test_an_install_whose_unit_runs_reads_as_installing(update_box):
    opened, installer, _ = update_box
    installer.state.save(_record("installing"))
    installer.is_active = True

    body = opened.get("/api/hub/setting/release").json()

    assert body["update"]["stage"] == "installing"


def test_a_staging_under_way_names_its_task(update_box):
    opened, installer, runtime = update_box
    installer.state.save(_record("preparing"))
    runtime.tasks.running_stream = SimpleNamespace(id="update-task")

    body = opened.get("/api/hub/setting/release").json()

    assert body["update"]["stage"] == "preparing"
    assert body["task_id"] == "update-task"


def test_a_checkout_says_so(update_box, monkeypatch):
    opened, _, _ = update_box
    monkeypatch.setattr(settings_router, "is_packaged", lambda: False)

    assert opened.get("/api/hub/setting/release").json()["is_packaged"] is False
    scan = opened.post("/api/hub/setting/release/scan")
    assert scan.status_code == 409
    assert scan.json()["detail"]["code"] == "hub_not_packaged"
    install = opened.post("/api/hub/setting/release/install", json={"version": "0.3.1"})
    assert install.status_code == 409
    assert install.json()["detail"]["code"] == "hub_not_packaged"


def test_a_scan_reads_the_newest_release_and_how_it_stands(update_box):
    opened, installer, _ = update_box
    installer.checker.latest_release = _Release("0.3.1", size=100)

    body = opened.post("/api/hub/setting/release/scan").json()

    assert body == {
        "current": "0.3.0",
        "latest": {
            "version": "0.3.1",
            "published_at": "2026-10-01T12:00:00Z",
            "notes": "notes",
            "page_url": "https://example.invalid/0.3.1",
            "size_bytes": 100,
        },
        "is_newer": True,
        "is_major": False,
        "is_rollback_available": True,
        "needed_bytes": 400,
        "free_bytes": 10_000,
        "is_space_enough": True,
    }


def test_a_scan_with_nothing_published_says_so(update_box):
    opened, _, _ = update_box

    body = opened.post("/api/hub/setting/release/scan").json()

    assert body["latest"] is None
    assert body["is_newer"] is False


def test_a_scan_singles_out_a_new_major_and_a_missing_rollback(update_box):
    opened, installer, _ = update_box
    installer.checker.latest_release = _Release("1.0.0")
    installer.rollback_available = False

    body = opened.post("/api/hub/setting/release/scan").json()

    assert body["is_newer"] is True
    assert body["is_major"] is True
    assert body["is_rollback_available"] is False


def test_a_scan_says_when_the_disk_is_short(update_box, monkeypatch):
    opened, installer, _ = update_box
    installer.checker.latest_release = _Release("0.3.1", size=100)
    monkeypatch.setattr(
        settings_router, "free_bytes", lambda size, *, is_rollback_fetched: (400, 399)
    )

    body = opened.post("/api/hub/setting/release/scan").json()

    assert body["is_space_enough"] is False
    assert body["needed_bytes"] == 400
    assert body["free_bytes"] == 399


def test_a_scan_that_cannot_reach_the_releases_is_a_bad_gateway(update_box):
    opened, installer, _ = update_box
    installer.checker.failure = OSError("no route")

    response = opened.post("/api/hub/setting/release/scan")

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "release_unreachable"


def test_an_install_stages_the_confirmed_release_as_a_task(update_box):
    opened, installer, runtime = update_box
    installer.checker.latest_release = _Release("0.3.1")

    response = opened.post(
        "/api/hub/setting/release/install", json={"version": "0.3.1"}
    )

    assert response.status_code == 200
    assert response.json() == {"task_id": "update-task"}
    assert [label for label, _ in runtime.tasks.started] == ["hub_update"]
    record = installer.state.load()
    assert record.stage == "preparing"
    assert record.from_version == "0.3.0"
    assert record.to_version == "0.3.1"
    for _, source in runtime.tasks.started:
        asyncio.run(source.aclose())


@pytest.mark.parametrize(
    ("latest", "requested", "code"),
    [
        (None, "0.3.1", "release_not_latest"),
        (_Release("0.3.2"), "0.3.1", "release_not_latest"),
        (_Release("0.3.0"), "0.3.0", "release_not_newer"),
        (_Release("1.0.0"), "1.0.0", "release_major"),
    ],
)
def test_an_install_refuses_what_is_not_the_newest_newer_minor(
    update_box, latest, requested, code
):
    opened, installer, runtime = update_box
    installer.checker.latest_release = latest

    response = opened.post(
        "/api/hub/setting/release/install", json={"version": requested}
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == code
    assert runtime.tasks.started == []
    assert installer.state.load() is None


def test_an_install_refuses_while_one_is_under_way(update_box):
    opened, installer, runtime = update_box
    installer.checker.latest_release = _Release("0.3.1")
    runtime.tasks.running_stream = SimpleNamespace(id="update-task")

    response = opened.post(
        "/api/hub/setting/release/install", json={"version": "0.3.1"}
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "update_in_progress"

    runtime.tasks.running_stream = None
    installer.is_active = True
    response = opened.post(
        "/api/hub/setting/release/install", json={"version": "0.3.1"}
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "update_in_progress"


def test_an_install_refuses_when_the_disk_is_short(update_box, monkeypatch):
    from neutrino_hub.exceptions import HubUpdateError

    opened, installer, runtime = update_box
    installer.checker.latest_release = _Release("0.3.1")

    def short(size, *, is_rollback_fetched):
        raise HubUpdateError(
            "disk_space_short", path="/var/lib", needed_bytes=400, free_bytes=1
        )

    monkeypatch.setattr(settings_router, "check_space", short)

    response = opened.post(
        "/api/hub/setting/release/install", json={"version": "0.3.1"}
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "disk_space_short",
        "params": {"path": "/var/lib", "needed_bytes": 400, "free_bytes": 1},
    }
    assert runtime.tasks.started == []


def test_an_install_that_cannot_reach_the_releases_is_a_bad_gateway(update_box):
    opened, installer, _ = update_box
    installer.checker.failure = OSError("no route")

    response = opened.post(
        "/api/hub/setting/release/install", json={"version": "0.3.1"}
    )

    assert response.status_code == 502


async def _drained(source) -> list:
    lines = []
    async for line in source:
        lines.append(line)
    return lines


def test_the_staging_task_relays_progress_and_hands_over(update_box, monkeypatch):
    opened, installer, _ = update_box
    found = _Release("0.3.1")

    lines = asyncio.run(
        _drained(settings_router._update_source(installer, found, port=8090))
    )

    assert lines == [
        "staging neutrino-hub_0.3.1_amd64.deb of v0.3.1\n",
        "downloading\n",
        "100%\n",
        "handing the install to systemd; the panel restarts now\n",
    ]
    assert installer.prepared == [("0.3.1", "0.3.0", 8090)]
    assert [plan.to_version for plan in installer.launched] == ["0.3.1"]


def test_a_staging_that_fails_records_why_and_ends_the_task_failed(update_box):
    from neutrino_hub.exceptions import HubUpdateError

    opened, installer, _ = update_box
    installer.state.save(_record("preparing"))
    installer.prepare_failure = HubUpdateError(
        "package_sha256_mismatch", name="neutrino-hub_0.3.1_amd64.deb"
    )
    found = _Release("0.3.1")

    with pytest.raises(HubUpdateError):
        asyncio.run(
            _drained(settings_router._update_source(installer, found, port=8090))
        )

    record = installer.state.load()
    assert record.stage == "failed"
    assert record.reason == "package_sha256_mismatch"
    assert record.started_at == "2026-09-20T15:00:00Z"
    assert record.finished_at.endswith("Z")
    assert installer.launched == []
