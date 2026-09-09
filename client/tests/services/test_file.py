"""The file service: the platform does the privileged part, typed refusals.

The password is proven absent three ways: never on argv, never in the
store, never in a state payload. Records are 0600 files of the person's
own; a declined authorization is typed and not retried on the timer.
"""

import json
import os

import pytest

from neutrino_client.platforms.base import ShareAttachError
from neutrino_client.services.file import FileServiceHandler, mount_record_id
from neutrino_client.services.store import ClientServiceStore
from tests.conftest import FakeClientPlatform, discard

PAYLOAD = {"protocol": "smb", "host": "hub", "share": "media"}


def entry_for(payload):
    return {
        "id": "share_media",
        "type": "file",
        "title": "media",
        "payload": payload,
        "is_healthy": True,
        "source": "module",
        "description": "",
    }


@pytest.fixture
def service(tmp_path):
    platform = FakeClientPlatform()
    store = ClientServiceStore(path=str(tmp_path / "state.json"))
    subject = FileServiceHandler(
        platform=platform,
        store=store,
        credentials_dir=str(tmp_path / "config" / "mount_credentials"),
        log=discard,
    )
    return subject, platform, store, tmp_path


def attach(subject, *, path, password="pw"):
    """Queue a mount and, when accepted, run the worker's pass by hand."""
    reply = subject.attach(
        entry_id="share_media",
        payload=PAYLOAD,
        username="media",
        password=password,
        path=path,
    )
    if reply == {}:
        subject.reconcile()
    return reply


def test_a_creatable_path_is_made_and_mounted(service):
    subject, platform, store, tmp_path = service
    location = str(tmp_path / "home" / "nas" / "media")

    assert attach(subject, path=location) == {}

    assert platform.fs_calls == [("mkdir", location)]
    call = platform.attach_calls[0]
    assert call["share_url"] == "//hub/media" and call["location"] == location
    record = store.mounts()[mount_record_id("share_media", location)]
    assert record["is_enabled"] is True
    assert "password" not in record and "account" not in record


def test_the_password_lands_only_in_a_0600_credentials_file(service):
    subject, platform, _store, tmp_path = service
    location = str(tmp_path / "home" / "nas")

    outcome = subject.act(
        entries=[entry_for(PAYLOAD)],
        body={
            "action": "mount",
            "id": "share_media",
            "username": "media",
            "password": "pw-secret",  # scan: allow
            "path": location,
        },
    )
    assert outcome == {}
    subject.reconcile()

    credentials_path = platform.attach_calls[0]["credentials_path"]
    assert "pw-secret" in open(credentials_path, encoding="utf-8").read()
    assert oct(os.stat(credentials_path).st_mode & 0o777) == "0o600"
    assert oct(os.stat(os.path.dirname(credentials_path)).st_mode & 0o777) == "0o700"
    assert "password" not in platform.attach_calls[0]
    raw = (tmp_path / "state.json").read_bytes()
    assert b"pw-secret" not in raw and b'"password"' not in raw
    payload = json.dumps(subject.state())
    assert "pw-secret" not in payload and '"password"' not in payload


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


def test_a_queued_mount_reports_its_stage_before_the_worker_runs(service):
    subject, _platform, _store, tmp_path = service

    reply = subject.attach(
        entry_id="share_media",
        payload=PAYLOAD,
        username="media",
        password="pw",
        path=str(tmp_path / "nas"),
    )

    assert reply == {}
    assert subject.rows()[0]["state"] == "queued"


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
    assert len(platform.attach_calls) == 1


def test_the_reconcile_remounts_an_enabled_record(service):
    subject, platform, _store, tmp_path = service
    location = str(tmp_path / "nas")
    assert attach(subject, path=location) == {}

    platform.attached.discard(location)
    subject.reconcile()

    assert len(platform.attach_calls) == 2
    assert subject.rows()[0]["is_attached"] is True


def test_a_declined_authorization_is_typed_and_not_retried(service):
    subject, platform, store, tmp_path = service
    platform.attach_error = ShareAttachError("mount_not_authorized")
    location = str(tmp_path / "nas")

    assert attach(subject, path=location) == {}
    subject.reconcile()

    row = subject.rows()[0]
    assert row["state"] == "failed" and row["code"] == "mount_not_authorized"
    assert len(platform.attach_calls) == 1
    (record,) = store.mounts().values()
    assert record["is_enabled"] is False


def test_a_failing_mount_is_a_typed_failed_row(service):
    subject, platform, _store, tmp_path = service
    platform.attach_error = ShareAttachError("mount_failed", "cifs refused")

    assert attach(subject, path=str(tmp_path / "nas")) == {}

    row = subject.rows()[0]
    assert row["state"] == "failed"
    assert row["code"] == "mount_failed"
    assert row["params"] == {"detail": "cifs refused"}


def test_detach_keeps_the_record_and_the_login(service):
    subject, platform, store, tmp_path = service
    location = str(tmp_path / "nas")
    assert attach(subject, path=location) == {}
    (record_id,) = store.mounts()

    assert subject.detach(record_id=record_id) == {}

    assert platform.detach_calls == [location]
    assert store.mounts()[record_id]["is_enabled"] is False
    assert os.path.isfile(platform.attach_calls[0]["credentials_path"])
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
    entry_b = dict(PAYLOAD, share="b")
    reply = subject.attach(
        entry_id="share_b",
        payload=entry_b,
        username="media",
        password="pw",
        path=str(tmp_path / "b"),
    )
    assert reply == {}
    subject.reconcile()
    assert len(platform.attached) == 2

    subject.release()
    subject.release()

    assert platform.attached == set()
    assert sorted(platform.detach_calls) == [str(tmp_path / "a"), str(tmp_path / "b")]
    assert len(store.mounts()) == 2
    assert all(record["is_enabled"] for record in store.mounts().values())


def test_act_mounts_and_unmounts_by_typed_entry(service):
    subject, _platform, store, tmp_path = service
    location = str(tmp_path / "nas" / "media")

    outcome = subject.act(
        entries=[entry_for(PAYLOAD)],
        body={
            "action": "mount",
            "id": "share_media",
            "username": "media",
            "password": "pw",  # scan: allow
            "path": location,
        },
    )
    assert outcome == {}
    (record_id,) = store.mounts()
    assert subject.state()["mounts"][0]["entry_id"] == "share_media"

    assert (
        subject.act(entries=[], body={"action": "unmount", "record_id": record_id})
        == {}
    )
    assert store.mounts()[record_id]["is_enabled"] is False
    assert (
        subject.act(entries=[], body={"action": "mount", "record_id": record_id}) == {}
    )
    assert subject.act(entries=[], body={"action": "mount"}) == {
        "code": "unknown_request",
        "params": {},
    }
    assert subject.act(entries=[], body={"action": "share"}) == {
        "code": "unknown_request",
        "params": {},
    }


def test_the_rows_carry_no_account_field(service):
    subject, _platform, _store, tmp_path = service
    assert attach(subject, path=str(tmp_path / "nas")) == {}

    (row,) = subject.rows()

    assert "account" not in row
    assert set(row) >= {"record_id", "entry_id", "path", "state", "code", "params"}
