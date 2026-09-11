"""The macOS platform: peercred identity, mount_smbfs as the person, mount.

A mount needs no root on macOS and rides ``mount_smbfs`` with the username
on the share URL and the password typed at the tool's own prompt on a
pseudo-terminal, never on an argument vector; attachment is read from the
mount table; the language is the first the account prefers.
"""

import collections
import os
import struct
import subprocess

import pytest

import neutrino_client.platforms.darwin as darwin_module
from neutrino_client.exceptions import ShareAttachError
from neutrino_client.platforms.darwin import DarwinPlatform
from tests.conftest import completed

PwdEntry = collections.namedtuple("PwdEntry", "pw_name pw_uid pw_shell pw_dir")

MOUNT_TABLE = (
    "/dev/disk3s1s1 on / (apfs, sealed, local, read-only, journaled)\n"
    "//alice@hub/media on /Users/alice/my nas (smbfs, nodev, nosuid, "
    "mounted by alice)\n"
    "map auto_home on /System/Volumes/Data/home (autofs, automounted, nobrowse)\n"
)


class FakePeerConnection:
    def __init__(self, credential: bytes):
        self._credential = credential
        self.asked = []

    def getsockopt(self, level, option, length):
        self.asked.append((level, option, length))
        return self._credential[:length]


class CommandRecorder:
    """Stands in for ``subprocess.run``, remembering every call."""

    def __init__(self, results=None):
        self.commands = []
        self.inputs = []
        self.results = list(results or [])

    def __call__(self, command, **kwargs):
        self.commands.append(list(command))
        self.inputs.append(kwargs.get("input"))
        if self.results:
            return self.results.pop(0)
        return completed(command)


class TerminalRecorder:
    """Stands in for the pseudo-terminal run, remembering what was typed."""

    def __init__(self, code=0, output=""):
        self.runs = []
        self.code = code
        self.output = output

    def __call__(self, argv, *, prompt, answer, timeout_s):
        self.runs.append((list(argv), prompt, answer))
        return self.code, self.output


def xucred(uid: int) -> bytes:
    """A ``struct xucred`` as the kernel fills it: version 0, the uid, one
    group, then the group list padded to its full length."""
    return struct.pack("IIh2x16I", 0, uid, 1, *([uid] + [0] * 15))


def test_the_config_dir_is_under_application_support(monkeypatch):
    monkeypatch.undo()
    monkeypatch.setenv("HOME", "/Users/alice")

    assert (
        DarwinPlatform().config_dir()
        == "/Users/alice/Library/Application Support/Neutrino Client"
    )


def test_the_socket_lives_under_the_persons_caches(monkeypatch):
    monkeypatch.setenv("HOME", "/Users/alice")

    assert (
        DarwinPlatform().control_socket_path()
        == "/Users/alice/Library/Caches/neutrino_client/neutrino_client.sock"
    )


def test_the_same_uid_is_the_same_user(monkeypatch):
    entry = PwdEntry("alice", os.getuid(), "/bin/zsh", "/Users/alice")
    monkeypatch.setattr(darwin_module.pwd, "getpwuid", lambda uid: entry)
    connection = FakePeerConnection(xucred(os.getuid()))

    identity = DarwinPlatform().read_peer_identity(connection)

    assert identity == {"account": "alice", "uid": os.getuid(), "is_same_user": True}
    assert connection.asked == [(0, darwin_module.LOCAL_PEERCRED, 76)]


def test_another_uid_is_not_the_same_user(monkeypatch):
    entry = PwdEntry("bob", 4242, "/bin/zsh", "/Users/bob")
    monkeypatch.setattr(darwin_module.pwd, "getpwuid", lambda uid: entry)
    connection = FakePeerConnection(xucred(4242))

    identity = DarwinPlatform().read_peer_identity(connection)

    assert identity["is_same_user"] is False
    assert identity["account"] == "bob"


def test_a_uid_that_names_no_account_still_answers(monkeypatch):
    def unknown(uid):
        raise KeyError(uid)

    monkeypatch.setattr(darwin_module.pwd, "getpwuid", unknown)
    connection = FakePeerConnection(xucred(4242))

    identity = DarwinPlatform().read_peer_identity(connection)

    assert identity == {"account": "4242", "uid": 4242, "is_same_user": False}


def test_the_language_is_the_first_the_account_prefers(monkeypatch):
    recorder = CommandRecorder(
        [completed(stdout='(\n    "zh-Hans-CN",\n    "en-US"\n)\n')]
    )
    monkeypatch.setattr(darwin_module.subprocess, "run", recorder)

    assert DarwinPlatform().system_language() == "zh-CN"
    assert recorder.commands == [["defaults", "read", "-g", "AppleLanguages"]]


def test_an_english_first_preference_reads_as_english(monkeypatch):
    recorder = CommandRecorder([completed(stdout='(\n    "en-GB",\n    "zh-Hans"\n)')])
    monkeypatch.setattr(darwin_module.subprocess, "run", recorder)

    assert DarwinPlatform().system_language() == "en"


def test_a_defaults_that_cannot_be_asked_falls_back_to_the_locale(monkeypatch):
    def refuse(command, **kwargs):
        raise OSError("no defaults here")

    monkeypatch.setattr(darwin_module.subprocess, "run", refuse)
    monkeypatch.setenv("LANG", "zh_CN.UTF-8")
    assert DarwinPlatform().system_language() == "zh-CN"

    recorder = CommandRecorder([completed(returncode=1, stderr="no such key")])
    monkeypatch.setattr(darwin_module.subprocess, "run", recorder)
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    assert DarwinPlatform().system_language() == "en"


def test_attach_names_the_user_on_the_url_and_types_the_password(monkeypatch, tmp_path):
    credentials = tmp_path / "r1.credentials"
    credentials.write_text("username=media\npassword=s3cret\n")  # scan: allow
    terminal = TerminalRecorder()
    monkeypatch.setattr(darwin_module, "run_on_pty", terminal)

    DarwinPlatform().attach_share(
        share_url="//hub/media",
        location="/Users/alice/nas/media",
        credentials_path=str(credentials),
    )

    assert terminal.runs == [
        (
            ["mount_smbfs", "//media@hub/media", "/Users/alice/nas/media"],
            "Password",
            "s3cret\n",  # scan: allow
        )
    ]
    assert "s3cret" not in " ".join(terminal.runs[0][0])  # scan: allow


def test_a_username_with_reserved_characters_is_escaped_on_the_url(
    monkeypatch, tmp_path
):
    credentials = tmp_path / "r1.credentials"
    credentials.write_text("username=lab@corp\npassword=x\n")  # scan: allow
    terminal = TerminalRecorder()
    monkeypatch.setattr(darwin_module, "run_on_pty", terminal)

    DarwinPlatform().attach_share(
        share_url="//hub/media", location="/mnt", credentials_path=str(credentials)
    )

    assert terminal.runs[0][0][1] == "//lab%40corp@hub/media"


def test_a_gone_credentials_file_is_refused_before_the_tool(monkeypatch, tmp_path):
    terminal = TerminalRecorder()
    monkeypatch.setattr(darwin_module, "run_on_pty", terminal)

    with pytest.raises(ShareAttachError) as caught:
        DarwinPlatform().attach_share(
            share_url="//hub/media",
            location="/mnt",
            credentials_path=str(tmp_path / "gone"),
        )
    assert caught.value.code == "credentials_missing"
    assert terminal.runs == []


def test_an_unreadable_share_url_is_refused_before_the_tool(monkeypatch, tmp_path):
    terminal = TerminalRecorder()
    monkeypatch.setattr(darwin_module, "run_on_pty", terminal)

    with pytest.raises(ShareAttachError) as caught:
        DarwinPlatform().attach_share(
            share_url="hub", location="/mnt", credentials_path=str(tmp_path)
        )
    assert caught.value.code == "mount_failed"
    assert terminal.runs == []


def test_a_refused_mount_carries_the_tools_words(monkeypatch, tmp_path):
    credentials = tmp_path / "r1.credentials"
    credentials.write_text("username=media\npassword=x\n")  # scan: allow
    terminal = TerminalRecorder(
        code=64,
        output="Password for hub:\r\nmount_smbfs: server rejected the connection",
    )
    monkeypatch.setattr(darwin_module, "run_on_pty", terminal)

    with pytest.raises(ShareAttachError) as caught:
        DarwinPlatform().attach_share(
            share_url="//hub/media", location="/mnt", credentials_path=str(credentials)
        )
    assert caught.value.code == "mount_failed"
    assert caught.value.detail.endswith("server rejected the connection")


def test_a_tool_that_cannot_start_is_a_failed_mount(monkeypatch, tmp_path):
    credentials = tmp_path / "r1.credentials"
    credentials.write_text("username=media\npassword=x\n")  # scan: allow

    def refuse(argv, *, prompt, answer, timeout_s):
        raise OSError("out of ptys")

    monkeypatch.setattr(darwin_module, "run_on_pty", refuse)

    with pytest.raises(ShareAttachError) as caught:
        DarwinPlatform().attach_share(
            share_url="//hub/media", location="/mnt", credentials_path=str(credentials)
        )
    assert caught.value.code == "mount_failed"
    assert caught.value.detail == "out of ptys"


def test_detach_runs_umount_on_the_location(monkeypatch):
    recorder = CommandRecorder()
    monkeypatch.setattr(darwin_module.subprocess, "run", recorder)

    DarwinPlatform().detach_share(location="/Users/alice/nas/media")

    assert recorder.commands == [["umount", "/Users/alice/nas/media"]]


def test_a_failed_unmount_carries_the_tools_words(monkeypatch):
    recorder = CommandRecorder(
        [completed(returncode=1, stderr="umount: /mnt: Resource busy")]
    )
    monkeypatch.setattr(darwin_module.subprocess, "run", recorder)

    with pytest.raises(ShareAttachError) as caught:
        DarwinPlatform().detach_share(location="/mnt")
    assert caught.value.code == "unmount_failed"
    assert caught.value.detail == "umount: /mnt: Resource busy"


def test_an_umount_that_cannot_run_is_a_failed_unmount(monkeypatch):
    def refuse(command, **kwargs):
        raise subprocess.TimeoutExpired(command, 1)

    monkeypatch.setattr(darwin_module.subprocess, "run", refuse)

    with pytest.raises(ShareAttachError) as caught:
        DarwinPlatform().detach_share(location="/mnt")
    assert caught.value.code == "unmount_failed"


def test_the_tooling_is_mount_smbfs(monkeypatch):
    monkeypatch.setattr(darwin_module.shutil, "which", lambda name: "/sbin/mount_smbfs")
    assert DarwinPlatform().has_mount_tooling() is True

    monkeypatch.setattr(darwin_module.shutil, "which", lambda name: None)
    assert DarwinPlatform().has_mount_tooling() is False


def test_attachment_is_read_from_the_mount_table(monkeypatch):
    recorder = CommandRecorder([completed(stdout=MOUNT_TABLE)] * 3)
    monkeypatch.setattr(darwin_module.subprocess, "run", recorder)
    platform = DarwinPlatform()

    assert platform.is_share_attached(location="/Users/alice/my nas")
    assert not platform.is_share_attached(location="/Users/alice/other")
    assert not platform.is_share_attached(location="/Users/alice")
    assert recorder.commands == [["mount"]] * 3


def test_a_mount_table_that_cannot_be_read_answers_not_attached(monkeypatch):
    def refuse(command, **kwargs):
        raise OSError("no mount here")

    monkeypatch.setattr(darwin_module.subprocess, "run", refuse)
    assert DarwinPlatform().is_share_attached(location="/mnt") is False

    recorder = CommandRecorder([completed(returncode=1)])
    monkeypatch.setattr(darwin_module.subprocess, "run", recorder)
    assert DarwinPlatform().is_share_attached(location="/mnt") is False


def test_a_mount_location_is_a_free_form_path_under_the_home():
    platform = DarwinPlatform()

    assert platform.mount_location_shape == "path"
    assert platform.mount_location_choices() == []
    assert platform.suggest_mount_location() == ""
    assert platform.validate_mount_location(location="nas/media") == {
        "code": "mountpoint_invalid",
        "params": {},
    }
    assert platform.validate_mount_location(location="/Users/alice/nas") is None


def test_preparing_a_mount_location_makes_the_directory(tmp_path):
    location = tmp_path / "nas" / "media"

    assert DarwinPlatform().prepare_mount_location(location=str(location)) is None
    assert location.is_dir()

    (location / "kept").write_text("")
    assert DarwinPlatform().prepare_mount_location(location=str(location)) == {
        "code": "mountpoint_not_empty",
        "params": {},
    }


def test_a_link_opens_through_open(monkeypatch):
    recorder = CommandRecorder()
    monkeypatch.setattr(darwin_module.subprocess, "run", recorder)

    DarwinPlatform().open_url("https://hub.lan/")

    assert recorder.commands == [["open", "https://hub.lan/"]]


def test_a_link_falls_back_to_the_browser_module_without_open(monkeypatch):
    opened = []

    def refuse(command, **kwargs):
        raise OSError("no open here")

    monkeypatch.setattr(darwin_module.subprocess, "run", refuse)
    monkeypatch.setattr(darwin_module.ClientPlatform, "open_url", opened.append)

    DarwinPlatform().open_url("https://hub.lan/")

    assert opened == ["https://hub.lan/"]


def test_a_program_that_asks_gets_its_answer_on_a_terminal_of_its_own():
    import sys

    platform = DarwinPlatform()
    code, output = platform.run_answering(
        [sys.executable, "-c", "print('ok' if input('go? (y/N) ') == 'y' else 'no')"],
        prompt="(y/N)",
        answer="y\n",
        timeout_s=20,
    )

    assert code == 0
    assert "ok" in output


def test_a_program_that_cannot_start_answers_127():
    code, _ = DarwinPlatform().run_answering(
        ["/nonexistent/program"], prompt="?", answer="y\n", timeout_s=5
    )
    assert code == 127


def test_a_windowed_program_starts_with_no_handles_of_this_process(monkeypatch):
    import sys

    process = DarwinPlatform().start_on_screen([sys.executable, "-c", "pass"])

    assert process.wait(timeout=20) == 0
