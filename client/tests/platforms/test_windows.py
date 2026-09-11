"""The Windows platform: pipe identity as the same account, net use here.

The pipe is the person's own, its peer must be the same account, and a
share is mapped in this very session with the login on standard input and
never on an argument vector. Every Win32 call rides the seam.
"""

import pytest

import neutrino_client.platforms.windows as windows_module
from neutrino_client.exceptions import PlatformUnsupportedError, ShareAttachError
from neutrino_client.platforms.windows import (
    WindowsPlatform,
)
from tests.conftest import completed


class FakeWin32:
    """The identity seam, scripted."""

    def __init__(self, *, account="Alice", language_id=0x0409):
        self.account = account
        self.language_id = language_id
        self.calls = []
        self.impersonate_error = None
        self.token_error = None
        self.connection_code = 0
        self.cancel_code = 0
        self.language_error = None

    def user_ui_language_id(self):
        self.calls.append(("user_ui_language_id",))
        if self.language_error is not None:
            raise self.language_error
        return self.language_id

    def notify_drive(self, path, event):
        self.calls.append(("notify_drive", path, event))

    def run_on_console(self, argv, *, prompt, answer, timeout_s):
        self.calls.append(("run_on_console", list(argv), prompt, answer))
        return 0, "Deleted"

    def add_connection(self, *, local, remote, username, password):
        self.calls.append(("add_connection", local, remote, username, password))
        return self.connection_code

    def cancel_connection(self, local):
        self.calls.append(("cancel_connection", local))
        return self.cancel_code

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
        return completed(command)


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


def test_the_windows_ui_language_is_what_the_first_start_takes():
    """0x0804 is Chinese (Simplified); 0x0409 is English (United States)."""
    chinese = WindowsPlatform(win32=FakeWin32(language_id=0x0804))
    english = WindowsPlatform(win32=FakeWin32(language_id=0x0409))

    assert chinese.system_language() == "zh-CN"
    assert english.system_language() == "en"


def test_every_chinese_region_reads_as_the_one_chinese_the_client_offers():
    """0x0404 is Taiwan, 0x0C04 Hong Kong; the client offers one Chinese."""
    for language_id in (0x0404, 0x0C04, 0x1004):
        assert (
            WindowsPlatform(win32=FakeWin32(language_id=language_id)).system_language()
            == "zh-CN"
        )


def test_a_windows_that_cannot_be_asked_leaves_the_language_english():
    win32 = FakeWin32()
    win32.language_error = OSError("no kernel32 here")

    assert WindowsPlatform(win32=win32).system_language() == "en"


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


def test_attach_maps_in_this_process_with_the_login_off_every_argv(
    platform, monkeypatch, tmp_path
):
    """A mapping made anywhere else is drawn as disconnected here."""
    credentials = tmp_path / "r1.credentials"
    credentials.write_text("username=media\npassword=s3cret\n")  # scan: allow
    recorder = CommandRecorder()
    monkeypatch.setattr(windows_module.subprocess, "run", recorder)

    platform.attach_share(
        share_url="//hub/media", location="Z:", credentials_path=str(credentials)
    )

    win32 = platform._win32()
    assert (
        "add_connection",
        "Z:",
        "\\\\hub\\media",
        "media",
        "s3cret",  # scan: allow
    ) in win32.calls
    assert recorder.commands == []
    assert ("notify_drive", "Z:\\", windows_module.SHCNE_DRIVEADD) in win32.calls


def test_a_refused_connection_is_a_typed_mount_failure(platform, monkeypatch, tmp_path):
    credentials = tmp_path / "r1.credentials"
    credentials.write_text("username=u\npassword=p\n")
    platform._win32().connection_code = 67

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


def test_detach_takes_the_mapping_down_in_this_session(platform):
    win32 = platform._win32()

    platform.detach_share(location="Z:")

    assert ("cancel_connection", "Z:") in win32.calls


def test_detaching_a_letter_that_is_only_remembered_counts_as_done(platform):
    platform._win32().cancel_code = 2250

    platform.detach_share(location="W:")

    assert ("cancel_connection", "W:") in platform._win32().calls


def test_a_failed_cancel_carries_the_win32_error(platform):
    platform._win32().cancel_code = 85

    with pytest.raises(ShareAttachError) as caught:
        platform.detach_share(location="Z:")
    assert caught.value.code == "unmount_failed"


def test_the_mapping_is_not_persisted_to_the_profile():
    """A persisted mapping is what Explorer keeps drawing after it is gone."""
    import inspect

    from neutrino_client.platforms.windows import _WindowsApi

    source = inspect.getsource(_WindowsApi.add_connection)
    # The last argument of WNetAddConnection2W is the flags; zero, not
    # CONNECT_UPDATE_PROFILE.
    assert "username, 0" in source
    assert "CONNECT_UPDATE_PROFILE" not in source


def test_detaching_forgets_a_mapping_the_profile_remembered():
    """A letter an earlier build persisted must not stay as a red cross."""
    import inspect

    from neutrino_client.platforms.windows import _WindowsApi

    source = inspect.getsource(_WindowsApi.cancel_connection)
    assert "win32.CONNECT_UPDATE_PROFILE" in source


def test_attachment_is_read_from_net_use(platform, monkeypatch):
    recorder = CommandRecorder([completed(stdout="Remote name \\\\hub\\media")])
    monkeypatch.setattr(windows_module, "run_quietly", recorder)
    assert platform.is_share_attached(location="Z:") is True
    assert recorder.commands == [["net", "use", "Z:"]]

    recorder = CommandRecorder([completed(returncode=2)])
    monkeypatch.setattr(windows_module, "run_quietly", recorder)
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


def test_a_mapped_drive_is_announced_to_the_shell(platform, monkeypatch):
    """Explorer draws a mapping it was never told about as disconnected."""
    win32 = platform._win32()
    monkeypatch.setattr(windows_module.os.path, "isfile", lambda path: True)
    monkeypatch.setattr(
        windows_module, "read_share_credentials", lambda path: ("bob", "pw")
    )

    platform.attach_share(
        share_url="//hub/media", location="Z:", credentials_path="/tmp/creds"
    )

    assert ("notify_drive", "Z:\\", windows_module.SHCNE_DRIVEADD) in win32.calls


def test_an_unmapped_drive_is_announced_to_the_shell(platform):
    win32 = platform._win32()

    platform.detach_share(location="Z:")

    assert ("notify_drive", "Z:\\", windows_module.SHCNE_DRIVEREMOVED) in win32.calls


def test_a_shell_that_refuses_the_notice_leaves_the_mapping_alone(
    platform, monkeypatch
):
    """Only the icon is at stake, never the mount."""

    def refuse(path, event):
        raise OSError("no shell here")

    monkeypatch.setattr(platform._win32(), "notify_drive", refuse)

    platform.detach_share(location="Z:")


def test_the_letters_offered_are_the_free_ones_top_down(platform, monkeypatch):
    """The window picks from these, so a taken letter is never on the list."""
    taken = {"C:\\", "D:\\", "Z:\\", "Y:\\"}
    monkeypatch.setattr(windows_module.os.path, "exists", lambda path: path in taken)

    choices = platform.mount_location_choices()

    assert choices[:3] == ["X:", "W:", "V:"]
    assert "Z:" not in choices and "C:" not in choices
    assert platform.suggest_mount_location() == "X:"


def test_every_letter_taken_offers_nothing(platform, monkeypatch):
    monkeypatch.setattr(windows_module.os.path, "exists", lambda path: True)

    assert platform.mount_location_choices() == []
    assert platform.suggest_mount_location() == ""


def test_a_question_is_answered_on_a_pseudo_console(platform):
    code, output = platform.run_answering(
        ["cc-switch.exe", "provider", "delete", "x"],
        prompt="(y/N)",
        answer="y\n",
        timeout_s=5,
    )

    assert (code, output) == (0, "Deleted")
    assert (
        "run_on_console",
        ["cc-switch.exe", "provider", "delete", "x"],
        "(y/N)",
        "y\n",
    ) in platform._win32().calls
