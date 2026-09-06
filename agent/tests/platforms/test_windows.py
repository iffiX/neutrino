"""The Windows platform: pipe identity, profiles, cmdkey and ``net use``.

Privileged is an elevated Administrators token, so an unelevated admin
shell is ordinary; people are local profiles; a share is a stored
credential plus a session mapping whose password rides standard input; the
SSH server is a capability whose install is allowed minutes. Every Win32
call rides the seam, so nothing here touches a real Windows API.
"""

import json
import subprocess

import pytest

import neutrino_agent.platforms.windows as windows_module
from neutrino_agent.constants import AGENT_CONTROL_PIPE_NAME
from neutrino_agent.core.metrics import HostMetrics
from neutrino_agent.modules import installers
from neutrino_agent.platforms.base import PlatformUnsupportedError, ShareAttachError
from neutrino_agent.platforms.windows import (
    WindowsPlatform,
    _human_profiles,
    _windows_metrics,
)


class FakeWin32:
    """The identity and step-down seam, scripted."""

    def __init__(
        self,
        *,
        account="Alice",
        is_elevated=False,
        is_admin=False,
        console="",
    ):
        self.account = account
        self.is_elevated = is_elevated
        self.is_admin = is_admin
        self.console = console
        self.calls = []
        self.impersonate_error = None
        self.token_error = None
        self.run_result = subprocess.CompletedProcess(["x"], 0, stdout="ran", stderr="")

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

    def is_token_elevated(self, token):
        return self.is_elevated

    def is_token_admin_member(self, token):
        return self.is_admin

    def close_handle(self, handle):
        self.calls.append(("close", handle))

    def console_account(self):
        return self.console

    def run_as_console_user(self, argv, *, stdin, timeout_s):
        self.calls.append(("run", tuple(argv), stdin, timeout_s))
        return self.run_result


class FakePipeConnection:
    pipe_handle = 7


class CommandRecorder:
    """Stands in for ``subprocess.run``, remembering every call."""

    def __init__(self, results=None):
        self.commands = []
        self.inputs = []
        self.kwargs = []
        self.results = list(results or [])

    def __call__(self, command, **kwargs):
        self.commands.append(list(command))
        self.inputs.append(kwargs.get("input"))
        self.kwargs.append(kwargs)
        if self.results:
            return self.results.pop(0)
        return subprocess.CompletedProcess(list(command), 0, stdout="", stderr="")


def completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


# --- identity and the control channel ---


def test_windows_control_channel_is_the_named_pipe():
    assert WindowsPlatform().control_socket_path() == AGENT_CONTROL_PIPE_NAME


@pytest.mark.parametrize(
    ("is_elevated", "is_admin", "is_privileged"),
    [
        (True, True, True),
        (False, True, False),
        (True, False, False),
        (False, False, False),
    ],
)
def test_windows_privilege_is_an_elevated_administrators_token(
    is_elevated, is_admin, is_privileged
):
    win32 = FakeWin32(account="Alice", is_elevated=is_elevated, is_admin=is_admin)
    platform = WindowsPlatform(win32=win32)

    identity = platform.read_peer_identity(FakePipeConnection())

    assert identity == {
        "account": "Alice",
        "uid": -1,
        "is_privileged": is_privileged,
    }


def test_windows_identity_reverts_and_closes_after_reading():
    win32 = FakeWin32(is_elevated=True, is_admin=True)
    WindowsPlatform(win32=win32).read_peer_identity(FakePipeConnection())

    assert ("impersonate", 7) in win32.calls
    assert win32.calls[-1] == ("revert",)
    assert ("close", 42) in win32.calls


def test_windows_identity_needs_a_pipe_peer():
    with pytest.raises(PlatformUnsupportedError) as caught:
        WindowsPlatform(win32=FakeWin32()).read_peer_identity(object())
    assert caught.value.code == "unsupported_platform"


def test_windows_a_failed_token_read_still_reverts():
    win32 = FakeWin32()
    win32.token_error = OSError("no token")

    with pytest.raises(PlatformUnsupportedError):
        WindowsPlatform(win32=win32).read_peer_identity(FakePipeConnection())

    assert ("revert",) in win32.calls


def test_windows_a_refused_impersonation_is_typed():
    win32 = FakeWin32()
    win32.impersonate_error = OSError("refused")

    with pytest.raises(PlatformUnsupportedError) as caught:
        WindowsPlatform(win32=win32).read_peer_identity(FakePipeConnection())
    assert caught.value.code == "unsupported_platform"


# --- human accounts are local profiles ---


def test_windows_human_accounts_are_local_profiles(monkeypatch):
    listing = json.dumps(
        [
            {"SID": "S-1-5-21-1-2-3-1001", "LocalPath": "C:\\Users\\alice"},
            {"SID": "S-1-5-21-1-2-3-1002", "LocalPath": "C:/Users/bob"},
            {"SID": "S-1-5-21-1-2-3-500", "LocalPath": "C:\\Users\\Administrator"},
            {"SID": "S-1-5-21-1-2-3-501", "LocalPath": "C:\\Users\\Guest"},
            {"SID": "S-1-5-21-1-2-3-503", "LocalPath": "C:\\Users\\DefaultAccount"},
            {"SID": "S-1-5-21-1-2-3-504", "LocalPath": "C:\\Users\\WDAGUtility"},
            {"SID": "S-1-5-80-1-2-3", "LocalPath": "C:\\Users\\service_like"},
            {"SID": "S-1-5-21-1-2-3-1003", "LocalPath": ""},
        ]
    )
    recorder = CommandRecorder(results=[completed(stdout=listing)])
    monkeypatch.setattr(windows_module.subprocess, "run", recorder)

    accounts = WindowsPlatform().human_accounts()

    assert accounts == ["alice", "bob"]
    assert recorder.commands[0][0] == "powershell"
    assert "Win32_UserProfile" in recorder.commands[0][-1]
    assert "Special=FALSE" in recorder.commands[0][-1]


def test_windows_a_single_profile_arrives_as_one_object(monkeypatch):
    listing = json.dumps({"SID": "S-1-5-21-1-2-3-1001", "LocalPath": "C:\\Users\\mia"})
    recorder = CommandRecorder(results=[completed(stdout=listing)])
    monkeypatch.setattr(windows_module.subprocess, "run", recorder)

    assert WindowsPlatform().human_accounts() == ["mia"]


def test_windows_an_unreadable_profile_listing_reads_as_nobody(monkeypatch):
    recorder = CommandRecorder(results=[completed(returncode=1)])
    monkeypatch.setattr(windows_module.subprocess, "run", recorder)
    assert WindowsPlatform().human_accounts() == []

    assert _human_profiles("not json") == []
    assert _human_profiles("") == []


# --- shares: stored credential plus session mapping ---


def test_windows_attach_stores_the_credential_then_maps(monkeypatch, tmp_path):
    recorder = CommandRecorder()
    monkeypatch.setattr(windows_module.subprocess, "run", recorder)
    credentials_path = tmp_path / "mounts" / "r1.credentials"

    WindowsPlatform().attach_share(
        account="alice",
        share_url="//hub/media",
        username="media",
        password="s3cret",  # scan: allow
        location="Z:",
        credentials_path=str(credentials_path),
    )

    icacls, cmdkey, net_use = recorder.commands
    assert icacls[0] == "icacls" and "/inheritance:r" in icacls
    assert "*S-1-5-18:(OI)(CI)F" in icacls and "*S-1-5-32-544:(OI)(CI)F" in icacls
    assert cmdkey[:2] == ["powershell", "-NoProfile"] and cmdkey[-1] == "-"
    script = recorder.inputs[1]
    assert "cmdkey /add:$h /user:$u /pass:$p" in script
    assert "'hub'" in script and "'media'" in script and "'s3cret'" in script
    assert net_use == ["net", "use", "Z:", "\\\\hub\\media", "/persistent:yes"]
    assert credentials_path.read_text() == "username=media\npassword=s3cret\n"


def test_windows_the_password_is_on_no_argument_vector(monkeypatch, tmp_path):
    recorder = CommandRecorder()
    monkeypatch.setattr(windows_module.subprocess, "run", recorder)

    WindowsPlatform().attach_share(
        account="alice",
        share_url="//hub/media",
        username="media",
        password="it's secret",  # scan: allow
        location="Z:",
        credentials_path=str(tmp_path / "r1.credentials"),
    )

    for command in recorder.commands:
        assert all("secret" not in part for part in command)
    assert "'it''s secret'" in recorder.inputs[1]


def test_windows_reattach_uses_the_kept_credentials(monkeypatch, tmp_path):
    credentials_path = tmp_path / "r1.credentials"
    credentials_path.write_text("username=media\npassword=kept\n")
    recorder = CommandRecorder()
    monkeypatch.setattr(windows_module.subprocess, "run", recorder)

    WindowsPlatform().attach_share(
        account="alice",
        share_url="//hub/media",
        username="",
        password="",
        location="Z:",
        credentials_path=str(credentials_path),
    )

    assert [command[0] for command in recorder.commands] == ["powershell", "net"]
    assert "'kept'" in recorder.inputs[0]


def test_windows_attach_refusals_are_typed(monkeypatch, tmp_path):
    recorder = CommandRecorder()
    monkeypatch.setattr(windows_module.subprocess, "run", recorder)

    with pytest.raises(ShareAttachError) as caught:
        WindowsPlatform().attach_share(
            account="alice",
            share_url="//hub/media",
            username="media",
            password="",
            location="Z:",
            credentials_path=str(tmp_path / "gone.credentials"),
        )
    assert caught.value.code == "credentials_missing"

    with pytest.raises(ShareAttachError) as caught:
        WindowsPlatform().attach_share(
            account="alice",
            share_url="//only_a_host",
            username="media",
            password="",
            location="Z:",
            credentials_path=str(tmp_path / "gone.credentials"),
        )
    assert caught.value.code == "mount_failed"


def test_windows_mapping_failures_carry_the_tools_own_words(monkeypatch, tmp_path):
    credentials_path = tmp_path / "r1.credentials"
    credentials_path.write_text("username=media\npassword=kept\n")
    recorder = CommandRecorder(
        results=[
            completed(),
            completed(returncode=2, stderr="System error 86 has occurred."),
        ]
    )
    monkeypatch.setattr(windows_module.subprocess, "run", recorder)

    with pytest.raises(ShareAttachError) as caught:
        WindowsPlatform().attach_share(
            account="alice",
            share_url="//hub/media",
            username="",
            password="",
            location="Z:",
            credentials_path=str(credentials_path),
        )
    assert caught.value.code == "mount_failed"
    assert "System error 86" in caught.value.detail


def test_windows_detach_deletes_the_mapping(monkeypatch):
    recorder = CommandRecorder()
    monkeypatch.setattr(windows_module.subprocess, "run", recorder)

    WindowsPlatform().detach_share(location="Z:")

    assert recorder.commands == [["net", "use", "Z:", "/delete", "/y"]]

    recorder.results = [completed(returncode=2, stderr="not found")]
    with pytest.raises(ShareAttachError) as caught:
        WindowsPlatform().detach_share(location="Z:")
    assert caught.value.code == "unmount_failed"


def test_windows_attachment_is_read_from_net_use(monkeypatch):
    listing = (
        "New connections will be remembered.\n\n"
        "Status       Local     Remote                    Network\n"
        "---------------------------------------------------------\n"
        "OK           Z:        \\\\hub\\media            Microsoft Windows Network\n"
    )
    recorder = CommandRecorder(
        results=[completed(stdout=listing), completed(stdout=listing)]
    )
    monkeypatch.setattr(windows_module.subprocess, "run", recorder)
    platform = WindowsPlatform()

    assert platform.is_share_attached(location="z:") is True
    assert platform.is_share_attached(location="Y:") is False

    recorder.results = [completed(returncode=1)]
    assert platform.is_share_attached(location="Z:") is False


def test_windows_mounting_is_native():
    assert WindowsPlatform().has_mount_tooling() is True


def test_windows_mount_locations_are_unused_drive_letters(monkeypatch):
    platform = WindowsPlatform()

    for bad in ("", "Z", "Z:\\media", "/mnt/media", "ZZ:"):
        assert platform.validate_mount_location(location=bad) == {
            "code": "mountpoint_invalid",
            "params": {},
        }

    monkeypatch.setattr(windows_module.os.path, "exists", lambda path: False)
    assert platform.validate_mount_location(location="Z:") is None
    assert platform.validate_mount_location(location="z:") is None

    monkeypatch.setattr(windows_module.os.path, "exists", lambda path: True)
    assert platform.validate_mount_location(location="Z:") == {
        "code": "mountpoint_not_empty",
        "params": {},
    }


def test_windows_a_drive_letter_needs_no_preparation():
    assert (
        WindowsPlatform().prepare_mount_location(account="Alice", location="Z:") is None
    )


# --- the SSH server is a capability, allowed minutes ---


def test_windows_openssh_install_adds_the_capability_and_starts_sshd(monkeypatch):
    recorded = {}

    def record(command, *, timeout_s=0):
        recorded["command"] = list(command)
        recorded["timeout_s"] = timeout_s
        return ""

    monkeypatch.setattr(windows_module.installers, "run_checked", record)

    WindowsPlatform().install_openssh({"capability": "OpenSSH.Server~~~~9.9"})

    script = recorded["command"][-1]
    assert "Add-WindowsCapability -Online -Name OpenSSH.Server~~~~9.9" in script
    assert "Start-Service sshd" in script
    assert script.index("Add-WindowsCapability") < script.index("Start-Service")
    # Add-WindowsCapability pulls from Windows Update and takes minutes.
    assert recorded["timeout_s"] == installers.INSTALL_TIMEOUT_S
    assert recorded["timeout_s"] >= 240


def test_windows_openssh_uninstall_stops_then_removes_the_capability(monkeypatch):
    recorded = {}

    def record(command, *, timeout_s=0):
        recorded["command"] = list(command)
        recorded["timeout_s"] = timeout_s
        return ""

    monkeypatch.setattr(windows_module.installers, "run_checked", record)

    WindowsPlatform().uninstall_openssh({"capability": "OpenSSH.Server~~~~9.9"})

    script = recorded["command"][-1]
    assert "Stop-Service sshd" in script
    assert "Remove-WindowsCapability -Online -Name OpenSSH.Server~~~~9.9" in script
    assert script.index("Stop-Service") < script.index("Remove-WindowsCapability")
    assert recorded["timeout_s"] >= 240


def test_windows_openssh_status_reads_the_service(monkeypatch):
    recorder = CommandRecorder(results=[completed(stdout="Running\n")])
    monkeypatch.setattr(windows_module.subprocess, "run", recorder)
    assert WindowsPlatform().read_openssh_status({}) is True

    recorder.results = [completed(stdout="Stopped\n")]
    assert WindowsPlatform().read_openssh_status({}) is False


# --- the msi kind for handed bytes ---


def test_windows_msi_bytes_install_silently(monkeypatch):
    recorded = {}

    def record(command, *, timeout_s=0):
        recorded["command"] = list(command)
        recorded["timeout_s"] = timeout_s
        return ""

    monkeypatch.setattr(installers, "run_checked", record)

    WindowsPlatform().install_package("C:\\tmp\\app.msi", package_kind="msi", entry={})

    assert recorded["command"] == [
        "msiexec",
        "/i",
        "C:\\tmp\\app.msi",
        "/quiet",
        "/norestart",
    ]
    assert recorded["timeout_s"] == installers.INSTALL_TIMEOUT_S


def test_windows_package_removal_runs_the_manifests_command(monkeypatch):
    recorded = {}

    def record(command, **kwargs):
        recorded["command"] = command
        recorded["kwargs"] = kwargs
        return completed()

    monkeypatch.setattr(installers.subprocess, "run", record)

    WindowsPlatform().uninstall_package("msiexec /x {GUID} /quiet /norestart")

    assert recorded["command"] == "msiexec /x {GUID} /quiet /norestart"
    assert recorded["kwargs"]["shell"] is True


# --- the agent's own service, power, metrics ---


def test_windows_agent_service_state_reads_the_service_manager(monkeypatch):
    recorder = CommandRecorder(results=[completed(stdout="Running\n")])
    monkeypatch.setattr(windows_module.subprocess, "run", recorder)
    assert WindowsPlatform().read_agent_service_state() == "running"
    assert "Get-Service neutrino_agent" in recorder.commands[0][-1]

    recorder.results = [completed(stdout="Stopped\n")]
    assert WindowsPlatform().read_agent_service_state() == "stopped"

    recorder.results = [completed(stdout="")]
    assert WindowsPlatform().read_agent_service_state() == "unknown"


def test_windows_power_actions_ride_shutdown(monkeypatch):
    recorder = CommandRecorder(results=[completed(stdout="bye")])
    monkeypatch.setattr(windows_module.subprocess, "run", recorder)

    exit_code, output = WindowsPlatform().power("reboot")

    assert recorder.commands == [["shutdown", "/r", "/t", "0"]]
    assert exit_code == 0 and output == "bye"

    WindowsPlatform().power("poweroff")
    assert recorder.commands[-1] == ["shutdown", "/s", "/t", "0"]


def test_windows_metrics_parse_the_wmi_json():
    payload = json.dumps(
        {
            "cpu_percents": [10, 30],
            "memory_total_kb": 16 * 1024 * 1024,
            "memory_free_kb": 4 * 1024 * 1024,
            "disk_total_bytes": 1000,
            "disk_free_bytes": 250,
            "uptime_s": 3600,
            "processes": [
                {"pid": 4242, "name": "xrayr", "memory_bytes": 16 * 1024 * 1024 * 512},
                {"pid": None, "name": "junk"},
                "junk",
            ],
        }
    )

    metrics = _windows_metrics(payload)

    assert metrics.cpu_percent == 20.0
    assert metrics.cpu_core_percents == [10.0, 30.0]
    assert metrics.memory_percent == 75.0
    assert metrics.disk_percent == 75.0
    assert metrics.uptime_s == 3600
    assert len(metrics.processes) == 1
    assert metrics.processes[0].pid == 4242
    assert metrics.processes[0].name == "xrayr"
    assert metrics.processes[0].memory_percent == 50.0
    assert metrics.processes[0].cpu_percent == 0.0


def test_windows_metrics_take_a_single_processor_as_a_scalar():
    metrics = _windows_metrics(json.dumps({"cpu_percents": 40}))
    assert metrics.cpu_percent == 40.0
    assert metrics.cpu_core_percents == [40.0]


def test_windows_unreadable_metrics_read_as_defaults(monkeypatch):
    assert _windows_metrics("not json") == HostMetrics()
    assert _windows_metrics(json.dumps([1, 2])) == HostMetrics()

    def refuse(command, **kwargs):
        raise OSError("no powershell")

    monkeypatch.setattr(windows_module.subprocess, "run", refuse)
    assert WindowsPlatform().read_host_metrics() == HostMetrics()


# --- run-as is the logged-on account only ---


def test_windows_runs_as_the_logged_on_account_only():
    win32 = FakeWin32(console="Alice")
    platform = WindowsPlatform(win32=win32)

    result = platform.run_as_account("alice", ["cmd", "/c", "echo"], stdin="typed")

    assert result.stdout == "ran"
    assert ("run", ("cmd", "/c", "echo"), "typed", 120) in win32.calls

    with pytest.raises(PlatformUnsupportedError) as caught:
        platform.run_as_account("bob", ["cmd"])
    assert caught.value.code == "unsupported_platform"


def test_windows_nobody_at_the_console_refuses_run_as():
    platform = WindowsPlatform(win32=FakeWin32(console=""))
    with pytest.raises(PlatformUnsupportedError):
        platform.run_as_account("alice", ["cmd"])


def test_windows_an_empty_account_runs_directly(monkeypatch):
    recorder = CommandRecorder(results=[completed(stdout="direct")])
    monkeypatch.setattr(windows_module.subprocess, "run", recorder)

    result = WindowsPlatform(win32=FakeWin32()).run_as_account(
        "", ["cmd", "/c", "echo"], stdin="typed"
    )

    assert recorder.commands == [["cmd", "/c", "echo"]]
    assert recorder.kwargs[0]["input"] == "typed"
    assert result.stdout == "direct"


# --- file work stays inside the profile ---


def test_windows_path_judgment_is_the_profile():
    platform = WindowsPlatform()
    home = platform.account_home("bob")

    assert platform.is_path_writable(account="bob", path=home) is True
    assert platform.is_path_writable(account="bob", path=home + "\\nas") is True
    assert platform.is_path_writable(account="bob", path="C:/Users/bob/nas") is True
    assert platform.is_path_writable(account="bob", path="C:\\Users\\bobby") is False
    assert platform.is_path_writable(account="bob", path="D:\\data") is False
    assert platform.is_path_writable(account="", path="D:\\data") is True


def test_windows_directory_ops_stay_inside_the_profile(monkeypatch, tmp_path):
    profiles = tmp_path / "Users"
    monkeypatch.setattr(windows_module, "WINDOWS_PROFILES_DIR", str(profiles))
    platform = WindowsPlatform()
    inside = str(profiles / "bob" / "nas")

    platform.make_directory(account="bob", path=inside)
    assert (profiles / "bob" / "nas").is_dir()

    assert platform.list_directories(account="bob", path=str(profiles / "bob")) == [
        "nas"
    ]
    with pytest.raises(OSError):
        platform.list_directories(account="bob", path=str(tmp_path))
    with pytest.raises(OSError):
        platform.make_directory(account="bob", path=str(tmp_path / "outside"))
