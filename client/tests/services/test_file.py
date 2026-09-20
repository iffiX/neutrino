"""The file service: the platform does the privileged part, typed refusals.

The password is proven absent three ways: never on argv, never in the
store, never in a state payload. A record is the hub and entry a share came
from, the login and the path this person typed; what is attached is this
run's own, so a record of an earlier run waits to be asked for. A declined
authorization is typed and not retried on the timer. One hub's records are
let go of without touching another's, two hubs cannot share one mount
point, and a record an older build wrote without a hub is unmounted by path
and dropped at start.
"""

import json
import os

import pytest

from neutrino_client.exceptions import ShareAttachError
from neutrino_client.services.file import FileServiceHandler, mount_record_id
from neutrino_client.services.store import ClientServiceStore
from tests.conftest import FakeClientPlatform, discard

PAYLOAD = {"protocol": "smb", "host": "hub", "share": "media"}


def entry_for(payload, hub_id="h1"):
    return {
        "hub_id": hub_id,
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


def attach(subject, *, path, password="pw", hub_id="h1", entry_id="share_media"):
    """Queue a mount and, when accepted, run the worker's pass by hand."""
    reply = subject.attach(
        hub_id=hub_id,
        entry_id=entry_id,
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
    record = store.mounts()[mount_record_id("h1", "share_media", location)]
    assert record["path"] == location
    assert record["hub_id"] == "h1"
    assert "password" not in record and "account" not in record


def test_the_password_lands_only_in_a_0600_credentials_file(service):
    subject, platform, _store, tmp_path = service
    location = str(tmp_path / "home" / "nas")

    outcome = subject.act(
        entries=[entry_for(PAYLOAD)],
        body={
            "action": "mount",
            "hub_id": "h1",
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
        hub_id="h1",
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


def test_the_reconcile_remounts_what_this_run_attached(service):
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

    subject.reconcile()
    assert len(platform.attach_calls) == 1


@pytest.mark.parametrize(
    "code",
    [
        "share_login_rejected",
        "share_access_denied",
        "share_not_found",
        "share_session_conflict",
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
    assert row["state"] == "failed" and row["code"] == code
    assert len(platform.attach_calls) == 1


def test_an_unreachable_host_is_tried_again_on_the_timer(service):
    subject, platform, _store, tmp_path = service
    platform.attach_error = ShareAttachError("share_unreachable")

    assert attach(subject, path=str(tmp_path / "nas")) == {}
    subject.reconcile()

    assert subject.rows()[0]["code"] == "share_unreachable"
    assert len(platform.attach_calls) == 2


def test_a_new_password_for_the_same_share_replaces_the_saved_login(service):
    """The second attach for one share is the person correcting the login:
    the old credentials file goes, the new one is what the mount reads."""
    subject, platform, _store, tmp_path = service
    location = str(tmp_path / "nas")
    platform.attach_error = ShareAttachError("share_login_rejected")
    assert attach(subject, path=location, password="wrong") == {}
    first = platform.attach_calls[0]["credentials_path"]
    assert "password=wrong" in open(first, encoding="utf-8").read()

    platform.attach_error = None
    assert attach(subject, path=location, password="right") == {}

    assert subject.rows()[0]["is_attached"] is True
    assert subject.rows()[0]["code"] == ""
    assert "password=right" in open(first, encoding="utf-8").read()
    assert len(subject.rows()) == 1


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
    assert record_id in store.mounts()
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
        hub_id="h1",
        entry_id="share_b",
        payload=entry_b,
        username="media",
        password="pw",
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
        body={
            "action": "mount",
            "hub_id": "h1",
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
        credentials_dir=str(tmp_path / "config" / "mount_credentials"),
        log=discard,
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
        credentials_dir=str(tmp_path / "config" / "mount_credentials"),
        log=discard,
    )
    fresh.clear_leftovers()

    assert platform.detach_calls == [location]
    assert platform.attached == set()
    assert fresh.rows()[0]["state"] == "detached"


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


def test_reconfiguring_the_same_share_at_its_path_is_not_in_use(service):
    subject, _platform, store, tmp_path = service
    location = str(tmp_path / "nas")
    assert attach(subject, path=location) == {}

    assert attach(subject, path=location, password="new") == {}

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
    credentials = tmp_path / "config" / "mount_credentials"
    credentials.mkdir(parents=True)
    (credentials / "old.credentials").write_text("username=media")

    subject.clear_leftovers()

    assert platform.detach_calls == [location]
    assert store.mounts() == {}
    assert not (credentials / "old.credentials").exists()
    assert subject.rows() == []
    assert attach(subject, path=str(tmp_path / "new")) == {}
    assert [row["hub_id"] for row in subject.rows()] == ["h1"]
