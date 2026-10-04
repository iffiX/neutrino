"""The macOS platform: peercred identity, a volume the system mounts, mount.

A mount asks the system for a network volume through ``osascript``, the
script and its password on standard input and never on an argument vector;
the mount point the system picked is read back from the mount table, a
share already mounted is not mounted twice, and ``diskutil unmount`` ejects
it; the language is the first the account prefers.
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
    "//alice@nas/media on /Users/alice/my nas (smbfs, nodev, nosuid, "
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


def xucred(uid: int) -> bytes:
    """A ``struct xucred`` as the kernel fills it: version 0, the uid, one
    group, then the group list padded to its full length."""
    return struct.pack("IIh2x16I", 0, uid, 1, *([uid] + [0] * 15))


def test_the_config_dir_is_under_application_support(monkeypatch):
    monkeypatch.undo()
    monkeypatch.setenv("HOME", "/Users/alice")

    assert (
        DarwinPlatform().config_dir()
        == "/Users/alice/Library/Application Support/Neutrino/client"
    )


def test_the_log_is_under_the_persons_logs(monkeypatch):
    monkeypatch.setenv("HOME", "/Users/alice")

    assert DarwinPlatform().log_dir() == "/Users/alice/Library/Logs/Neutrino/client"


def test_the_socket_lives_in_the_persons_client_directory():
    platform = DarwinPlatform()

    assert platform.control_socket_path() == os.path.join(
        platform.config_dir(), "client.sock"
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


def credentials_file(tmp_path, username="media", password="s3cret"):
    credentials = tmp_path / "r1.credentials"
    credentials.write_text(f"username={username}\npassword={password}\n")
    return str(credentials)


def volume_table(source="//media@hub/media", location="/Volumes/media"):
    return (
        MOUNT_TABLE
        + f"{source} on {location} (smbfs, nodev, nosuid, mounted by alice)\n"
    )


def test_attach_asks_the_system_to_mount_a_volume_on_osascripts_stdin(
    monkeypatch, tmp_path
):
    recorder = CommandRecorder(
        [completed(stdout=MOUNT_TABLE), completed(), completed(stdout=volume_table())]
    )
    monkeypatch.setattr(darwin_module.subprocess, "run", recorder)

    mounted = DarwinPlatform().attach_share(
        share_url="//hub/media",
        location="",
        credentials_path=credentials_file(tmp_path),
    )

    assert mounted == "/Volumes/media"
    assert recorder.commands == [["mount"], ["osascript", "-"], ["mount"]]
    assert recorder.inputs[1] == (
        'mount volume "smb://media@hub/media" as user name "media"'
        ' with password "s3cret"\n'  # scan: allow
    )
    for argv in recorder.commands:
        assert "s3cret" not in " ".join(argv)  # scan: allow


def test_a_forwarded_share_is_mounted_at_the_loopback_and_its_port(
    monkeypatch, tmp_path
):
    table = volume_table(source="//media@127.0.0.1:20445/media")
    recorder = CommandRecorder(
        [completed(stdout=MOUNT_TABLE), completed(), completed(stdout=table)]
    )
    monkeypatch.setattr(darwin_module.subprocess, "run", recorder)

    mounted = DarwinPlatform().attach_share(
        share_url="//127.0.0.1/media",
        port=20445,
        location="",
        credentials_path=credentials_file(tmp_path),
    )

    assert mounted == "/Volumes/media"
    assert recorder.inputs[1] == (
        'mount volume "smb://media@127.0.0.1:20445/media" as user name "media"'
        ' with password "s3cret"\n'  # scan: allow
    )


def test_a_volume_of_another_forward_is_not_taken_as_mounted(monkeypatch, tmp_path):
    other = volume_table(source="//media@127.0.0.1:20446/media")
    table = volume_table(
        source="//media@127.0.0.1:20445/media", location="/Volumes/media-1"
    )
    recorder = CommandRecorder(
        [completed(stdout=other), completed(), completed(stdout=other + table)]
    )
    monkeypatch.setattr(darwin_module.subprocess, "run", recorder)

    mounted = DarwinPlatform().attach_share(
        share_url="//127.0.0.1/media",
        port=20445,
        location="",
        credentials_path=credentials_file(tmp_path),
    )

    assert mounted == "/Volumes/media-1"
    assert recorder.commands == [["mount"], ["osascript", "-"], ["mount"]]


def test_the_system_picks_the_next_free_name_and_it_is_read_back(monkeypatch, tmp_path):
    table = volume_table(location="/Volumes/media-1")
    recorder = CommandRecorder(
        [completed(stdout=MOUNT_TABLE), completed(), completed(stdout=table)]
    )
    monkeypatch.setattr(darwin_module.subprocess, "run", recorder)

    mounted = DarwinPlatform().attach_share(
        share_url="//hub/media",
        location="",
        credentials_path=credentials_file(tmp_path),
    )

    assert mounted == "/Volumes/media-1"


def test_quotes_and_backslashes_are_escaped_in_the_script(monkeypatch, tmp_path):
    recorder = CommandRecorder(
        [completed(stdout=MOUNT_TABLE), completed(), completed(stdout=volume_table())]
    )
    monkeypatch.setattr(darwin_module.subprocess, "run", recorder)

    DarwinPlatform().attach_share(
        share_url="//hub/media",
        location="",
        credentials_path=credentials_file(
            tmp_path, username='lab\\"bob', password='p"w\\x'  # scan: allow
        ),
    )

    script = recorder.inputs[1]
    assert 'as user name "lab\\\\\\"bob"' in script
    assert 'with password "p\\"w\\\\x"' in script  # scan: allow


def test_the_user_and_share_are_percent_encoded_in_the_url():
    script = darwin_module.mount_volume_script(
        host="hub", share="my files", username="lab@corp", password="x"
    )

    assert script.startswith('mount volume "smb://lab%40corp@hub/my%20files"')


def test_a_share_the_system_already_mounted_is_not_mounted_twice(monkeypatch, tmp_path):
    table = volume_table(source="//GUEST:@HUB/Media", location="/Volumes/Media")
    recorder = CommandRecorder([completed(stdout=table)])
    monkeypatch.setattr(darwin_module.subprocess, "run", recorder)

    mounted = DarwinPlatform().attach_share(
        share_url="//hub/media",
        location="",
        credentials_path=credentials_file(tmp_path),
    )

    assert mounted == "/Volumes/Media"
    assert recorder.commands == [["mount"]]


def test_a_share_of_another_host_is_not_taken_as_mounted(monkeypatch, tmp_path):
    other = volume_table(source="//media@nas/media", location="/Volumes/media")
    table = volume_table(location="/Volumes/media-1")
    recorder = CommandRecorder(
        [completed(stdout=other), completed(), completed(stdout=table)]
    )
    monkeypatch.setattr(darwin_module.subprocess, "run", recorder)

    DarwinPlatform().attach_share(
        share_url="//hub/media",
        location="",
        credentials_path=credentials_file(tmp_path),
    )

    assert recorder.commands[1] == ["osascript", "-"]


def test_a_mount_the_table_does_not_show_is_a_failed_mount(monkeypatch, tmp_path):
    recorder = CommandRecorder(
        [completed(stdout=MOUNT_TABLE), completed(), completed(stdout=MOUNT_TABLE)]
    )
    monkeypatch.setattr(darwin_module.subprocess, "run", recorder)

    with pytest.raises(ShareAttachError) as caught:
        DarwinPlatform().attach_share(
            share_url="//hub/media",
            location="",
            credentials_path=credentials_file(tmp_path),
        )
    assert caught.value.code == "mount_failed"


def test_a_gone_credentials_file_is_refused_before_the_tool(monkeypatch, tmp_path):
    recorder = CommandRecorder()
    monkeypatch.setattr(darwin_module.subprocess, "run", recorder)

    with pytest.raises(ShareAttachError) as caught:
        DarwinPlatform().attach_share(
            share_url="//hub/media",
            location="",
            credentials_path=str(tmp_path / "gone"),
        )
    assert caught.value.code == "credentials_missing"
    assert recorder.commands == []


def test_an_unreadable_share_url_is_refused_before_the_tool(monkeypatch, tmp_path):
    recorder = CommandRecorder()
    monkeypatch.setattr(darwin_module.subprocess, "run", recorder)

    with pytest.raises(ShareAttachError) as caught:
        DarwinPlatform().attach_share(
            share_url="hub", location="", credentials_path=str(tmp_path)
        )
    assert caught.value.code == "mount_failed"
    assert recorder.commands == []


@pytest.mark.parametrize(
    ("said", "code"),
    [
        (
            "execution error: The user name or password is wrong. (-5023)",
            "share_login_rejected",
        ),
        ("execution error: Access not granted. (-5000)", "share_access_denied"),
        ("execution error: File not found. (-43)", "share_not_found"),
        (
            "execution error: An error of type -5014 has occurred. (-5014)",
            "share_not_found",
        ),
        ("execution error: An I/O error occurred. (-36)", "share_unreachable"),
        ("execution error: Connection failed.", "share_unreachable"),
        ("execution error: User canceled. (-128)", "mount_not_authorized"),
        ("execution error: s3cret was refused. (-1)", "mount_failed"),  # scan: allow
    ],
)
def test_osascripts_words_name_the_refusal_and_never_carry_the_password(
    monkeypatch, tmp_path, said, code
):
    recorder = CommandRecorder(
        [completed(stdout=MOUNT_TABLE), completed(returncode=1, stderr=f"0:80: {said}")]
    )
    monkeypatch.setattr(darwin_module.subprocess, "run", recorder)

    with pytest.raises(ShareAttachError) as caught:
        DarwinPlatform().attach_share(
            share_url="//hub/media",
            location="",
            credentials_path=credentials_file(tmp_path),
        )
    assert caught.value.code == code
    assert "s3cret" not in caught.value.detail  # scan: allow
    assert "s3cret" not in str(caught.value)  # scan: allow


def test_the_script_waits_ten_minutes_for_the_systems_dialogs(monkeypatch, tmp_path):
    timeouts = []

    def record(command, **kwargs):
        timeouts.append((command, kwargs.get("timeout")))
        if command == ["mount"]:
            return completed(stdout=MOUNT_TABLE)
        return completed(returncode=1, stderr="execution error: (-128)")

    monkeypatch.setattr(darwin_module.subprocess, "run", record)

    with pytest.raises(ShareAttachError):
        DarwinPlatform().attach_share(
            share_url="//hub/media",
            location="",
            credentials_path=credentials_file(tmp_path),
        )
    assert darwin_module.MOUNT_SCRIPT_TIMEOUT_S == 600
    assert (["osascript", "-"], 600) in timeouts


def test_an_osascript_that_does_not_finish_is_a_timed_out_mount(monkeypatch, tmp_path):
    def refuse(command, **kwargs):
        if command == ["mount"]:
            return completed(stdout=MOUNT_TABLE)
        raise subprocess.TimeoutExpired(command, 600)

    monkeypatch.setattr(darwin_module.subprocess, "run", refuse)

    with pytest.raises(ShareAttachError) as caught:
        DarwinPlatform().attach_share(
            share_url="//hub/media",
            location="",
            credentials_path=credentials_file(tmp_path),
        )
    assert caught.value.code == "mount_timed_out"
    assert "s3cret" not in str(caught.value)  # scan: allow


def test_detach_ejects_the_mount_point_with_diskutil(monkeypatch, tmp_path):
    recorder = CommandRecorder()
    monkeypatch.setattr(darwin_module.subprocess, "run", recorder)
    location = tmp_path / "media"
    location.mkdir()

    DarwinPlatform().detach_share(location=str(location))

    assert recorder.commands == [["diskutil", "unmount", str(location)]]
    assert location.is_dir()


def test_a_failed_unmount_carries_the_tools_words(monkeypatch):
    recorder = CommandRecorder(
        [completed(returncode=1, stderr="Unmount of /Volumes/media failed")]
    )
    monkeypatch.setattr(darwin_module.subprocess, "run", recorder)

    with pytest.raises(ShareAttachError) as caught:
        DarwinPlatform().detach_share(location="/Volumes/media")
    assert caught.value.code == "unmount_failed"
    assert caught.value.detail == "Unmount of /Volumes/media failed"


def test_a_diskutil_that_cannot_run_is_a_failed_unmount(monkeypatch):
    def refuse(command, **kwargs):
        raise subprocess.TimeoutExpired(command, 1)

    monkeypatch.setattr(darwin_module.subprocess, "run", refuse)

    with pytest.raises(ShareAttachError) as caught:
        DarwinPlatform().detach_share(location="/Volumes/media")
    assert caught.value.code == "unmount_failed"


def test_the_tooling_is_osascript(monkeypatch):
    monkeypatch.setattr(darwin_module.shutil, "which", lambda name: "/usr/bin/" + name)
    assert DarwinPlatform().has_mount_tooling() is True

    monkeypatch.setattr(darwin_module.shutil, "which", lambda name: None)
    assert DarwinPlatform().has_mount_tooling() is False


def test_attachment_is_read_from_the_mount_table(monkeypatch):
    recorder = CommandRecorder([completed(stdout=volume_table())] * 3)
    monkeypatch.setattr(darwin_module.subprocess, "run", recorder)
    platform = DarwinPlatform()

    assert platform.is_share_attached(location="/Volumes/media")
    assert platform.is_share_attached(location="/Users/alice/my nas")
    assert not platform.is_share_attached(location="/Volumes")
    assert recorder.commands == [["mount"]] * 3


def test_an_empty_location_is_not_attached_and_asks_nothing(monkeypatch):
    recorder = CommandRecorder()
    monkeypatch.setattr(darwin_module.subprocess, "run", recorder)

    assert DarwinPlatform().is_share_attached(location="") is False
    assert recorder.commands == []


def test_a_mount_table_that_cannot_be_read_answers_not_attached(monkeypatch):
    def refuse(command, **kwargs):
        raise OSError("no mount here")

    monkeypatch.setattr(darwin_module.subprocess, "run", refuse)
    assert DarwinPlatform().is_share_attached(location="/mnt") is False

    recorder = CommandRecorder([completed(returncode=1)])
    monkeypatch.setattr(darwin_module.subprocess, "run", recorder)
    assert DarwinPlatform().is_share_attached(location="/mnt") is False


def test_a_mount_location_is_a_volume_the_system_places():
    platform = DarwinPlatform()

    assert platform.mount_location_shape == "volume"
    assert platform.mount_location_choices() == []
    assert platform.suggest_mount_location() == ""
    assert platform.validate_mount_location(location="") is None


def test_preparing_an_empty_location_makes_no_directory(monkeypatch, tmp_path):
    made = []
    monkeypatch.setattr(DarwinPlatform, "make_directory", made.append)
    working = tmp_path / "working"
    working.mkdir()
    monkeypatch.chdir(working)

    assert DarwinPlatform().prepare_mount_location(location="") is None
    assert made == []
    assert list(working.iterdir()) == []


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


# --- the EasyTier daemon ---


def test_easytier_is_asked_of_the_daemons_socket_and_prompts_for_nothing():
    platform = DarwinPlatform()

    assert (
        platform.easytier_daemon_address() == "/var/run/neutrino/client/easytier.sock"
    )
    assert (
        platform.easytier_state_dir()
        == "/Library/Application Support/Neutrino/client/state/easytier"
    )
    assert platform.easytier_log_dir() == "/Library/Logs/Neutrino/client"
    assert not hasattr(darwin_module, "OSASCRIPT_TOOL")
    assert not hasattr(DarwinPlatform, "easytier_join")


# --- the clipboard ---


def test_the_clipboard_is_read_with_pbpaste(monkeypatch):
    recorder = CommandRecorder([completed(stdout="git status\n")])
    monkeypatch.setattr(darwin_module.subprocess, "run", recorder)

    assert DarwinPlatform().read_clipboard() == "git status\n"
    assert recorder.commands == [["pbpaste"]]


def test_a_pbpaste_that_fails_is_an_os_error(monkeypatch):
    recorder = CommandRecorder([completed(returncode=1, stderr="no pasteboard")])
    monkeypatch.setattr(darwin_module.subprocess, "run", recorder)

    with pytest.raises(OSError):
        DarwinPlatform().read_clipboard()


def test_a_pbpaste_that_hangs_is_an_os_error(monkeypatch):
    def hang(command, **kwargs):
        raise subprocess.TimeoutExpired(command, 5)

    monkeypatch.setattr(darwin_module.subprocess, "run", hang)

    with pytest.raises(OSError):
        DarwinPlatform().read_clipboard()


def test_the_clipboard_is_written_with_pbcopy(monkeypatch):
    recorder = CommandRecorder([completed()])
    monkeypatch.setattr(darwin_module.subprocess, "run", recorder)

    DarwinPlatform().write_clipboard("make test")

    assert recorder.commands == [["pbcopy"]]
    assert recorder.inputs == ["make test"]


def test_a_pbcopy_that_fails_is_an_os_error(monkeypatch):
    recorder = CommandRecorder([completed(returncode=1, stderr="no pasteboard")])
    monkeypatch.setattr(darwin_module.subprocess, "run", recorder)

    with pytest.raises(OSError):
        DarwinPlatform().write_clipboard("x")
