"""The file service: path rules by identity, typed refusals, remounting."""

import os

import pytest

from neutrino_agent.platforms.base import AgentPlatform, ShareAttachError
from neutrino_agent.services.file import FileServiceHandler, mount_record_id
from neutrino_agent.services.store import MachineServiceStore

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
        self.attached.discard(location)

    def is_share_attached(self, *, location: str) -> bool:
        return location in self.attached


def discard(message: str) -> None:
    """Swallow the log lines."""


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
    return subject.attach(
        account=account,
        is_privileged=is_privileged,
        entry_id="hub_share_media",
        payload=PAYLOAD,
        username="media",
        password=password,
        path=path,
    )


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


def test_missing_tooling_is_typed_and_keeps_no_record(service):
    subject, platform, store, tmp_path = service
    platform.attach_error = ShareAttachError("cifs_missing")

    reply = attach(subject, path=str(tmp_path / "nas"))

    assert reply == {"code": "cifs_missing", "params": {}}
    assert store.mounts() == {}


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
    assert store.mounts() == {}
    assert not os.path.isfile(platform.attach_calls[0]["credentials_path"])


def test_a_relative_path_is_refused(service):
    subject, _platform, _store, _tmp_path = service

    assert attach(subject, path="nas/media") == {"code": "fs_refused", "params": {}}


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
    assert store.mounts() == {}

    refused = subject.act(
        entries=[], account="root", is_privileged=True, body={"action": "mount"}
    )
    assert refused == {"code": "unknown_request", "params": {}}
