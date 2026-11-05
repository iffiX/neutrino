"""A share's folder, read by whoever owns its place.

What these pin: in an account's place the read is one ``/bin/sh`` the
platform's step-down starts as that account, here run as the test's own
user and recorded, and it reads a real folder, a missing one, a file, a
link at the last level and a folder the account cannot reach; in root's
place, every level root's, the folder is opened level by level with no link
followed and no account is asked; a link or a folder others may write in
root's place reads as a link. The reader takes each share that cannot be
served out of a configuration with its code, reads each folder the state
names again at the report only once 30 seconds old, and asks once for a
configure task when a folder reads otherwise than the last apply read it,
gone, back, a link or no longer one, and never for a folder it cannot reach.
"""

import os
import pwd

import pytest

from neutrino_agent.modules.samba import folder_reader
from neutrino_agent.modules.samba.config import SambaConfig
from neutrino_agent.modules.samba.constants import SAMBA_FOLDER_SHELL
from neutrino_agent.modules.samba.folder_reader import (
    SambaFolderReader,
    folder_refusal,
    read_posix_folder,
)


class Platform:
    """A machine whose accounts' commands run as the test's own user, each recorded."""

    os_name = "linux"

    def __init__(self):
        self.asked: list = []

    def account_process(self, account, argv):
        self.asked.append((account, list(argv)))
        return list(argv), {}


@pytest.fixture
def platform():
    return Platform()


def test_a_folder_in_an_accounts_place_is_read_as_that_account(tmp_path, platform):
    (tmp_path / "share").mkdir()
    owner = pwd.getpwuid(os.stat(tmp_path).st_uid).pw_name

    found = read_posix_folder(str(tmp_path / "share"), platform=platform)

    assert found == "folder"
    assert platform.asked == [
        (owner, ["/bin/sh", "-c", SAMBA_FOLDER_SHELL, str(tmp_path / "share")])
    ]


def test_a_missing_folder_and_a_file_read_as_missing(tmp_path, platform):
    (tmp_path / "file").write_text("")

    assert read_posix_folder(str(tmp_path / "gone"), platform=platform) == "missing"
    assert read_posix_folder(str(tmp_path / "file"), platform=platform) == "missing"
    assert not (tmp_path / "gone").exists()


def test_a_link_at_the_last_level_reads_as_a_link(tmp_path, platform):
    (tmp_path / "real").mkdir()
    (tmp_path / "share").symlink_to(tmp_path / "real")

    assert read_posix_folder(str(tmp_path / "share"), platform=platform) == "link"


def test_a_link_named_with_a_trailing_slash_still_reads_as_a_link(tmp_path, platform):
    (tmp_path / "real").mkdir()
    (tmp_path / "share").symlink_to(tmp_path / "real")

    assert read_posix_folder(f"{tmp_path}/share/", platform=platform) == "link"
    assert platform.asked[0][1][-1] == str(tmp_path / "share")


def test_a_link_above_the_last_level_in_the_accounts_place_is_followed_as_the_account(
    tmp_path, platform
):
    (tmp_path / "real" / "share").mkdir(parents=True)
    (tmp_path / "way").symlink_to(tmp_path / "real")

    found = read_posix_folder(str(tmp_path / "way" / "share"), platform=platform)

    assert found == "folder"
    assert len(platform.asked) == 1


@pytest.mark.skipif(os.geteuid() == 0, reason="root reaches every folder")
def test_a_folder_the_account_cannot_reach_reads_as_unreachable(tmp_path, platform):
    closed = tmp_path / "closed"
    (closed / "share").mkdir(parents=True)
    closed.chmod(0)
    try:
        found = read_posix_folder(str(closed / "share"), platform=platform)
    finally:
        closed.chmod(0o755)

    assert found == "unreachable"


def test_a_folder_in_roots_place_is_walked_by_root_with_no_link_followed(
    tmp_path, platform, monkeypatch
):
    monkeypatch.setattr(folder_reader, "place_owner", lambda path: 0)
    (tmp_path / "real").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "real")
    (tmp_path / "file").write_text("")

    assert read_posix_folder(str(tmp_path / "real"), platform=platform) == "folder"
    assert read_posix_folder(str(tmp_path / "gone"), platform=platform) == "missing"
    assert read_posix_folder(str(tmp_path / "file"), platform=platform) == "missing"
    assert read_posix_folder(str(tmp_path / "link"), platform=platform) == "link"
    assert platform.asked == []


def test_a_link_or_a_shared_folder_in_roots_place_reads_as_a_link(
    tmp_path, platform, monkeypatch
):
    monkeypatch.setattr(folder_reader, "place_owner", lambda path: None)
    (tmp_path / "real").mkdir()

    assert read_posix_folder(str(tmp_path / "real"), platform=platform) == "link"
    assert platform.asked == []


def test_an_owner_with_no_account_reads_as_unreachable(tmp_path, platform, monkeypatch):
    monkeypatch.setattr(folder_reader, "place_owner", lambda path: 4_000_000)

    assert read_posix_folder(str(tmp_path), platform=platform) == "unreachable"


def test_the_verbs_answer_names_the_path():
    assert folder_refusal("folder", "/srv/a") == {}
    assert folder_refusal("missing", "/srv/a") == {
        "code": "share_path_missing",
        "params": {"path": "/srv/a"},
    }
    assert folder_refusal("unreachable", "/srv/a")["code"] == "share_path_missing"
    assert folder_refusal("link", "/srv/a") == {
        "code": "share_path_link",
        "params": {"path": "/srv/a"},
    }


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class Folders:
    """What each folder reads as, every read counted."""

    def __init__(self, found=None):
        self.found = dict(found or {})
        self.reads: list = []

    def __call__(self, path):
        self.reads.append(path)
        return self.found.get(path, "folder")


SECTION = {
    "shares": [
        {"name": "ann", "path": "/home/ann", "valid_users": ["neutrino-ann"]},
        {"name": "media", "path": "/srv/media", "valid_users": ["neutrino-ann"]},
        {"name": "lab", "path": "/srv/lab", "valid_users": ["neutrino-ann"]},
        {"name": "nobody", "path": "/srv/nobody", "valid_users": []},
    ],
    "users": ["neutrino-ann"],
}


def test_an_apply_takes_each_share_that_cannot_be_served_out_with_its_code():
    folders = Folders({"/srv/media": "missing", "/srv/lab": "link"})
    reader = SambaFolderReader(read=folders, clock=Clock())

    kept, left_off = reader.served(SambaConfig.from_dict(SECTION))

    assert [share.name for share in kept.shares] == ["ann", "nobody"]
    assert left_off == [
        {
            "code": "share_path_missing",
            "params": {"name": "media", "path": "/srv/media"},
        },
        {"code": "share_path_link", "params": {"name": "lab", "path": "/srv/lab"}},
    ]
    assert "/srv/nobody" not in folders.reads


def test_the_report_reads_each_folder_of_the_state_once_per_half_minute():
    folders = Folders({"/srv/media": "missing", "/srv/lab": "unreachable"})
    clock = Clock()
    reader = SambaFolderReader(read=folders, clock=clock)
    reader.take_config(SECTION)
    asked: list = []

    reader.check(lambda: asked.append(1))
    reader.check(lambda: asked.append(1))
    clock.now += 31
    folders.found = {}
    reader.check(lambda: asked.append(1))

    assert folders.reads == ["/home/ann", "/srv/media", "/srv/lab"] * 2
    assert asked == []


def test_a_folder_gone_and_back_asks_for_a_task_once_for_each_change():
    folders = Folders()
    clock = Clock()
    reader = SambaFolderReader(read=folders, clock=clock)
    reader.take_config(SECTION)
    reader.served(SambaConfig.from_dict(SECTION))
    asked: list = []

    folders.found = {"/srv/media": "missing"}
    clock.now += 31
    reader.check(lambda: asked.append("gone"))
    clock.now += 31
    reader.check(lambda: asked.append("gone"))
    reader.served(SambaConfig.from_dict(SECTION))
    folders.found = {}
    clock.now += 31
    reader.check(lambda: asked.append("back"))

    assert asked == ["gone", "back"]


def test_a_folder_the_account_cannot_reach_asks_for_nothing():
    folders = Folders()
    clock = Clock()
    reader = SambaFolderReader(read=folders, clock=clock)
    reader.take_config(SECTION)
    reader.served(SambaConfig.from_dict(SECTION))
    asked: list = []

    folders.found = {"/srv/media": "unreachable"}
    clock.now += 31
    reader.check(lambda: asked.append(1))

    assert asked == []


def test_a_folder_that_reads_otherwise_than_the_last_apply_asks_for_a_task_once():
    folders = Folders()
    clock = Clock()
    reader = SambaFolderReader(read=folders, clock=clock)
    reader.take_config(SECTION)
    reader.served(SambaConfig.from_dict(SECTION))
    asked: list = []

    folders.found = {"/srv/lab": "link"}
    clock.now += 31
    reader.check(lambda: asked.append("lab"))
    clock.now += 31
    reader.check(lambda: asked.append("lab"))

    assert asked == ["lab"]
    reader.served(SambaConfig.from_dict(SECTION))
    folders.found = {}
    clock.now += 31
    reader.check(lambda: asked.append("back"))
    assert asked == ["lab", "back"]


def test_a_removed_configuration_asks_for_nothing():
    folders = Folders()
    clock = Clock()
    reader = SambaFolderReader(read=folders, clock=clock)
    reader.take_config(SECTION)
    reader.served(SambaConfig.from_dict(SECTION))
    reader.forget()
    folders.found = {"/srv/lab": "link"}
    clock.now += 31
    asked: list = []

    reader.check(lambda: asked.append(1))

    assert asked == []
