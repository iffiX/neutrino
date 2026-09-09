"""The Windows platform: pipe identity as the same account, net use here.

The pipe is the person's own, its peer must be the same account, and a
share is mapped in this very session with the login on standard input and
never on an argument vector. Every Win32 call rides the seam.
"""

import pytest

import neutrino_client.platforms.windows as windows_module
from neutrino_client.platforms.base import PlatformUnsupportedError, ShareAttachError
from neutrino_client.platforms.windows import (
    WINDOWS_MOUNT_SUCCESS_MARKER,
    WindowsPlatform,
    _mapping_script,
)
from tests.conftest import completed


class FakeWin32:
    """The identity seam, scripted."""

    def __init__(self, *, account="Alice"):
        self.account = account
        self.calls = []
        self.impersonate_error = None
        self.token_error = None

    def impersonate_named_pipe_client(self, handle):
        self.calls.append(("impersonate", handle))
        if self.impersonate_error is not None:
            raise self.impersonate_error

    def revert_to_self(self):
        self.calls.append(("revert",))

    def open_thread_token(self):
        self.calls.append(("open_token",))
        if self.token_error is not None:
            raise self.token_error
        return 42

    def token_account(self, token):
        return self.account

    def close_handle(self, handle):
        self.calls.append(("close", handle))


class FakePipeConnection:
    pipe_handle = 7


class CommandRecorder:
    def __init__(self, results=None):
        self.commands = []
        self.inputs = []
        self.results = list(results or [])

    def __call__(self, command, **kwargs):
        self.commands.append(list(command))
        self.inputs.append(kwargs.get("input"))
        if self.results:
            return self.results.pop(0)
        return completed(command, stdout=WINDOWS_MOUNT_SUCCESS_MARKER + "\n")


@pytest.fixture
def platform(monkeypatch):
    monkeypatch.setattr(WindowsPlatform, "current_account", lambda self: "alice")
    return WindowsPlatform(win32=FakeWin32())


def test_the_pipe_is_named_per_person(platform):
    assert platform.control_socket_path() == "\\\\.\\pipe\\neutrino_client_alice"


def test_a_pipe_name_carries_no_character_a_pipe_refuses(monkeypatch):
    monkeypatch.setattr(WindowsPlatform, "current_account", lambda self: "a b\\c")

    assert (
        WindowsPlatform().control_socket_path() == "\\\\.\\pipe\\neutrino_client_a_b_c"
    )


def test_the_config_dir_is_under_appdata(monkeypatch):
    monkeypatch.undo()
    monkeypatch.setenv("APPDATA", "C:\\Users\\alice\\AppData\\Roaming")

    assert WindowsPlatform().config_dir().endswith("Neutrino Client")
    assert WindowsPlatform().config_dir().startswith("C:\\Users\\alice")


@pytest.mark.parametrize(
    ("account", "is_same_user"), [("alice", True), ("ALICE", True), ("Bob", False)]
)
def test_the_peer_must_be_the_same_account(monkeypatch, account, is_same_user):
    monkeypatch.setattr(WindowsPlatform, "current_account", lambda self: "alice")
    platform = WindowsPlatform(win32=FakeWin32(account=account))

    identity = platform.read_peer_identity(FakePipeConnection())

    assert identity == {"account": account, "uid": -1, "is_same_user": is_same_user}


def test_identity_reverts_and_closes_after_reading(platform):
    win32 = platform._win32()

    platform.read_peer_identity(FakePipeConnection())

    assert ("impersonate", 7) in win32.calls
    assert win32.calls[-1] == ("revert",)
    assert ("close", 42) in win32.calls


def test_identity_needs_a_pipe_peer(platform):
    with pytest.raises(PlatformUnsupportedError):
        platform.read_peer_identity(object())


def test_a_failed_token_read_still_reverts(platform):
    win32 = platform._win32()
    win32.token_error = OSError("no token")

    with pytest.raises(PlatformUnsupportedError):
        platform.read_peer_identity(FakePipeConnection())

    assert ("revert",) in win32.calls


def test_attach_maps_in_this_session_with_the_login_on_stdin(
    platform, monkeypatch, tmp_path
):
    credentials = tmp_path / "r1.credentials"
    credentials.write_text("username=media\npassword=s3cret\n")  # scan: allow
    recorder = CommandRecorder()
    monkeypatch.setattr(windows_module.subprocess, "run", recorder)

    platform.attach_share(
        share_url="//hub/media", location="Z:", credentials_path=str(credentials)
    )

    assert recorder.commands == [
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", "-"]
    ]
    script = recorder.inputs[0]
    assert "New-SmbMapping -LocalPath $local -RemotePath $remote" in script
    assert "$p = 's3cret'" in script  # scan: allow
    assert "s3cret" not in " ".join(recorder.commands[0])  # scan: allow
    assert script.endswith("\n\n")
    assert "run_in_session" not in dir(windows_module)


def test_the_mapping_script_closes_itself_and_names_success():
    script = _mapping_script(
        host="hub", share="media", location="Z:", username="u", password="it's"
    )

    assert script.endswith("}\n\n")
    assert f"Write-Output '{WINDOWS_MOUNT_SUCCESS_MARKER}'" in script
    assert "$p = 'it''s'" in script


def test_a_silent_zero_exit_is_a_mount_failure(platform, monkeypatch, tmp_path):
    credentials = tmp_path / "r1.credentials"
    credentials.write_text("username=u\npassword=p\n")
    recorder = CommandRecorder([completed(stdout="")])
    monkeypatch.setattr(windows_module.subprocess, "run", recorder)

    with pytest.raises(ShareAttachError) as caught:
        platform.attach_share(
            share_url="//hub/media", location="Z:", credentials_path=str(credentials)
        )
    assert caught.value.code == "mount_failed"


def test_attach_refusals_are_typed(platform, monkeypatch, tmp_path):
    recorder = CommandRecorder()
    monkeypatch.setattr(windows_module.subprocess, "run", recorder)

    with pytest.raises(ShareAttachError) as caught:
        platform.attach_share(
            share_url="//hub/media",
            location="Z:",
            credentials_path=str(tmp_path / "gone"),
        )
    assert caught.value.code == "credentials_missing"

    with pytest.raises(ShareAttachError) as caught:
        platform.attach_share(
            share_url="nonsense", location="Z:", credentials_path=str(tmp_path / "gone")
        )
    assert caught.value.code == "mount_failed"
    assert recorder.commands == []


def test_detach_deletes_the_mapping_here(platform, monkeypatch):
    recorder = CommandRecorder()
    monkeypatch.setattr(windows_module.subprocess, "run", recorder)

    platform.detach_share(location="Z:")

    assert recorder.commands == [["net", "use", "Z:", "/delete", "/y"]]


def test_a_failed_delete_carries_the_tools_words(platform, monkeypatch):
    recorder = CommandRecorder([completed(returncode=2, stderr="in use")])
    monkeypatch.setattr(windows_module.subprocess, "run", recorder)

    with pytest.raises(ShareAttachError) as caught:
        platform.detach_share(location="Z:")
    assert caught.value.code == "unmount_failed"
    assert caught.value.detail == "in use"


def test_attachment_is_read_from_net_use(platform, monkeypatch):
    recorder = CommandRecorder([completed(stdout="Remote name \\\\hub\\media")])
    monkeypatch.setattr(windows_module.subprocess, "run", recorder)
    assert platform.is_share_attached(location="Z:") is True
    assert recorder.commands == [["net", "use", "Z:"]]

    recorder = CommandRecorder([completed(returncode=2)])
    monkeypatch.setattr(windows_module.subprocess, "run", recorder)
    assert platform.is_share_attached(location="Z:") is False


def test_mount_locations_are_unused_drive_letters(platform, monkeypatch):
    monkeypatch.setattr(windows_module.os.path, "exists", lambda path: path == "C:\\")

    assert platform.validate_mount_location(location="Z:") is None
    assert platform.validate_mount_location(location="C:") == {
        "code": "mountpoint_not_empty",
        "params": {},
    }
    for bad in ("", "Z", "Z:\\", "/mnt/media"):
        assert platform.validate_mount_location(location=bad) == {
            "code": "mountpoint_not_drive_letter",
            "params": {},
        }
    assert platform.suggest_mount_location() == "Z:"
    assert platform.prepare_mount_location(location="Z:") is None
