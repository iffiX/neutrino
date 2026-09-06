"""The file service: path rules by identity, typed refusals, remounting."""

import json
import os

import pytest

from neutrino_agent.platforms.base import AgentPlatform, ShareAttachError
from neutrino_agent.services.file import FileServiceHandler, mount_record_id
from neutrino_agent.services.store import MachineServiceStore
from tests.conftest import discard

PAYLOAD = {"protocol": "smb", "host": "hub", "share": "media"}


class FakeMountPlatform(AgentPlatform):
    os_name = "linux"

    def __init__(self):
        self.attached = set()
        self.attach_calls = []
        self.detach_calls = []
        self.made_directories = []
        self.writable = set()
        self.attach_error = None
        self.detach_error = None
        self.has_tooling = True
        self.location_refusal = None
        # An observer a test may hang on the slow step, to read state mid-step.
        self.on_attach = None

    def has_mount_tooling(self) -> bool:
        return self.has_tooling

    def validate_mount_location(self, *, location: str):
        if self.location_refusal is not None:
            return self.location_refusal
        return super().validate_mount_location(location=location)

    def write_share_credentials(self, *, credentials_path, username, password):
        os.makedirs(os.path.dirname(credentials_path), exist_ok=True)
        with open(credentials_path, "w", encoding="utf-8") as stream:
            stream.write(f"username={username}\npassword={password}\n")

    def is_path_writable(self, *, account: str, path: str) -> bool:
        return path in self.writable

    def make_directory(self, *, account: str, path: str) -> None:
        self.made_directories.append((account, path))
        os.makedirs(path, exist_ok=True)

    def attach_share(
        self,
        *,
        account,
        share_url,
        username,
        password,
        location,
        credentials_path="",
    ) -> None:
        if self.on_attach is not None:
            self.on_attach()
        self.attach_calls.append(
            {
                "account": account,
                "share_url": share_url,
                "username": username,
                "password": password,
                "location": location,
                "credentials_path": credentials_path,
            }
        )
        if self.attach_error is not None:
            raise self.attach_error
        if password:
            os.makedirs(os.path.dirname(credentials_path), exist_ok=True)
            with open(credentials_path, "w", encoding="utf-8") as stream:
                stream.write(f"username={username}\npassword={password}\n")
        if not os.path.isfile(credentials_path):
            raise ShareAttachError("credentials_missing")
        self.attached.add(location)

    def detach_share(self, *, location: str) -> None:
        self.detach_calls.append(location)
        if self.detach_error is not None:
            raise self.detach_error
        self.attached.discard(location)

    def is_share_attached(self, *, location: str) -> bool:
        return location in self.attached


@pytest.fixture
def service(tmp_path):
    platform = FakeMountPlatform()
    store = MachineServiceStore(path=str(tmp_path / "services.json"))
    subject = FileServiceHandler(
        platform=platform,
        store=store,
        credentials_dir=str(tmp_path / "creds"),
        log=discard,
    )
    return subject, platform, store, tmp_path


def attach(subject, *, path, account="root", is_privileged=True, password="pw"):
    """Queue a mount and, when accepted, run the worker's pass by hand."""
    reply = subject.attach(
        account=account,
        is_privileged=is_privileged,
        entry_id="hub_share_media",
        payload=PAYLOAD,
        username="media",
        password=password,
        path=path,
    )
    if reply == {}:
        subject.reconcile()
    return reply


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


def test_a_creatable_path_is_made_and_mounted(service):
    subject, platform, store, tmp_path = service
    location = str(tmp_path / "nas" / "media")

    assert attach(subject, path=location) == {}

    assert platform.made_directories == [("", location)]
    call = platform.attach_calls[0]
    assert call["share_url"] == "//hub/media" and call["location"] == location
    record_id = mount_record_id("hub_share_media", location)
    record = store.mounts()[record_id]
    assert record["account"] == "root" and record["is_enabled"] is True
    assert "password" not in record


def test_an_ordinary_identity_may_attach_only_where_it_writes(service):
    subject, platform, store, tmp_path = service
    location = str(tmp_path / "elsewhere")

    refused = attach(subject, path=location, account="alice", is_privileged=False)
    assert refused == {"code": "fs_refused", "params": {}}
    assert platform.attach_calls == []

    platform.writable.add(location)
    assert attach(subject, path=location, account="alice", is_privileged=False) == {}
    assert platform.made_directories[-1] == ("alice", location)
    assert store.mounts()


def test_a_mount_with_the_module_absent_is_refused_typed(service):
    subject, platform, store, tmp_path = service
    platform.has_tooling = False
    location = str(tmp_path / "nas")

    # The service installs nothing: the tooling is the samba_mount module's.
    assert attach(subject, path=location) == {
        "code": "module_missing",
        "params": {"module": "samba_mount"},
    }
    assert platform.attach_calls == []
    assert store.mounts() == {}


def test_a_remount_with_the_module_absent_is_refused_typed(service):
    subject, platform, store, tmp_path = service
    location = str(tmp_path / "nas")
    assert attach(subject, path=location) == {}
    record_id = mount_record_id("hub_share_media", location)
    subject.detach(account="root", is_privileged=True, record_id=record_id)
    platform.has_tooling = False

    refused = subject.remount(account="root", is_privileged=True, record_id=record_id)

    assert refused == {"code": "module_missing", "params": {"module": "samba_mount"}}


def test_the_reconcile_reports_module_missing_when_the_tooling_goes(service):
    subject, platform, store, tmp_path = service
    location = str(tmp_path / "nas")
    assert attach(subject, path=location) == {}
    platform.attached.clear()
    platform.attach_calls.clear()
    platform.has_tooling = False

    subject.reconcile()

    row = subject.rows()[0]
    assert row["state"] == "failed"
    assert row["code"] == "module_missing"
    assert row["params"] == {"module": "samba_mount"}
    assert platform.attach_calls == []


def test_a_queued_mount_reports_its_stage_before_the_worker_runs(service):
    subject, platform, store, tmp_path = service
    location = str(tmp_path / "nas")
    reply = subject.attach(
        account="root",
        is_privileged=True,
        entry_id="hub_share_media",
        payload=PAYLOAD,
        username="media",
        password="pw",
        path=location,
    )

    assert reply == {}
    assert subject.rows()[0]["state"] == "queued"


def test_the_stage_machine_is_observable_at_each_step(service):
    subject, platform, _store, tmp_path = service
    seen = []
    platform.on_attach = lambda: seen.append(subject.rows()[0]["state"])
    location = str(tmp_path / "nas")

    reply = subject.attach(
        account="root",
        is_privileged=True,
        entry_id="hub_share_media",
        payload=PAYLOAD,
        username="media",
        password="pw",  # scan: allow
        path=location,
    )
    assert reply == {}
    assert subject.rows()[0]["state"] == "queued"

    subject.reconcile()

    assert seen == ["mounting"]
    assert subject.rows()[0]["state"] == "mounted"


def test_the_password_lands_only_in_the_credentials_file(service):
    subject, platform, _store, tmp_path = service
    location = str(tmp_path / "nas")

    outcome = subject.act(
        entries=[entry_for(PAYLOAD)],
        account="root",
        is_privileged=True,
        body={
            "action": "mount",
            "id": "hub_share_media",
            "username": "media",
            "password": "pw-secret",  # scan: allow
            "path": location,
        },
    )
    assert outcome == {}
    subject.reconcile()

    credentials_path = platform.attach_calls[0]["credentials_path"]
    assert "pw-secret" in open(credentials_path, encoding="utf-8").read()
    # The mount itself is handed the credentials file, never the password.
    assert all(call["password"] == "" for call in platform.attach_calls)
    raw = (tmp_path / "services.json").read_bytes()
    assert b"pw-secret" not in raw and b'"password"' not in raw
    payload = json.dumps(subject.state())
    assert "pw-secret" not in payload and '"password"' not in payload


def test_a_gone_credentials_file_reports_and_waits(service):
    subject, platform, _store, tmp_path = service
    location = str(tmp_path / "nas")
    assert attach(subject, path=location) == {}
    credentials_path = platform.attach_calls[0]["credentials_path"]

    os.unlink(credentials_path)
    platform.attached.discard(location)
    subject.reconcile()

    row = subject.rows()[0]
    assert row["code"] == "credentials_missing"
    assert row["is_attached"] is False
    # Only the first attach carried the password; the remount attempt waits.
    assert len(platform.attach_calls) == 1


def test_the_reconcile_remounts_an_enabled_record(service):
    subject, platform, _store, tmp_path = service
    location = str(tmp_path / "nas")
    assert attach(subject, path=location) == {}

    platform.attached.discard(location)
    subject.reconcile()

    assert len(platform.attach_calls) == 2
    remount = platform.attach_calls[1]
    assert remount["password"] == ""
    assert remount["credentials_path"] == platform.attach_calls[0]["credentials_path"]
    assert subject.rows()[0]["is_attached"] is True


def test_a_restarted_handler_remounts_the_stores_records(service):
    subject, _platform, store, tmp_path = service
    location = str(tmp_path / "nas")
    assert attach(subject, path=location) == {}

    fresh_platform = FakeMountPlatform()
    revived = FileServiceHandler(
        platform=fresh_platform,
        store=store,
        credentials_dir=str(tmp_path / "creds"),
        log=discard,
    )
    revived.reconcile()

    (call,) = fresh_platform.attach_calls
    assert call["location"] == location and call["password"] == ""
    assert revived.rows()[0]["state"] == "mounted"


def test_the_remount_runs_as_the_records_own_account(service):
    subject, platform, _store, tmp_path = service
    location = str(tmp_path / "alice_nas")
    platform.writable.add(location)
    assert attach(subject, path=location, account="alice", is_privileged=False) == {}

    platform.attached.discard(location)
    os.rmdir(location)
    subject.reconcile()

    assert platform.made_directories[-1] == ("alice", location)
    assert platform.attach_calls[-1]["account"] == "alice"
    assert subject.rows()[0]["is_attached"] is True


def test_a_mount_point_with_content_blocks_the_remount(service):
    subject, platform, _store, tmp_path = service
    location = str(tmp_path / "nas")
    assert attach(subject, path=location) == {}

    platform.attached.discard(location)
    (tmp_path / "nas" / "leftover").write_text("kept")
    subject.reconcile()

    row = subject.rows()[0]
    assert row["state"] == "failed" and row["code"] == "mountpoint_not_empty"
    assert len(platform.attach_calls) == 1


def test_a_failing_mount_is_a_typed_failed_row(service):
    subject, platform, _store, tmp_path = service
    platform.attach_error = ShareAttachError("mount_failed", "cifs refused")
    location = str(tmp_path / "nas")

    assert attach(subject, path=location) == {}

    row = subject.rows()[0]
    assert row["state"] == "failed"
    assert row["code"] == "mount_failed"
    assert row["params"] == {"detail": "cifs refused"}


def test_a_mount_point_that_is_a_file_is_refused(service):
    subject, platform, _store, tmp_path = service
    occupied = tmp_path / "occupied"
    occupied.write_text("data")

    assert attach(subject, path=str(occupied)) == {
        "code": "mountpoint_not_empty",
        "params": {},
    }
    assert platform.attach_calls == []


def test_detach_is_the_records_own_account_or_privileged(service):
    subject, platform, store, tmp_path = service
    location = str(tmp_path / "nas")
    platform.writable.add(location)
    assert attach(subject, path=location, account="bob", is_privileged=False) == {}
    (record_id,) = store.mounts()

    refused = subject.detach(account="alice", is_privileged=False, record_id=record_id)
    assert refused == {"code": "control_scope_refused", "params": {}}

    assert subject.detach(account="bob", is_privileged=False, record_id=record_id) == {}
    assert platform.detach_calls == [location]
    kept = store.mounts()[record_id]
    assert kept["is_enabled"] is False
    assert os.path.isfile(platform.attach_calls[0]["credentials_path"])

    assert (
        subject.remount(account="bob", is_privileged=False, record_id=record_id) == {}
    )
    subject.reconcile()
    assert subject.rows()[0]["state"] == "mounted"
    assert platform.attach_calls[-1]["password"] == ""


def test_unmounting_an_unknown_record_is_refused(service):
    subject, _platform, _store, _tmp_path = service

    refused = subject.detach(account="root", is_privileged=True, record_id="missing")

    assert refused == {"code": "unknown_request", "params": {}}


def test_a_refusing_unmount_keeps_the_record(service):
    subject, platform, store, tmp_path = service
    location = str(tmp_path / "nas")
    assert attach(subject, path=location) == {}
    platform.detach_error = ShareAttachError("unmount_failed", "target busy")
    (record_id,) = store.mounts()

    refused = subject.detach(account="root", is_privileged=True, record_id=record_id)

    assert refused == {"code": "unmount_failed", "params": {"detail": "target busy"}}
    assert record_id in store.mounts()
    assert os.path.isfile(platform.attach_calls[0]["credentials_path"])


def test_a_relative_path_is_refused(service):
    subject, _platform, _store, _tmp_path = service

    assert attach(subject, path="nas/media") == {
        "code": "mountpoint_invalid",
        "params": {},
    }


def test_the_mount_location_is_judged_by_the_platform(service):
    subject, platform, _store, tmp_path = service
    platform.location_refusal = {"code": "mountpoint_invalid", "params": {}}

    assert attach(subject, path=str(tmp_path / "point")) == {
        "code": "mountpoint_invalid",
        "params": {},
    }
    assert platform.attach_calls == []


def entry_for(payload):
    return {
        "id": "hub_share_media",
        "type": "file",
        "title": "media",
        "payload": payload,
        "is_healthy": True,
        "source": "module",
        "description": "",
    }


def test_act_mounts_and_unmounts_by_typed_entry(service):
    subject, platform, store, tmp_path = service
    location = str(tmp_path / "nas" / "media")

    outcome = subject.act(
        entries=[entry_for(PAYLOAD)],
        account="root",
        is_privileged=True,
        body={
            "action": "mount",
            "id": "hub_share_media",
            "username": "media",
            "password": "pw",  # scan: allow
            "path": location,
        },
    )
    assert outcome == {}
    (record_id,) = store.mounts()
    assert subject.state()["mounts"][0]["entry_id"] == "hub_share_media"

    outcome = subject.act(
        entries=[entry_for(PAYLOAD)],
        account="root",
        is_privileged=True,
        body={"action": "unmount", "record_id": record_id},
    )
    assert outcome == {}
    assert store.mounts()[record_id]["is_enabled"] is False

    outcome = subject.act(
        entries=[],
        account="root",
        is_privileged=True,
        body={"action": "mount", "record_id": record_id},
    )
    assert outcome == {}

    refused = subject.act(
        entries=[], account="root", is_privileged=True, body={"action": "mount"}
    )
    assert refused == {"code": "unknown_request", "params": {}}
