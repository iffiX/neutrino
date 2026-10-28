"""The file service: the platform does the privileged part, typed refusals.

A machine's share takes its login from the hub's ``service`` frame at every
mount and asks the person nothing; a declared share keeps the person's own
login in a file only this person reads, and one with no user name is
refused ``credentials_missing``. Every mount writes its login to a 0600
credentials file of that one mount, gone once the mount answered, whether
it succeeded or failed. The password is proven absent from argv, the store
and the state payload. An empty place takes the default:
``~/remote/<machine>-<share>``, or the first free drive letter on Windows.
A record is the hub and entry a share came from, its host, its share, the
user it last mounted as and its place; what is attached is this run's own,
so a record of an earlier run waits to be asked for. A declined
authorization, a share refusal the person must act on, and a hub that
refuses the login are typed and not retried on the timer; an unreachable
share or hub is. One hub's records are let go of without touching
another's, two hubs cannot share one mount point, a failed record holds
none, and a record an older build wrote without a hub is unmounted by path
and dropped at start. A mount follows the host its entry names now, and a
record whose entry moved is written back; an absent entry leaves it alone.

Every share is mounted from the hub's channel: on Linux and macOS the
system mounts ``//127.0.0.1/<share>`` at the port of the entry's forward,
made before the mount and ended once the share is unmounted or refused for
good; on Windows it mounts the files adapter's address for the share's
machine, and an adapter that cannot be made fails the record with
``files_adapter_unavailable`` and is not retried.
"""

import json
import os

import pytest

from neutrino_client.exceptions import (
    GatewayRefusedDetail,
    GatewayUnreachable,
    ShareAttachError,
)
from neutrino_client.services.file import (
    FileServiceHandler,
    default_place,
    mount_record_id,
)
from neutrino_client.services.store import ClientServiceStore
from tests.conftest import FakeClientPlatform, discard

PAYLOAD = {"protocol": "smb", "host": "hub", "share": "media", "users": ["media"]}
DECLARED_PAYLOAD = {"protocol": "smb", "host": "nas", "share": "photos", "users": []}
# Where the fake registry says each entry's forward listens.
FORWARD_PORT = 20445
# The login the hub gives a machine's share.
HUB_LOGIN = {"user": "media", "password": "hub-secret"}  # scan: allow


class FakeForwards:
    """The forward registry, a port handed out per entry and nothing listening."""

    def __init__(self):
        self.running = {}
        self.ensured = []
        self.error = None

    def ensure(self, *, hub_id, entry_id, kind, own_port=0, protocol="tcp"):
        if self.error is not None:
            raise self.error
        self.ensured.append((hub_id, entry_id, kind))
        port = FORWARD_PORT + len(self.running)
        return self.running.setdefault((hub_id, entry_id), port)

    def stop(self, hub_id, entry_id):
        return self.running.pop((hub_id, entry_id), None) is not None

    def port_of(self, hub_id, entry_id):
        return self.running.get((hub_id, entry_id), 0)


class FakeHub:
    """The hub's replies to a share's ``service`` frame, scripted."""

    def __init__(self, material=None, error=None):
        self.material = dict(HUB_LOGIN if material is None else material)
        self.error = error
        self.asked = []

    def open_service(self, hub_id, entry_id):
        self.asked.append((hub_id, entry_id))
        if self.error is not None:
            raise self.error
        return dict(self.material)


class ReadingPlatform(FakeClientPlatform):
    """A platform that reads the mount's credentials file while it mounts."""

    def __init__(self):
        super().__init__()
        self.logins = []

    def attach_share(self, *, share_url, location, credentials_path, port=0) -> str:
        with open(credentials_path, "r", encoding="utf-8") as stream:
            text = stream.read()
        mode = os.stat(credentials_path).st_mode & 0o777
        self.logins.append((text, mode))
        return super().attach_share(
            share_url=share_url,
            location=location,
            credentials_path=credentials_path,
            port=port,
        )


def entry_for(payload, hub_id="h1", entry_id="share_media", **fields):
    return dict(
        {
            "hub_id": hub_id,
            "id": entry_id,
            "type": "file",
            "title": payload.get("share", ""),
            "payload": payload,
            "is_healthy": True,
            "source": "module",
            "description": "",
            "device_name": "lab",
        },
        **fields,
    )


def declared_entry(hub_id="h1"):
    return entry_for(
        DECLARED_PAYLOAD,
        hub_id=hub_id,
        entry_id="app_nas_file_photos",
        source="declared",
        app_id="app_nas",
        device_name="",
    )


def handler_on(tmp_path, platform=None, hub=None, entries=None, **kwargs):
    """A handler on a platform, a hub and the entries the hubs list now."""
    platform = platform if platform is not None else ReadingPlatform()
    hub = hub if hub is not None else FakeHub()
    store = ClientServiceStore(path=str(tmp_path / "state.json"))
    held = entries if entries is not None else []
    subject = FileServiceHandler(
        platform=platform,
        store=store,
        credentials_dir=str(tmp_path / "config" / "mount_credentials"),
        forwards=FakeForwards(),
        log=kwargs.pop("log", discard),
        entries_of=lambda: list(held),
        open_service=hub.open_service,
        **kwargs,
    )
    return subject, platform, store, hub


@pytest.fixture
def service(tmp_path):
    subject, platform, store, hub = handler_on(tmp_path)
    subject.hub = hub
    return subject, platform, store, tmp_path


def credentials_dir(tmp_path):
    return tmp_path / "config" / "mount_credentials"


def left_files(tmp_path) -> list:
    """The files the credentials directory holds; none while it is not there."""
    directory = credentials_dir(tmp_path)
    return (
        sorted(path.name for path in directory.iterdir()) if directory.is_dir() else []
    )


def attach(subject, *, path, hub_id="h1", entry=None, username="", password=""):
    """Queue a mount and, when accepted, run the worker's pass by hand."""
    reply = subject.attach(
        hub_id=hub_id,
        entry=entry if entry is not None else entry_for(PAYLOAD, hub_id=hub_id),
        path=path,
        username=username,
        password=password,
    )
    if reply == {}:
        subject.reconcile()
    return reply


def attach_declared(subject, *, path, password="nas-pw", username="alice", **kw):
    """Queue a declared share's mount with the person's login and run the worker."""
    return attach(
        subject,
        path=path,
        entry=declared_entry(kw.get("hub_id", "h1")),
        username=username,
        password=password,
        hub_id=kw.get("hub_id", "h1"),
    )


def test_a_creatable_path_is_made_and_mounted(service):
    subject, platform, store, tmp_path = service
    location = str(tmp_path / "home" / "nas" / "media")

    assert attach(subject, path=location) == {}

    assert platform.fs_calls == [("mkdir", location)]
    call = platform.attach_calls[0]
    assert call["share_url"] == "//127.0.0.1/media" and call["location"] == location
    assert call["port"] == FORWARD_PORT
    record = store.mounts()[mount_record_id("h1", "share_media", location)]
    assert record["path"] == location
    assert record["hub_id"] == "h1"
    assert "password" not in record and "account" not in record


# --- the login: the hub's for a machine's share, the person's for a declared one ---


def test_a_machines_share_mounts_with_the_hubs_login_and_asks_nothing(service):
    subject, platform, store, tmp_path = service
    location = str(tmp_path / "nas")

    assert attach(subject, path=location) == {}

    assert subject.hub.asked == [("h1", "share_media")]
    ((text, mode),) = platform.logins
    assert text == "username=media\npassword=hub-secret\n"  # scan: allow
    assert mode == 0o600
    (record,) = store.mounts().values()
    assert record["username"] == "media"
    assert subject.rows()[0]["state"] == "mounted"


def test_the_hubs_login_is_read_again_at_every_mount(service):
    subject, platform, store, tmp_path = service
    location = str(tmp_path / "nas")
    assert attach(subject, path=location) == {}
    (record_id,) = store.mounts()

    assert subject.detach(record_id=record_id) == {}
    subject.hub.material = {"user": "media", "password": "turned"}  # scan: allow
    assert subject.remount(record_id=record_id) == {}
    subject.reconcile()

    assert subject.hub.asked == [("h1", "share_media")] * 2
    assert platform.logins[1][0] == "username=media\npassword=turned\n"


def test_a_mounts_credentials_file_is_gone_once_it_answered(service):
    subject, platform, _store, tmp_path = service

    assert attach(subject, path=str(tmp_path / "nas")) == {}

    credentials_path = platform.attach_calls[0]["credentials_path"]
    assert credentials_path.endswith(".mount")
    assert not os.path.exists(credentials_path)
    assert left_files(tmp_path) == []


def test_a_mounts_credentials_file_is_gone_after_a_failed_mount_too(service):
    subject, platform, _store, tmp_path = service
    platform.attach_error = ShareAttachError("share_login_rejected")

    assert attach(subject, path=str(tmp_path / "nas")) == {}

    assert subject.rows()[0]["code"] == "share_hub_login_rejected"
    assert not os.path.exists(platform.attach_calls[0]["credentials_path"])
    assert left_files(tmp_path) == []


def test_the_password_is_on_no_argument_in_no_store_and_in_no_state(service):
    subject, platform, _store, tmp_path = service

    outcome = subject.act(
        entries=[entry_for(PAYLOAD)],
        body={
            "action": "mount",
            "hub_id": "h1",
            "id": "share_media",
            "path": str(tmp_path / "nas"),
        },
    )
    assert outcome == {}
    subject.reconcile()

    assert "password" not in platform.attach_calls[0]
    assert "hub-secret" not in json.dumps(platform.attach_calls)
    raw = (tmp_path / "state.json").read_bytes()
    assert b"hub-secret" not in raw and b'"password"' not in raw
    payload = json.dumps(subject.state())
    assert "hub-secret" not in payload and '"password"' not in payload


@pytest.mark.parametrize(
    "code", ["permission_denied", "vault_locked", "service_unknown", "client_disabled"]
)
def test_a_hub_that_refuses_the_login_fails_the_record_and_is_not_retried(
    tmp_path, code
):
    hub = FakeHub(error=GatewayRefusedDetail(code=code, params={"kind": "file"}))
    subject, platform, _store, _hub = handler_on(tmp_path, hub=hub)

    assert attach(subject, path=str(tmp_path / "nas")) == {}
    subject.reconcile()

    row = subject.rows()[0]
    assert (row["state"], row["code"]) == ("failed", code)
    assert row["params"] == {"kind": "file"}
    assert platform.attach_calls == []
    assert hub.asked == [("h1", "share_media")]
    assert subject._forwards.running == {}
    assert left_files(tmp_path) == []


def test_a_hub_out_of_reach_is_asked_again_on_the_timer(tmp_path):
    hub = FakeHub(error=GatewayUnreachable("down"))
    subject, platform, _store, _hub = handler_on(tmp_path, hub=hub)

    assert attach(subject, path=str(tmp_path / "nas")) == {}
    assert subject.rows()[0]["code"] == "hub_unreachable"
    hub.error = None
    subject.reconcile()

    assert len(hub.asked) == 2
    assert subject.rows()[0]["state"] == "mounted"


def test_a_hub_that_gives_no_user_is_a_missing_login(tmp_path):
    hub = FakeHub(material={})
    subject, platform, _store, _hub = handler_on(tmp_path, hub=hub)

    assert attach(subject, path=str(tmp_path / "nas")) == {}

    assert subject.rows()[0]["code"] == "credentials_missing"
    assert platform.attach_calls == []


def test_a_declared_share_keeps_the_persons_login_and_asks_the_hub_nothing(service):
    subject, platform, store, tmp_path = service
    location = str(tmp_path / "photos")

    assert attach_declared(subject, path=location) == {}

    assert subject.hub.asked == []
    assert platform.logins[0][0] == "username=alice\npassword=nas-pw\n"
    record_id = mount_record_id("h1", "app_nas_file_photos", location)
    login = credentials_dir(tmp_path) / f"{record_id}.login"
    assert login.read_text() == "username=alice\npassword=nas-pw\n"
    assert oct(login.stat().st_mode & 0o777) == "0o600"
    assert oct(credentials_dir(tmp_path).stat().st_mode & 0o777) == "0o700"
    record = store.mounts()[record_id]
    assert record["is_declared"] is True and record["username"] == "alice"
    assert "nas-pw" not in (tmp_path / "state.json").read_text()
    assert subject.rows()[0]["is_declared"] is True


def test_a_declared_share_with_no_user_name_is_refused(service):
    subject, platform, store, tmp_path = service

    assert attach_declared(subject, path=str(tmp_path / "photos"), username="") == {
        "code": "credentials_missing",
        "params": {},
    }
    assert store.mounts() == {}
    assert platform.attach_calls == []


def test_a_declared_share_mounts_again_with_its_kept_login(service):
    subject, platform, store, tmp_path = service
    assert attach_declared(subject, path=str(tmp_path / "photos")) == {}
    (record_id,) = store.mounts()
    assert subject.detach(record_id=record_id) == {}

    assert subject.remount(record_id=record_id) == {}
    subject.reconcile()

    assert [text for text, _mode in platform.logins] == [
        "username=alice\npassword=nas-pw\n"
    ] * 2
    assert subject.rows()[0]["state"] == "mounted"


def test_a_declared_shares_gone_login_reports_and_waits(service):
    subject, platform, store, tmp_path = service
    location = str(tmp_path / "photos")
    assert attach_declared(subject, path=location) == {}
    (record_id,) = store.mounts()

    os.unlink(credentials_dir(tmp_path) / f"{record_id}.login")
    platform.attached.discard(location)
    subject.reconcile()

    row = subject.rows()[0]
    assert (row["state"], row["code"]) == ("failed", "credentials_missing")
    assert row["is_attached"] is False
    assert len(platform.attach_calls) == 1


def test_a_new_login_for_the_same_declared_share_replaces_the_kept_one(service):
    subject, platform, _store, tmp_path = service
    location = str(tmp_path / "photos")
    platform.attach_error = ShareAttachError("share_login_rejected")
    assert attach_declared(subject, path=location, password="wrong") == {}

    platform.attach_error = None
    assert attach_declared(subject, path=location, password="right") == {}

    assert subject.rows()[0]["is_attached"] is True
    assert subject.rows()[0]["code"] == ""
    assert platform.logins[-1][0] == "username=alice\npassword=right\n"
    assert len(subject.rows()) == 1


def test_save_after_a_refused_login_mounts_at_once_with_the_new_one(service):
    subject, platform, store, tmp_path = service
    platform.attach_error = ShareAttachError("share_login_rejected")
    assert attach_declared(subject, path=str(tmp_path / "photos")) == {}
    (record_id,) = store.mounts()
    platform.attach_error = None

    outcome = subject.act(
        entries=[],
        body={
            "action": "set",
            "record_id": record_id,
            "username": "bob",
            "password": "fixed",  # scan: allow
        },
    )

    assert outcome == {}
    assert subject.rows()[0]["state"] == "queued"
    subject.reconcile()
    assert platform.logins[-1][0] == "username=bob\npassword=fixed\n"
    assert store.mounts()[record_id]["username"] == "bob"
    assert subject.rows()[0]["state"] == "mounted"


def test_a_login_is_saved_for_a_declared_share_alone(service):
    subject, _platform, store, tmp_path = service
    assert attach(subject, path=str(tmp_path / "nas")) == {}
    assert attach_declared(subject, path=str(tmp_path / "photos")) == {}
    machine_id = mount_record_id("h1", "share_media", str(tmp_path / "nas"))
    declared_id = mount_record_id("h1", "app_nas_file_photos", str(tmp_path / "photos"))

    assert subject.set_login(record_id=machine_id, username="x", password="y") == {
        "code": "unknown_request",
        "params": {},
    }
    assert subject.set_login(record_id="missing", username="x", password="y") == {
        "code": "unknown_request",
        "params": {},
    }
    assert subject.set_login(record_id=declared_id, username="", password="y") == {
        "code": "credentials_missing",
        "params": {},
    }
    assert store.mounts()[declared_id]["username"] == "alice"


# --- the place ---


def test_an_empty_place_mounts_under_the_home_by_machine_and_share(service):
    subject, platform, _store, _tmp_path = service
    expected = os.path.join(os.path.expanduser("~"), "remote", "lab-media")

    assert attach(subject, path="") == {}

    assert platform.attach_calls[0]["location"] == expected
    assert subject.rows()[0]["path"] == expected


def test_a_default_place_turns_every_other_character_into_a_hyphen():
    platform = FakeClientPlatform()
    entry = entry_for(dict(PAYLOAD, share="my share!"), device_name="Lab GPU_2")

    assert default_place(entry, platform) == os.path.join(
        os.path.expanduser("~"), "remote", "Lab-GPU_2-my-share-"
    )


def test_a_share_of_no_known_machine_is_named_by_its_host():
    platform = FakeClientPlatform()

    assert default_place(declared_entry(), platform) == os.path.join(
        os.path.expanduser("~"), "remote", "nas-photos"
    )


def test_the_default_on_windows_is_the_first_free_drive_letter():
    assert default_place(entry_for(PAYLOAD), FakeDrivePlatform()) == "Z:"


def test_an_entrys_fields_say_its_default_place_and_whose_login_it_takes(service):
    subject, _platform, _store, _tmp_path = service

    assert subject.entry_fields(entry_for(PAYLOAD)) == {
        "mount_default": os.path.join(os.path.expanduser("~"), "remote", "lab-media"),
        "is_declared": False,
    }
    assert subject.entry_fields(declared_entry())["is_declared"] is True


def test_a_non_empty_mount_point_is_refused(service):
    subject, platform, _store, tmp_path = service
    full = tmp_path / "full"
    full.mkdir()
    (full / "kept").write_text("content")

    assert attach(subject, path=str(full)) == {
        "code": "mountpoint_not_empty",
        "params": {},
    }
    assert platform.attach_calls == []


def test_a_relative_path_is_refused(service):
    subject, _platform, _store, _tmp_path = service

    assert attach(subject, path="nas/media") == {
        "code": "mountpoint_invalid",
        "params": {},
    }


def test_a_mount_without_the_tooling_is_refused_typed(service):
    subject, platform, store, tmp_path = service
    platform.has_tooling = False

    assert attach(subject, path=str(tmp_path / "nas")) == {
        "code": "mount_tooling_missing",
        "params": {},
    }
    assert platform.attach_calls == []
    assert store.mounts() == {}


# --- the record and the reconcile ---


def test_a_queued_mount_reports_its_stage_before_the_worker_runs(service):
    subject, _platform, _store, tmp_path = service

    reply = subject.attach(
        hub_id="h1", entry=entry_for(PAYLOAD), path=str(tmp_path / "nas")
    )

    assert reply == {}
    assert subject.rows()[0]["state"] == "queued"


def test_the_reconcile_remounts_what_this_run_attached(service):
    subject, platform, _store, tmp_path = service
    location = str(tmp_path / "nas")
    assert attach(subject, path=location) == {}

    platform.attached.discard(location)
    subject.reconcile()

    assert len(platform.attach_calls) == 2
    assert subject.rows()[0]["is_attached"] is True


def test_a_mount_follows_the_host_its_entry_names_now(tmp_path):
    """The hub moved its share to another address: the remount takes the
    entry's host and the record is written back with it."""
    entries: list = []
    lines: list = []
    subject, platform, store, _hub = handler_on(
        tmp_path, entries=entries, log=lines.append
    )
    location = str(tmp_path / "nas")
    assert attach(subject, path=location) == {}
    assert platform.attach_calls[0]["share_url"] == "//127.0.0.1/media"
    record_id = mount_record_id("h1", "share_media", location)

    platform.attached.discard(location)
    entries.append(entry_for(dict(PAYLOAD, host="nas2")))
    subject.reconcile()

    assert platform.attach_calls[1]["share_url"] == "//127.0.0.1/media"
    assert store.mounts()[record_id]["host"] == "nas2"
    assert store.mounts()[record_id]["share"] == "media"
    assert subject.rows()[0]["host"] == "nas2"
    assert f"share moved to nas2: //nas2/media at {location}" in lines


def test_a_mount_whose_entry_is_absent_keeps_the_records_host(tmp_path):
    """The hub is away: its entries are gone, and the record stands."""
    lines: list = []
    subject, platform, store, _hub = handler_on(tmp_path, log=lines.append)
    location = str(tmp_path / "nas")
    assert attach(subject, path=location) == {}
    record_id = mount_record_id("h1", "share_media", location)

    platform.attached.discard(location)
    subject.reconcile()

    assert platform.attach_calls[1]["share_url"] == "//127.0.0.1/media"
    assert store.mounts()[record_id]["host"] == "hub"
    assert not any(line.startswith("share moved") for line in lines)


def test_an_entry_naming_the_same_host_writes_nothing_back(tmp_path):
    lines: list = []
    subject, platform, _store, _hub = handler_on(
        tmp_path, entries=[entry_for(PAYLOAD)], log=lines.append
    )
    location = str(tmp_path / "nas")
    assert attach(subject, path=location) == {}

    platform.attached.discard(location)
    subject.reconcile()

    assert platform.attach_calls[1]["share_url"] == "//127.0.0.1/media"
    assert not any(line.startswith("share moved") for line in lines)


def test_a_declined_authorization_is_typed_and_not_retried(service):
    subject, platform, store, tmp_path = service
    platform.attach_error = ShareAttachError("mount_not_authorized")
    location = str(tmp_path / "nas")

    assert attach(subject, path=location) == {}
    subject.reconcile()

    row = subject.rows()[0]
    assert row["state"] == "failed" and row["code"] == "mount_not_authorized"
    assert len(platform.attach_calls) == 1

    subject.reconcile()
    assert len(platform.attach_calls) == 1


@pytest.mark.parametrize(
    "code",
    [
        "share_login_rejected",
        "share_access_denied",
        "share_not_found",
        "share_session_conflict",
        "mount_timed_out",
        "pkexec_missing",
    ],
)
def test_a_share_refusal_the_person_must_act_on_is_not_retried(service, code):
    """Mounting again with the same login or the same share name would be
    refused again; the record waits, with the refusal on its row."""
    subject, platform, _store, tmp_path = service
    platform.attach_error = ShareAttachError(code)

    assert attach(subject, path=str(tmp_path / "nas")) == {}
    subject.reconcile()
    subject.reconcile()

    row = subject.rows()[0]
    shown = "share_hub_login_rejected" if code == "share_login_rejected" else code
    assert row["state"] == "failed" and row["code"] == shown
    assert len(platform.attach_calls) == 1


def test_an_unreachable_host_is_tried_again_on_the_timer(service):
    subject, platform, _store, tmp_path = service
    platform.attach_error = ShareAttachError("share_unreachable")

    assert attach(subject, path=str(tmp_path / "nas")) == {}
    subject.reconcile()

    assert subject.rows()[0]["code"] == "share_unreachable"
    assert len(platform.attach_calls) == 2


def test_a_failing_mount_is_a_typed_failed_row(service):
    subject, platform, _store, tmp_path = service
    platform.attach_error = ShareAttachError("mount_failed", "cifs refused")

    assert attach(subject, path=str(tmp_path / "nas")) == {}

    row = subject.rows()[0]
    assert row["state"] == "failed"
    assert row["code"] == "mount_failed"
    assert row["params"] == {"detail": "cifs refused"}


def test_detach_keeps_the_record_and_a_declared_shares_login(service):
    subject, platform, store, tmp_path = service
    location = str(tmp_path / "photos")
    assert attach_declared(subject, path=location) == {}
    (record_id,) = store.mounts()

    assert subject.detach(record_id=record_id) == {}

    assert platform.detach_calls == [location]
    assert record_id in store.mounts()
    assert (credentials_dir(tmp_path) / f"{record_id}.login").is_file()
    assert subject.rows()[0]["state"] == "detached"

    assert subject.remount(record_id=record_id) == {}
    subject.reconcile()
    assert subject.rows()[0]["state"] == "mounted"


def test_a_refusing_unmount_keeps_the_record(service):
    subject, platform, store, tmp_path = service
    location = str(tmp_path / "nas")
    assert attach(subject, path=location) == {}
    platform.detach_error = ShareAttachError("unmount_failed", "target busy")
    (record_id,) = store.mounts()

    refused = subject.detach(record_id=record_id)

    assert refused == {"code": "unmount_failed", "params": {"detail": "target busy"}}
    assert record_id in store.mounts()


def test_unmounting_an_unknown_record_is_refused(service):
    subject, _platform, _store, _tmp_path = service

    assert subject.detach(record_id="missing") == {
        "code": "unknown_request",
        "params": {},
    }


def test_release_detaches_everything_and_keeps_the_records(service):
    subject, platform, store, tmp_path = service
    assert attach(subject, path=str(tmp_path / "a")) == {}
    reply = subject.attach(
        hub_id="h1",
        entry=entry_for(dict(PAYLOAD, share="b"), entry_id="share_b"),
        path=str(tmp_path / "b"),
    )
    assert reply == {}
    subject.reconcile()
    assert len(platform.attached) == 2

    assert subject.release() == 2
    assert subject.release() == 0

    assert platform.attached == set()
    assert sorted(platform.detach_calls) == [str(tmp_path / "a"), str(tmp_path / "b")]
    assert len(store.mounts()) == 2
    assert [row["state"] for row in subject.rows()] == ["detached", "detached"]


def test_act_mounts_and_unmounts_by_typed_entry(service):
    subject, _platform, store, tmp_path = service
    location = str(tmp_path / "nas" / "media")

    outcome = subject.act(
        entries=[entry_for(PAYLOAD)],
        body={"action": "mount", "hub_id": "h1", "id": "share_media", "path": location},
    )
    assert outcome == {}
    (record_id,) = store.mounts()
    assert subject.state()["mounts"][0]["entry_id"] == "share_media"

    assert (
        subject.act(entries=[], body={"action": "unmount", "record_id": record_id})
        == {}
    )
    assert subject.rows()[0]["state"] == "detached"
    assert (
        subject.act(entries=[], body={"action": "mount", "record_id": record_id}) == {}
    )
    assert subject.act(entries=[], body={"action": "mount"}) == {
        "code": "unknown_request",
        "params": {},
    }
    assert subject.act(
        entries=[entry_for(PAYLOAD)],
        body={"action": "mount", "hub_id": "h2", "id": "share_media", "path": "/x"},
    ) == {"code": "unknown_request", "params": {}}
    assert subject.act(entries=[], body={"action": "share"}) == {
        "code": "unknown_request",
        "params": {},
    }


def test_a_record_of_an_earlier_run_is_not_mounted_by_itself(service, tmp_path):
    """The store outlives the process; what was mounted does not."""
    subject, platform, store, _tmp_path = service
    location = str(tmp_path / "nas")
    assert attach(subject, path=location) == {}
    platform.attached.discard(location)

    fresh = FileServiceHandler(
        platform=platform,
        store=store,
        credentials_dir=str(credentials_dir(tmp_path)),
        forwards=FakeForwards(),
        log=discard,
        open_service=FakeHub().open_service,
    )
    fresh.reconcile()

    assert len(platform.attach_calls) == 1
    assert fresh.rows()[0]["state"] == "detached"

    assert fresh.remount(record_id=fresh.rows()[0]["record_id"]) == {}
    fresh.reconcile()
    assert fresh.rows()[0]["state"] == "mounted"


def test_leftovers_of_an_unclean_exit_are_detached(service, tmp_path):
    subject, platform, store, _tmp_path = service
    location = str(tmp_path / "nas")
    assert attach(subject, path=location) == {}

    fresh = FileServiceHandler(
        platform=platform,
        store=store,
        credentials_dir=str(credentials_dir(tmp_path)),
        forwards=FakeForwards(),
        log=discard,
    )
    fresh.clear_leftovers()

    assert platform.detach_calls == [location]
    assert platform.attached == set()
    assert fresh.rows()[0]["state"] == "detached"


def test_a_mounts_credentials_file_an_unclean_exit_left_is_deleted(service, tmp_path):
    subject, _platform, store, _tmp_path = service
    assert attach(subject, path=str(tmp_path / "nas")) == {}
    (record_id,) = store.mounts()
    left = credentials_dir(tmp_path) / f"{record_id}.mount"
    left.write_text("username=media\npassword=hub-secret\n")  # scan: allow

    subject.clear_leftovers()

    assert not left.exists()


def test_a_clean_machine_has_no_mount_to_clear(service, tmp_path):
    subject, platform, _store, _tmp_path = service
    assert attach(subject, path=str(tmp_path / "nas")) == {}
    subject.release()
    platform.detach_calls.clear()

    subject.clear_leftovers()

    assert platform.detach_calls == []


def test_the_rows_carry_the_hub_and_no_account_field(service):
    subject, _platform, _store, tmp_path = service
    assert attach(subject, path=str(tmp_path / "nas")) == {}

    (row,) = subject.rows()

    assert "account" not in row
    assert row["hub_id"] == "h1"
    assert row["is_declared"] is False
    assert set(row) >= {"record_id", "hub_id", "entry_id", "path", "state", "code"}


def test_the_same_share_on_two_hubs_is_two_records(service):
    subject, platform, store, tmp_path = service
    assert attach(subject, path=str(tmp_path / "home")) == {}
    assert attach(subject, path=str(tmp_path / "office"), hub_id="h2") == {}

    assert sorted(record["hub_id"] for record in store.mounts().values()) == [
        "h1",
        "h2",
    ]
    assert len(platform.attached) == 2


def test_two_hubs_cannot_claim_one_mount_point(service):
    subject, platform, store, tmp_path = service
    location = str(tmp_path / "nas")
    assert attach(subject, path=location) == {}

    refused = attach(subject, path=location, hub_id="h2")

    assert refused == {"code": "mountpoint_in_use", "params": {"path": location}}
    assert [record["hub_id"] for record in store.mounts().values()] == ["h1"]
    assert len(platform.attach_calls) == 1


def test_a_failed_record_holds_no_place(service):
    subject, platform, store, tmp_path = service
    location = str(tmp_path / "nas")
    platform.attach_error = ShareAttachError("share_not_found", "")
    assert attach(subject, path=location) == {}
    assert subject.rows()[0]["state"] == "failed"
    platform.attach_error = None

    assert attach(subject, path=location, hub_id="h2") == {}

    assert [record["hub_id"] for record in store.mounts().values()] == ["h2"]
    assert platform.attached == {location}


def test_an_unmounted_record_holds_no_place(service):
    subject, platform, store, tmp_path = service
    location = str(tmp_path / "nas")
    assert attach(subject, path=location) == {}
    (record_id,) = store.mounts()
    assert subject.detach(record_id=record_id) == {}

    assert attach(subject, path=location, hub_id="h2") == {}

    assert [record["hub_id"] for record in store.mounts().values()] == ["h2"]
    assert platform.attached == {location}


def test_a_record_mounted_again_on_the_timer_keeps_its_place(service):
    subject, platform, store, tmp_path = service
    location = str(tmp_path / "nas")
    assert attach(subject, path=location) == {}
    platform.attached.discard(location)

    refused = attach(subject, path=location, hub_id="h2")

    assert refused == {"code": "mountpoint_in_use", "params": {"path": location}}


def test_a_left_hubs_records_and_logins_go_and_another_hubs_stay(service):
    subject, platform, store, tmp_path = service
    assert attach_declared(subject, path=str(tmp_path / "a")) == {}
    assert attach_declared(subject, path=str(tmp_path / "b"), hub_id="h2") == {}

    subject.release_hub("h1")
    dropped = subject.drop_withdrawn(hub_id="h1", entries=[])

    assert dropped == 1
    assert [record["hub_id"] for record in store.mounts().values()] == ["h2"]
    assert [path.suffix for path in credentials_dir(tmp_path).iterdir()] == [".login"]
    assert platform.attached == {str(tmp_path / "b")}


def test_a_failed_record_whose_entry_left_the_list_is_dropped(service):
    subject, platform, store, tmp_path = service
    platform.attach_error = ShareAttachError("share_not_found", "")
    assert attach_declared(subject, path=str(tmp_path / "home")) == {}
    platform.attach_error = None
    assert attach_declared(subject, path=str(tmp_path / "office"), hub_id="h2") == {}

    listed = [declared_entry("h1")]
    assert subject.drop_withdrawn(hub_id="h1", entries=listed) == 0
    assert subject.drop_withdrawn(hub_id="h2", entries=[]) == 0
    assert subject.drop_withdrawn(hub_id="h1", entries=[]) == 1

    assert [record["hub_id"] for record in store.mounts().values()] == ["h2"]
    assert len(os.listdir(credentials_dir(tmp_path))) == 1


def test_reconfiguring_the_same_share_at_its_path_is_not_in_use(service):
    subject, _platform, store, tmp_path = service
    location = str(tmp_path / "photos")
    assert attach_declared(subject, path=location) == {}

    assert attach_declared(subject, path=location, password="new") == {}

    assert len(store.mounts()) == 1


def test_release_hub_detaches_only_that_hubs_records(service):
    subject, platform, store, tmp_path = service
    assert attach(subject, path=str(tmp_path / "home")) == {}
    assert attach(subject, path=str(tmp_path / "office"), hub_id="h2") == {}

    assert subject.release_hub("h2") == 1
    assert subject.release_hub("h2") == 0

    assert platform.detach_calls == [str(tmp_path / "office")]
    assert platform.attached == {str(tmp_path / "home")}
    assert len(store.mounts()) == 2
    assert sorted((row["hub_id"], row["state"]) for row in subject.rows()) == [
        ("h1", "mounted"),
        ("h2", "detached"),
    ]
    subject.reconcile()
    assert platform.attached == {str(tmp_path / "home")}


def test_a_record_without_a_hub_is_unmounted_by_path_then_dropped(service):
    """What a 0.2.x build kept: mounted by path first, then forgotten."""
    subject, platform, store, tmp_path = service
    location = str(tmp_path / "old")
    store.set_mount(
        "old",
        {
            "entry_id": "share_media",
            "host": "hub",
            "share": "media",
            "username": "media",
            "path": location,
        },
    )
    platform.attached.add(location)
    credentials = credentials_dir(tmp_path)
    credentials.mkdir(parents=True)
    (credentials / "old.login").write_text("username=media")

    subject.clear_leftovers()

    assert platform.detach_calls == [location]
    assert store.mounts() == {}
    assert not (credentials / "old.login").exists()
    assert subject.rows() == []
    assert attach(subject, path=str(tmp_path / "new")) == {}
    assert [row["hub_id"] for row in subject.rows()] == ["h1"]


# --- the share comes from the hub's channel ---


def test_a_mount_takes_the_entrys_forward_and_unmount_ends_it(service):
    subject, platform, store, tmp_path = service
    location = str(tmp_path / "nas")

    assert attach(subject, path=location) == {}

    forwards = subject._forwards
    assert forwards.ensured == [("h1", "share_media", "file")]
    assert forwards.running == {("h1", "share_media"): FORWARD_PORT}
    assert platform.attach_calls[0]["port"] == FORWARD_PORT
    assert subject.rows()[0]["server"] == "127.0.0.1"
    (record_id,) = store.mounts()

    assert subject.detach(record_id=record_id) == {}

    assert forwards.running == {}


def test_a_refusal_the_person_must_act_on_ends_the_forward(service):
    subject, platform, _store, tmp_path = service
    platform.attach_error = ShareAttachError("share_login_rejected")

    assert attach(subject, path=str(tmp_path / "nas")) == {}

    assert subject.rows()[0]["code"] == "share_hub_login_rejected"
    assert subject._forwards.running == {}


def test_a_declared_shares_refused_login_keeps_its_own_code(service):
    subject, platform, _store, tmp_path = service
    platform.attach_error = ShareAttachError("share_login_rejected")

    assert attach_declared(subject, path=str(tmp_path / "photos")) == {}

    assert subject.rows()[0]["code"] == "share_login_rejected"


def test_a_forward_that_cannot_listen_fails_the_record(service):
    subject, platform, _store, tmp_path = service
    subject._forwards.error = OSError("no free loopback port")

    assert attach(subject, path=str(tmp_path / "nas")) == {}

    row = subject.rows()[0]
    assert (row["state"], row["code"]) == ("failed", "forward_failed")
    assert platform.attach_calls == []
    assert left_files(tmp_path) == []


def test_release_ends_the_forwards_with_the_mounts(service):
    subject, _platform, _store, tmp_path = service
    assert attach(subject, path=str(tmp_path / "nas")) == {}

    assert subject.release() == 1

    assert subject._forwards.running == {}


class FakeDrivePlatform(FakeClientPlatform):
    """A platform that maps a share to a drive letter, as Windows does."""

    os_name = "windows"
    mount_location_shape = "drive_letter"

    def validate_mount_location(self, *, location: str) -> "dict | None":
        return None

    def prepare_mount_location(self, *, location: str) -> "dict | None":
        return None

    def mount_location_choices(self) -> list:
        return ["Z:", "Y:"]

    def suggest_mount_location(self) -> str:
        return "Z:"


def drive_service(tmp_path, adapter_host=None, entries=(), **kwargs):
    subject, platform, _store, _hub = handler_on(
        tmp_path,
        platform=FakeDrivePlatform(),
        entries=list(entries),
        adapter_host=adapter_host,
        **kwargs,
    )
    return subject, platform


def test_windows_mounts_the_files_adapters_address_for_the_machine(tmp_path):
    asked = []

    def adapter_host(hub_id, machine, user):
        asked.append((hub_id, machine, user))
        return "198.19.255.2"  # scan: allow

    entry = dict(entry_for(PAYLOAD), device_id="d_nas")
    subject, platform = drive_service(tmp_path, adapter_host, [entry])

    assert attach(subject, path="Z:", entry=entry) == {}

    call = platform.attach_calls[0]
    assert call["share_url"] == "//198.19.255.2/media"  # scan: allow
    assert (call["port"], call["location"]) == (0, "Z:")
    assert asked == [("h1", "d_nas", "media")]
    assert subject._forwards.ensured == []


def test_windows_mounts_at_the_first_free_letter_when_none_is_named(tmp_path):
    subject, platform = drive_service(
        tmp_path, lambda hub_id, machine, user: "198.19.255.2"  # scan: allow
    )

    assert attach(subject, path="") == {}

    assert platform.attach_calls[0]["location"] == "Z:"


def test_a_declared_share_names_its_host_as_the_machine(tmp_path):
    asked = []

    def adapter_host(hub_id, machine, user):
        asked.append((machine, user))
        return "198.19.255.3"  # scan: allow

    subject, _platform = drive_service(tmp_path, adapter_host)

    assert attach(subject, path="Z:") == {}

    assert asked == [("hub", "media")]


def test_an_adapter_that_cannot_be_made_fails_the_record_once(tmp_path):
    subject, platform = drive_service(tmp_path)

    assert attach(subject, path="Z:") == {}
    subject.reconcile()

    row = subject.rows()[0]
    assert (row["state"], row["code"]) == ("failed", "files_adapter_unavailable")
    assert row["params"]["detail"]
    assert platform.attach_calls == []


def test_only_a_quit_lets_the_adapter_go(tmp_path):
    """Windows keeps an SMB connection to an address after its unmount; an
    adapter taken down and brought back under it fails the next mounts there
    as a refused login or a lost network name."""
    idle = []
    subject, _platform = drive_service(
        tmp_path,
        lambda hub_id, machine, user: "198.19.255.2",  # scan: allow
        on_adapter_idle=lambda: idle.append(1),
    )
    assert attach(subject, path="Z:") == {}
    assert attach(subject, path="Y:", hub_id="h2") == {}
    first, second = sorted(subject.rows(), key=lambda row: row["path"])

    assert subject.detach(record_id=first["record_id"]) == {}
    assert subject.detach(record_id=second["record_id"]) == {}
    assert subject.release_hub("h1") == 0
    assert idle == []

    subject.release()

    assert idle == [1]


def test_a_handler_with_no_adapter_refuses_the_windows_mount(tmp_path):
    subject, platform = drive_service(tmp_path)

    assert attach(subject, path="Z:") == {}

    assert subject.rows()[0]["code"] == "files_adapter_unavailable"


# --- a share of this machine itself ---


def test_windows_mounts_its_own_machines_share_from_the_loopback(tmp_path):
    asked = []

    def adapter_host(hub_id, machine, user):
        asked.append((hub_id, machine, user))
        return "198.19.255.2"  # scan: allow

    entry = dict(entry_for(PAYLOAD), device_id="d_self", is_own_machine=True)
    subject, platform = drive_service(tmp_path, adapter_host, [entry])

    assert attach(subject, path="Z:", entry=entry) == {}

    call = platform.attach_calls[0]
    assert call["share_url"] == "//127.0.0.1/media"
    assert (call["port"], call["location"]) == (0, "Z:")
    assert asked == []
    assert subject._forwards.ensured == []
    row = subject.rows()[0]
    assert (row["state"], row["code"], row["server"]) == ("mounted", "", "127.0.0.1")
    assert subject.adapter_pairs() == set()


def test_windows_keeps_the_adapter_for_another_machines_share(tmp_path):
    entry = dict(entry_for(PAYLOAD), device_id="d_nas", is_own_machine=False)
    subject, platform = drive_service(
        tmp_path, lambda hub_id, machine, user: "198.19.255.2", [entry]  # scan: allow
    )

    assert attach(subject, path="Z:", entry=entry) == {}

    assert (
        platform.attach_calls[0]["share_url"] == "//198.19.255.2/media"
    )  # scan: allow
    assert subject.adapter_pairs() == {("h1", "d_nas", "media")}


def test_linux_mounts_its_own_machines_share_through_its_forward(tmp_path):
    entry = dict(entry_for(PAYLOAD), device_id="d_self", is_own_machine=True)
    subject, platform, _store, _hub = handler_on(tmp_path, entries=[entry])

    assert attach(subject, path=str(tmp_path / "nas"), entry=entry) == {}

    call = platform.attach_calls[0]
    assert (call["share_url"], call["port"]) == ("//127.0.0.1/media", FORWARD_PORT)
    assert subject._forwards.ensured


def test_an_adapter_another_account_holds_does_not_stop_the_own_share(tmp_path):
    def adapter_host(hub_id, machine, user):
        raise ShareAttachError("files_adapter_in_use")

    entry = dict(entry_for(PAYLOAD), device_id="d_self", is_own_machine=True)
    subject, platform = drive_service(tmp_path, adapter_host, [entry])

    assert attach(subject, path="Z:", entry=entry) == {}

    row = subject.rows()[0]
    assert (row["state"], row["code"]) == ("mounted", "")
    assert platform.attach_calls[0]["share_url"] == "//127.0.0.1/media"


def test_a_refused_mount_says_so_in_the_log(tmp_path):
    """A mount that cannot start leaves a line naming why, not a log that
    ends at the queue."""
    lines: list = []
    subject, platform, _store, _hub = handler_on(
        tmp_path, entries=[entry_for(PAYLOAD)], log=lines.append
    )
    platform.attach_error = ShareAttachError("pkexec_missing")

    assert attach(subject, path=str(tmp_path / "nas")) == {}
    subject.reconcile()

    assert subject.rows()[0]["code"] == "pkexec_missing"
    assert any(
        line.startswith("could not mount //") and line.endswith(": pkexec_missing")
        for line in lines
    )


def test_the_logins_a_0_5_client_kept_are_deleted_at_start(tmp_path):
    subject = FileServiceHandler(
        platform=FakeClientPlatform(),
        store=ClientServiceStore(path=str(tmp_path / "state.json")),
        credentials_dir=str(tmp_path / "creds"),
        forwards=FakeForwards(),
        log=discard,
    )
    (tmp_path / "creds").mkdir()
    (tmp_path / "creds" / "r1.credentials").write_text("password=x\n")
    (tmp_path / "creds" / "r2.login").write_text("password=y\n")

    subject.clear_leftovers()

    assert sorted(os.listdir(str(tmp_path / "creds"))) == ["r2.login"]


def test_a_folder_share_entry_mounts_by_default_under_its_account_s_name(tmp_path):
    entry = entry_for(
        {**PAYLOAD, "share": "lab", "users": ["neutrino-ann"], "account": "ann"},
        entry_id="samba_folder_d1_lab_ann",
    )
    platform = ReadingPlatform()

    assert default_place(entry, platform) == os.path.join(
        platform.home(), "remote", "lab-lab-ann"
    )


def test_two_accounts_of_a_folder_share_mount_through_two_pairs(tmp_path):
    asked = []

    def adapter_host(hub_id, machine, user):
        asked.append((machine, user))
        return f"198.19.255.{len(asked) + 1}"  # scan: allow

    entries = [
        dict(
            entry_for(
                {**PAYLOAD, "share": "lab", "users": [user], "account": account},
                entry_id=f"samba_folder_d1_lab_{account}",
            ),
            device_id="d1",
        )
        for account, user in (("ann", "neutrino-ann"), ("bob", "neutrino-bob"))
    ]
    subject, platform = drive_service(tmp_path, adapter_host, entries)

    assert attach(subject, path="Y:", entry=entries[0]) == {}
    assert attach(subject, path="Z:", entry=entries[1]) == {}

    assert asked == [("d1", "neutrino-ann"), ("d1", "neutrino-bob")]
    assert [call["share_url"] for call in platform.attach_calls] == [
        "//198.19.255.2/lab",  # scan: allow
        "//198.19.255.3/lab",  # scan: allow
    ]
    assert subject.adapter_pairs() == {
        ("h1", "d1", "neutrino-ann"),
        ("h1", "d1", "neutrino-bob"),
    }
