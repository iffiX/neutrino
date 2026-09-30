"""The Linux platform: peercred identity, the pkexec helper, /proc/mounts.

A mount is the one privileged step and rides the root helper under
``pkexec`` with the credentials file on its argument vector and the
password nowhere; a declined authorization is typed; attachment is read
from the kernel's mount table. The clipboard is read with the session's
own tool, else through GTK.
"""

import collections
import os
import struct
import subprocess

import pytest

import neutrino_client.platforms.linux as linux_module
from neutrino_client.constants import (
    CLIENT_CLIPBOARD_TIMEOUT_S,
    CLIENT_MOUNT_HELPER_PATH,
)
from neutrino_client.exceptions import (
    ControlSocketUnavailableError,
    ShareAttachError,
)
from neutrino_client.platforms.linux import LinuxPlatform
from tests.conftest import completed

PwdEntry = collections.namedtuple("PwdEntry", "pw_name pw_uid pw_shell pw_dir")


class FakePeerConnection:
    def __init__(self, credential: bytes):
        self._credential = credential

    def getsockopt(self, level, option, length):
        return self._credential[:length]


class CommandRecorder:
    """Stands in for ``subprocess.run``, remembering every call."""

    def __init__(self, results=None):
        self.commands = []
        self.results = list(results or [])

    def __call__(self, command, **kwargs):
        self.commands.append(list(command))
        if self.results:
            return self.results.pop(0)
        return completed(command)


def test_the_config_dir_is_under_xdg_config_home(monkeypatch, tmp_path):
    monkeypatch.undo()
    monkeypatch.setenv("HOME", "/home/alice")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    assert LinuxPlatform().config_dir() == "/home/alice/.config/neutrino_client"

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert LinuxPlatform().config_dir() == str(tmp_path / "neutrino_client")


def test_the_socket_lives_in_the_runtime_dir_or_nowhere(monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    assert (
        LinuxPlatform().control_socket_path() == "/run/user/1000/neutrino_client.sock"
    )

    monkeypatch.delenv("XDG_RUNTIME_DIR")
    with pytest.raises(ControlSocketUnavailableError) as caught:
        LinuxPlatform().control_socket_path()
    assert caught.value.code == "control_socket_unavailable"


def test_the_same_uid_is_the_same_user(monkeypatch):
    entry = PwdEntry("alice", os.getuid(), "/bin/bash", "/home/alice")
    monkeypatch.setattr(linux_module.pwd, "getpwuid", lambda uid: entry)
    connection = FakePeerConnection(struct.pack("3i", 42, os.getuid(), 1000))

    identity = LinuxPlatform().read_peer_identity(connection)

    assert identity == {"account": "alice", "uid": os.getuid(), "is_same_user": True}


def test_another_uid_is_not_the_same_user(monkeypatch):
    entry = PwdEntry("bob", 4242, "/bin/bash", "/home/bob")
    monkeypatch.setattr(linux_module.pwd, "getpwuid", lambda uid: entry)
    connection = FakePeerConnection(struct.pack("3i", 42, 4242, 4242))

    identity = LinuxPlatform().read_peer_identity(connection)

    assert identity["is_same_user"] is False
    assert identity["account"] == "bob"


def test_a_uid_that_names_no_account_still_answers(monkeypatch):
    def unknown(uid):
        raise KeyError(uid)

    monkeypatch.setattr(linux_module.pwd, "getpwuid", unknown)
    connection = FakePeerConnection(struct.pack("3i", 42, 4242, 4242))

    identity = LinuxPlatform().read_peer_identity(connection)

    assert identity == {"account": "4242", "uid": 4242, "is_same_user": False}


def test_attach_rides_pkexec_and_the_helper_with_the_credentials_file(
    monkeypatch, tmp_path
):
    credentials = tmp_path / "r1.credentials"
    credentials.write_text("username=media\npassword=s3cret\n")  # scan: allow
    recorder = CommandRecorder()
    monkeypatch.setattr(linux_module.subprocess, "run", recorder)

    LinuxPlatform().attach_share(
        share_url="//hub/media",
        location="/home/alice/nas/media",
        credentials_path=str(credentials),
    )

    assert recorder.commands == [
        [
            "pkexec",
            CLIENT_MOUNT_HELPER_PATH,
            "mount",
            "--share",
            "//hub/media",
            "--location",
            "/home/alice/nas/media",
            "--credentials",
            str(credentials),
        ]
    ]
    assert "s3cret" not in " ".join(recorder.commands[0])  # scan: allow


def test_detach_rides_pkexec_and_the_helper(monkeypatch):
    recorder = CommandRecorder()
    monkeypatch.setattr(linux_module.subprocess, "run", recorder)

    LinuxPlatform().detach_share(location="/home/alice/nas/media")

    assert recorder.commands == [
        [
            "pkexec",
            CLIENT_MOUNT_HELPER_PATH,
            "unmount",
            "--location",
            "/home/alice/nas/media",
        ]
    ]


@pytest.mark.parametrize("exit_code", [126, 127])
def test_a_declined_authorization_is_typed(monkeypatch, tmp_path, exit_code):
    credentials = tmp_path / "r1.credentials"
    credentials.write_text("")
    recorder = CommandRecorder([completed(returncode=exit_code)])
    monkeypatch.setattr(linux_module.subprocess, "run", recorder)

    with pytest.raises(ShareAttachError) as caught:
        LinuxPlatform().attach_share(
            share_url="//hub/media", location="/mnt", credentials_path=str(credentials)
        )
    assert caught.value.code == "mount_not_authorized"


@pytest.mark.parametrize(
    "exit_code, code",
    [
        (3, "mountpoint_invalid"),
        (4, "mountpoint_not_empty"),
        (5, "credentials_missing"),
        (6, "mount_failed"),
        (8, "share_login_rejected"),
        (9, "share_access_denied"),
        (10, "share_not_found"),
        (11, "share_unreachable"),
        (99, "mount_failed"),
    ],
)
def test_the_helpers_exit_status_is_typed(monkeypatch, tmp_path, exit_code, code):
    credentials = tmp_path / "r1.credentials"
    credentials.write_text("")
    recorder = CommandRecorder(
        [completed(returncode=exit_code, stderr="the tool's words")]
    )
    monkeypatch.setattr(linux_module.subprocess, "run", recorder)

    with pytest.raises(ShareAttachError) as caught:
        LinuxPlatform().attach_share(
            share_url="//hub/media", location="/mnt", credentials_path=str(credentials)
        )
    assert caught.value.code == code
    assert caught.value.detail == "the tool's words"


def test_a_gone_credentials_file_is_refused_before_pkexec(monkeypatch, tmp_path):
    recorder = CommandRecorder()
    monkeypatch.setattr(linux_module.subprocess, "run", recorder)

    with pytest.raises(ShareAttachError) as caught:
        LinuxPlatform().attach_share(
            share_url="//hub/media",
            location="/mnt",
            credentials_path=str(tmp_path / "gone"),
        )
    assert caught.value.code == "credentials_missing"
    assert recorder.commands == []


def test_a_failed_unmount_carries_the_tools_words(monkeypatch):
    recorder = CommandRecorder([completed(returncode=7, stderr="target is busy")])
    monkeypatch.setattr(linux_module.subprocess, "run", recorder)

    with pytest.raises(ShareAttachError) as caught:
        LinuxPlatform().detach_share(location="/mnt")
    assert caught.value.code == "unmount_failed"
    assert caught.value.detail == "target is busy"


def test_the_tooling_is_the_helper_and_mount_cifs(monkeypatch, tmp_path):
    helper = tmp_path / "mount_helper"
    monkeypatch.setattr(linux_module, "CLIENT_MOUNT_HELPER_PATH", str(helper))
    monkeypatch.setattr(
        linux_module.shutil, "which", lambda name, path=None: "/sbin/mount.cifs"
    )
    assert LinuxPlatform().has_mount_tooling() is False

    helper.write_text("")
    assert LinuxPlatform().has_mount_tooling() is True

    monkeypatch.setattr(linux_module.shutil, "which", lambda name, path=None: None)
    assert LinuxPlatform().has_mount_tooling() is False


def test_mount_cifs_is_looked_for_where_debian_puts_it(monkeypatch, tmp_path):
    """/usr/sbin is not on a person's PATH on Debian, and cifs-utils installs
    there; the helper that runs it as root finds it either way."""
    helper = tmp_path / "mount_helper"
    helper.write_text("")
    monkeypatch.setattr(linux_module, "CLIENT_MOUNT_HELPER_PATH", str(helper))
    asked = []

    def which(name, path=None):
        asked.append(path)
        return "/usr/sbin/mount.cifs"

    monkeypatch.setattr(linux_module.shutil, "which", which)

    assert LinuxPlatform().has_mount_tooling() is True
    assert "/usr/sbin" in asked[0].split(":")


def test_attachment_is_read_from_proc_mounts_with_escapes(monkeypatch, tmp_path):
    table = tmp_path / "mounts"
    table.write_text(
        "//hub/media /home/alice/my\\040nas cifs rw 0 0\n" "tmpfs /tmp tmpfs rw 0 0\n"
    )
    monkeypatch.setattr(linux_module, "PROC_MOUNTS_PATH", str(table))
    platform = LinuxPlatform()

    assert platform.is_share_attached(location="/home/alice/my nas")
    assert not platform.is_share_attached(location="/home/alice/other")


def test_a_program_that_asks_gets_its_answer_on_a_terminal_of_its_own():
    import sys

    platform = LinuxPlatform()
    code, output = platform.run_answering(
        [sys.executable, "-c", "print('ok' if input('go? (y/N) ') == 'y' else 'no')"],
        prompt="(y/N)",
        answer="y\n",
        timeout_s=20,
    )

    assert code == 0
    assert "ok" in output


def test_a_program_that_cannot_start_answers_127():
    platform = LinuxPlatform()
    code, _ = platform.run_answering(
        ["/nonexistent/program"], prompt="?", answer="y\n", timeout_s=5
    )
    assert code == 127


def test_without_a_pty_module_the_terminal_is_a_typed_refusal(monkeypatch):
    import neutrino_client.platforms.base as base_module
    from neutrino_client.exceptions import PlatformUnsupportedError

    monkeypatch.setattr(base_module, "pty", None)

    with pytest.raises(PlatformUnsupportedError):
        LinuxPlatform().run_answering(["x"], prompt="?", answer="y", timeout_s=1)


# --- the EasyTier daemon ---


def test_easytier_is_asked_of_the_daemons_socket_and_kept_in_root_state():
    platform = LinuxPlatform()

    assert platform.easytier_daemon_address() == "/run/neutrino_client_easytier.sock"
    assert platform.easytier_state_dir() == "/etc/neutrino_client/easytier"


def test_the_daemons_state_directory_is_its_owners_alone(tmp_path):
    state = tmp_path / "easytier"
    state.mkdir(mode=0o755)

    LinuxPlatform().secure_easytier_state_dir(str(state))

    assert os.stat(state).st_mode & 0o777 == 0o700


def test_linux_has_no_overlay_helper_left():
    assert not hasattr(LinuxPlatform, "easytier_join")
    assert not hasattr(LinuxPlatform, "easytier_leave")


# --- the clipboard ---


class ClipboardTools:
    """``shutil.which`` and ``subprocess.run`` for the clipboard tools.

    Attributes:
        installed: The tools found on PATH.
        commands: Every command run, in order.
        result: What every run answers.
    """

    def __init__(self, installed, result=None):
        self.installed = set(installed)
        self.commands = []
        self.result = result if result is not None else completed(stdout="ls -la\n")

    def which(self, name):
        return f"/usr/bin/{name}" if name in self.installed else None

    def run(self, command, **kwargs):
        self.commands.append(list(command))
        return self.result


def clipboard_session(monkeypatch, tools, *, wayland="", display=""):
    for name, value in (("WAYLAND_DISPLAY", wayland), ("DISPLAY", display)):
        if value:
            monkeypatch.setenv(name, value)
        else:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(linux_module.shutil, "which", tools.which)
    monkeypatch.setattr(linux_module.subprocess, "run", tools.run)


def refuse_gtk(timeout_s):
    raise AssertionError("GTK is asked only when no tool serves the session")


def test_a_wayland_session_is_read_with_wl_paste(monkeypatch):
    tools = ClipboardTools({"wl-paste", "xclip"})
    clipboard_session(monkeypatch, tools, wayland="wayland-0", display=":0")
    monkeypatch.setattr(linux_module, "gtk_clipboard_text", refuse_gtk)

    assert LinuxPlatform().read_clipboard() == "ls -la\n"
    assert tools.commands == [["wl-paste", "--no-newline", "--type", "text"]]


def test_an_x_session_is_read_with_xclip(monkeypatch):
    tools = ClipboardTools({"xclip"})
    clipboard_session(monkeypatch, tools, wayland="wayland-0", display=":0")
    monkeypatch.setattr(linux_module, "gtk_clipboard_text", refuse_gtk)

    assert LinuxPlatform().read_clipboard() == "ls -la\n"
    assert tools.commands == [["xclip", "-selection", "clipboard", "-o"]]


def test_a_clipboard_the_tool_finds_no_text_on_reads_empty(monkeypatch):
    tools = ClipboardTools({"xclip"}, completed(returncode=1, stderr="no STRING"))
    clipboard_session(monkeypatch, tools, display=":0")

    assert LinuxPlatform().read_clipboard() == ""


def test_without_a_tool_the_clipboard_is_read_through_gtk(monkeypatch):
    tools = ClipboardTools(set())
    clipboard_session(monkeypatch, tools, display=":0")
    asked = []

    def gtk_text(timeout_s):
        asked.append(timeout_s)
        return "from gtk"

    monkeypatch.setattr(linux_module, "gtk_clipboard_text", gtk_text)

    assert LinuxPlatform().read_clipboard() == "from gtk"
    assert tools.commands == []
    assert asked == [CLIENT_CLIPBOARD_TIMEOUT_S]


def test_a_tool_that_hangs_is_an_os_error(monkeypatch):
    tools = ClipboardTools({"xclip"})

    def hang(command, **kwargs):
        raise subprocess.TimeoutExpired(command, 5)

    tools.run = hang
    clipboard_session(monkeypatch, tools, display=":0")

    with pytest.raises(OSError):
        LinuxPlatform().read_clipboard()
