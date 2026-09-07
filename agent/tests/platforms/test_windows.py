"""The Windows platform: pipe identity, profiles, cmdkey and ``net use``.

Privileged is an elevated Administrators token, so an unelevated admin
shell is ordinary; people are local profiles; a share is a stored
credential plus a mapping in the target account's own session — found by
enumerating the sessions, RDP counting the same as the console — whose
password rides standard input and whose script must print its success
marker; the SSH server is a capability whose install is allowed minutes.
Every Win32 call rides the seam, so nothing here touches a real Windows
API.
"""

import json
import subprocess

import pytest

import neutrino_agent.platforms.windows as windows_module
from neutrino_agent.constants import (
    AGENT_CONTROL_PIPE_NAME,
    AGENT_SERVICE_NAME_WINDOWS,
)
from neutrino_agent.core.metrics import HostMetrics
from neutrino_agent.modules import installers
from neutrino_agent.platforms.base import PlatformUnsupportedError, ShareAttachError
from neutrino_agent.platforms.windows import (
    WINDOWS_MOUNT_SUCCESS_MARKER,
    WTS_CONNECTSTATE_ACTIVE,
    WTS_CONNECTSTATE_DISCONNECTED,
    WindowsPlatform,
    _cpu_percent_from_deltas,
    _human_profiles,
    _mapping_script,
)


def session(session_id, account, state=WTS_CONNECTSTATE_ACTIVE):
    return {"session_id": session_id, "account": account, "state": state}


class FakeWin32:
    """The identity and step-down seam, scripted."""

    def __init__(
        self,
        *,
        account="Alice",
        is_elevated=False,
        is_admin=False,
        sessions=None,
    ):
        self.account = account
        self.is_elevated = is_elevated
        self.is_admin = is_admin
        self.session_rows = list(sessions or [])
        self.sessions_error = None
        self.calls = []
        self.impersonate_error = None
        self.token_error = None
        self.profile_dirs = {}
        self.run_result = subprocess.CompletedProcess(
            ["x"], 0, stdout=WINDOWS_MOUNT_SUCCESS_MARKER + "\n", stderr=""
        )

    def profile_directory(self, account):
        return self.profile_dirs.get(account, "")

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

    def sessions(self):
        if self.sessions_error is not None:
            raise self.sessions_error
        return [dict(row) for row in self.session_rows]

    def run_in_session(self, session_id, argv, *, stdin, timeout_s):
        self.calls.append(("run", session_id, tuple(argv), stdin, timeout_s))
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

    # The built-in Administrator counts when it has a profile: on a server
    # it is the person, and a rented Windows Server reached as it had nobody
    # to mount for or switch at the gateway. Guest, DefaultAccount and the
    # Defender sandbox account never do, profile or not.
    assert accounts == ["Administrator", "alice", "bob"]
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


# --- shares: stored credential plus a mapping in the account's session ---


def _run_call(win32):
    """The one in-session run the platform made."""
    return [call for call in win32.calls if call[0] == "run"][0]


def test_windows_attach_maps_in_the_accounts_session(monkeypatch, tmp_path):
    recorder = CommandRecorder()
    monkeypatch.setattr(windows_module.subprocess, "run", recorder)
    win32 = FakeWin32(sessions=[session(2, "alice")])
    credentials_path = tmp_path / "mounts" / "r1.credentials"

    WindowsPlatform(win32=win32).attach_share(
        account="alice",
        share_url="//hub/media",
        username="media",
        password="s3cret",  # scan: allow
        location="Z:",
        credentials_path=str(credentials_path),
    )

    # The only subprocess is icacls locking the credentials directory down.
    assert [command[0] for command in recorder.commands] == ["icacls"]
    icacls = recorder.commands[0]
    assert "/inheritance:r" in icacls
    assert "*S-1-5-18:(OI)(CI)F" in icacls and "*S-1-5-32-544:(OI)(CI)F" in icacls
    assert credentials_path.read_text() == "username=media\npassword=s3cret\n"

    # The mapping ran in alice's own session, from a script fed on stdin.
    _, session_id, argv, stdin, _ = _run_call(win32)
    assert session_id == 2
    assert argv == ("powershell", "-NoProfile", "-NonInteractive", "-Command", "-")
    assert "New-SmbMapping -LocalPath $local -RemotePath $remote" in stdin
    assert "cmdkey /add:$h /user:$u /pass:$p" in stdin
    assert "'hub'" in stdin and "'media'" in stdin and "'s3cret'" in stdin
    assert "'Z:'" in stdin


def test_windows_the_mapping_script_closes_itself_and_names_success():
    script = _mapping_script(
        host="hub", share="media", location="Z:", username="media", password="pw"
    )

    # PowerShell fed on stdin runs a multi-line block only once a blank line
    # closes it; without one the block is discarded with exit code zero.
    assert script.endswith("\n\n")
    assert script.splitlines()[-1] == ""
    marker_line = f"Write-Output '{WINDOWS_MOUNT_SUCCESS_MARKER}'"
    assert marker_line in script
    assert script.index("New-SmbMapping") < script.index(marker_line)
    assert script.index(marker_line) < script.index("exit 0")


def test_windows_a_silent_zero_exit_is_a_mount_failure(monkeypatch, tmp_path):
    credentials_path = tmp_path / "r1.credentials"
    credentials_path.write_text("username=media\npassword=kept\n")
    recorder = CommandRecorder()
    monkeypatch.setattr(windows_module.subprocess, "run", recorder)
    win32 = FakeWin32(sessions=[session(2, "alice")])
    win32.run_result = completed(returncode=0, stdout="PS >")

    with pytest.raises(ShareAttachError) as caught:
        WindowsPlatform(win32=win32).attach_share(
            account="alice",
            share_url="//hub/media",
            username="",
            password="",
            location="Z:",
            credentials_path=str(credentials_path),
        )
    assert caught.value.code == "mount_failed"
    assert "PS >" in caught.value.detail


def test_windows_attach_picks_the_accounts_rdp_session(monkeypatch, tmp_path):
    credentials_path = tmp_path / "r1.credentials"
    credentials_path.write_text("username=media\npassword=kept\n")
    recorder = CommandRecorder()
    monkeypatch.setattr(windows_module.subprocess, "run", recorder)
    # The console session is an empty shell; the person is Active over RDP.
    win32 = FakeWin32(sessions=[session(1, ""), session(3, "lab")])

    WindowsPlatform(win32=win32).attach_share(
        account="lab",
        share_url="//hub/media",
        username="",
        password="",
        location="Z:",
        credentials_path=str(credentials_path),
    )

    assert _run_call(win32)[1] == 3


def test_windows_an_active_session_wins_over_a_disconnected_one():
    win32 = FakeWin32(
        sessions=[
            session(2, "alice", WTS_CONNECTSTATE_DISCONNECTED),
            session(5, "alice"),
        ]
    )
    win32.run_result = completed(returncode=0, stdout="ok")

    WindowsPlatform(win32=win32).run_as_account("alice", ["cmd"])

    assert _run_call(win32)[1] == 5


def test_windows_a_disconnected_session_is_the_fallback():
    win32 = FakeWin32(sessions=[session(2, "alice", WTS_CONNECTSTATE_DISCONNECTED)])
    win32.run_result = completed(returncode=0, stdout="ok")

    WindowsPlatform(win32=win32).run_as_account("alice", ["cmd"])

    assert _run_call(win32)[1] == 2


def test_windows_session_accounts_compare_case_insensitively():
    win32 = FakeWin32(sessions=[session(4, "Alice")])
    win32.run_result = completed(returncode=0, stdout="ok")

    WindowsPlatform(win32=win32).run_as_account("alice", ["cmd"])

    assert _run_call(win32)[1] == 4


def test_windows_the_password_is_on_no_argument_vector(monkeypatch, tmp_path):
    recorder = CommandRecorder()
    monkeypatch.setattr(windows_module.subprocess, "run", recorder)
    win32 = FakeWin32(sessions=[session(2, "alice")])

    WindowsPlatform(win32=win32).attach_share(
        account="alice",
        share_url="//hub/media",
        username="media",
        password="it's secret",  # scan: allow
        location="Z:",
        credentials_path=str(tmp_path / "r1.credentials"),
    )

    for command in recorder.commands:
        assert all("secret" not in part for part in command)
    _, _, argv, stdin, _ = _run_call(win32)
    assert all("secret" not in part for part in argv)
    assert "'it''s secret'" in stdin


def test_windows_reattach_uses_the_kept_credentials(monkeypatch, tmp_path):
    credentials_path = tmp_path / "r1.credentials"
    credentials_path.write_text("username=media\npassword=kept\n")
    recorder = CommandRecorder()
    monkeypatch.setattr(windows_module.subprocess, "run", recorder)
    win32 = FakeWin32(sessions=[session(2, "alice")])

    WindowsPlatform(win32=win32).attach_share(
        account="alice",
        share_url="//hub/media",
        username="",
        password="",
        location="Z:",
        credentials_path=str(credentials_path),
    )

    # No password given, so nothing is rewritten and no icacls runs; the kept
    # login rides the session script.
    assert recorder.commands == []
    assert "'kept'" in _run_call(win32)[3]


def test_windows_attach_without_a_session_of_the_account_is_refused(
    monkeypatch, tmp_path
):
    recorder = CommandRecorder()
    monkeypatch.setattr(windows_module.subprocess, "run", recorder)
    credentials_path = tmp_path / "r1.credentials"
    credentials_path.write_text("username=media\npassword=kept\n")

    with pytest.raises(ShareAttachError) as caught:
        WindowsPlatform(win32=FakeWin32(sessions=[session(2, "alice")])).attach_share(
            account="bob",
            share_url="//hub/media",
            username="",
            password="",
            location="Z:",
            credentials_path=str(credentials_path),
        )
    assert caught.value.code == "no_logged_on_session"


def test_windows_attach_refusals_are_typed(monkeypatch, tmp_path):
    recorder = CommandRecorder()
    monkeypatch.setattr(windows_module.subprocess, "run", recorder)
    win32 = FakeWin32(sessions=[session(2, "alice")])

    with pytest.raises(ShareAttachError) as caught:
        WindowsPlatform(win32=win32).attach_share(
            account="alice",
            share_url="//hub/media",
            username="media",
            password="",
            location="Z:",
            credentials_path=str(tmp_path / "gone.credentials"),
        )
    assert caught.value.code == "credentials_missing"

    with pytest.raises(ShareAttachError) as caught:
        WindowsPlatform(win32=win32).attach_share(
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
    recorder = CommandRecorder()
    monkeypatch.setattr(windows_module.subprocess, "run", recorder)
    win32 = FakeWin32(sessions=[session(2, "alice")])
    win32.run_result = completed(returncode=1, stderr="System error 86 has occurred.")

    with pytest.raises(ShareAttachError) as caught:
        WindowsPlatform(win32=win32).attach_share(
            account="alice",
            share_url="//hub/media",
            username="",
            password="",
            location="Z:",
            credentials_path=str(credentials_path),
        )
    assert caught.value.code == "mount_failed"
    assert "System error 86" in caught.value.detail


def test_windows_detach_deletes_the_mapping_in_the_accounts_session():
    win32 = FakeWin32(sessions=[session(1, ""), session(3, "alice")])
    win32.run_result = completed(returncode=0, stdout="deleted")

    WindowsPlatform(win32=win32).detach_share(location="Z:", account="alice")

    assert _run_call(win32)[1] == 3
    assert _run_call(win32)[2] == ("net", "use", "Z:", "/delete", "/y")

    win32.run_result = completed(returncode=2, stderr="not found")
    with pytest.raises(ShareAttachError) as caught:
        WindowsPlatform(win32=win32).detach_share(location="Z:", account="alice")
    assert caught.value.code == "unmount_failed"


def test_windows_detach_without_a_session_is_refused():
    with pytest.raises(ShareAttachError) as caught:
        WindowsPlatform(win32=FakeWin32(sessions=[])).detach_share(
            location="Z:", account="alice"
        )
    assert caught.value.code == "no_logged_on_session"

    with pytest.raises(ShareAttachError) as caught:
        WindowsPlatform(win32=FakeWin32(sessions=[session(2, "alice")])).detach_share(
            location="Z:"
        )
    assert caught.value.code == "no_logged_on_session"


def test_windows_attachment_is_read_in_the_accounts_session():
    win32 = FakeWin32(sessions=[session(1, ""), session(3, "alice")])
    win32.run_result = completed(returncode=0, stdout="Remote name  \\\\hub\\media\n")
    platform = WindowsPlatform(win32=win32)

    assert platform.is_share_attached(location="Z:", account="alice") is True
    assert _run_call(win32)[1] == 3
    assert _run_call(win32)[2] == ("net", "use", "Z:")

    win32.run_result = completed(returncode=2)
    assert platform.is_share_attached(location="Z:", account="alice") is False


def test_windows_nothing_is_attached_without_a_session():
    platform = WindowsPlatform(win32=FakeWin32(sessions=[]))
    assert platform.is_share_attached(location="Z:", account="alice") is False
    assert platform.is_share_attached(location="Z:") is False


def test_windows_credentials_land_under_a_programdata_shaped_dir(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    recorder = CommandRecorder()
    monkeypatch.setattr(windows_module.subprocess, "run", recorder)
    made = []

    def record_makedirs(path, exist_ok=False):
        made.append(path)

    monkeypatch.setattr(windows_module.os, "makedirs", record_makedirs)
    directory = "C:\\ProgramData\\Neutrino\\agent\\mount_credentials"

    WindowsPlatform().write_share_credentials(
        credentials_path=directory + "\\r1.credentials",
        username="media",
        password="pw",
    )

    # The backslash path resolves to its own directory, never a POSIX read
    # of `C:` — icacls restricts exactly that directory.
    assert made == [directory]
    assert recorder.commands[0][:2] == ["icacls", directory]


def test_windows_agent_data_root_is_under_programdata():
    assert WindowsPlatform().agent_data_dir() == "C:\\ProgramData\\Neutrino\\agent"


def test_windows_mounting_is_native():
    assert WindowsPlatform().has_mount_tooling() is True


def test_windows_mount_locations_are_unused_drive_letters(monkeypatch):
    platform = WindowsPlatform()

    for bad in ("", "Z", "Z:\\media", "/mnt/media", "ZZ:"):
        assert platform.validate_mount_location(location=bad) == {
            "code": "mountpoint_not_drive_letter",
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


def test_windows_agent_state_asks_the_service_control_manager(monkeypatch):
    """The agent is a service here, not a task the scheduler runs: the state
    is the manager's own number, which no language translates."""
    asked = []

    def read_state(name, **kwargs):
        asked.append(name)
        return "running"

    monkeypatch.setattr(windows_module.windows_service, "read_state", read_state)

    assert WindowsPlatform().read_agent_service_state() == "running"
    assert asked == [AGENT_SERVICE_NAME_WINDOWS]


def test_windows_start_asks_the_service_control_manager(monkeypatch):
    started = []
    monkeypatch.setattr(
        windows_module.windows_service, "start", lambda name: started.append(name)
    )

    WindowsPlatform().start_agent_service()

    assert started == [AGENT_SERVICE_NAME_WINDOWS]


def test_windows_start_hint_names_the_service_not_a_task():
    hint = WindowsPlatform().agent_service_start_hint()
    assert hint == f"sc start {AGENT_SERVICE_NAME_WINDOWS}"
    assert "schtasks" not in hint
    assert "systemctl" not in hint and "sudo" not in hint


def test_windows_power_actions_ride_shutdown(monkeypatch):
    recorder = CommandRecorder(results=[completed(stdout="bye")])
    monkeypatch.setattr(windows_module.subprocess, "run", recorder)

    exit_code, output = WindowsPlatform().power("reboot")

    assert recorder.commands == [["shutdown", "/r", "/t", "0"]]
    assert exit_code == 0 and output == "bye"

    WindowsPlatform().power("poweroff")
    assert recorder.commands[-1] == ["shutdown", "/s", "/t", "0"]


class FakeMetricsWin32:
    """The metrics seam, scripted, so no real Win32 call is made."""

    def __init__(self, *, times, memory, disk, uptime_ms, error=None):
        self._times = list(times)
        self._memory = memory
        self._disk = disk
        self._uptime_ms = uptime_ms
        self._error = error
        self.disk_paths = []
        # One list per sample; the last one is reused once they run out.
        self.process_samples = []

    def system_times(self):
        if self._error is not None:
            raise self._error
        return self._times.pop(0)

    def memory_status(self):
        return self._memory

    def disk_space(self, path):
        self.disk_paths.append(path)
        return self._disk

    def uptime_ms(self):
        if isinstance(self._uptime_ms, list):
            return (
                self._uptime_ms.pop(0)
                if len(self._uptime_ms) > 1
                else self._uptime_ms[0]
            )
        return self._uptime_ms

    def processes(self):
        if not self.process_samples:
            return []
        if len(self.process_samples) > 1:
            return self.process_samples.pop(0)
        return self.process_samples[0]


def test_windows_cpu_percent_is_the_busy_share_between_two_samples():
    assert _cpu_percent_from_deltas(None, (100, 200, 100)) == 0.0
    # kernel delta 200, user delta 200 -> total 400; idle delta 50 -> busy 350.
    assert _cpu_percent_from_deltas((100, 200, 100), (150, 400, 300)) == 87.5
    # A total of zero cannot divide; it reads as idle.
    assert _cpu_percent_from_deltas((100, 200, 100), (100, 200, 100)) == 0.0


def test_windows_metrics_come_from_native_calls(monkeypatch):
    win32 = FakeMetricsWin32(
        times=[(100, 200, 100), (150, 400, 300)],
        memory=(16 * 1024**3, 4 * 1024**3),
        disk=(1000, 250),
        uptime_ms=3_600_000,
    )
    platform = WindowsPlatform(win32=win32)

    # No subprocess is ever spawned for a beat.
    def refuse(*args, **kwargs):
        raise AssertionError("metrics must not spawn a subprocess")

    monkeypatch.setattr(windows_module.subprocess, "run", refuse)

    first = platform.read_host_metrics()
    assert first.cpu_percent == 0.0
    assert first.cpu_core_percents == []
    assert first.processes == []
    assert first.memory_percent == 75.0
    assert first.disk_percent == 75.0
    assert first.uptime_s == 3600

    second = platform.read_host_metrics()
    assert second.cpu_percent == 87.5


def test_windows_metrics_read_the_system_drive(monkeypatch):
    monkeypatch.setenv("SystemDrive", "D:")
    win32 = FakeMetricsWin32(
        times=[(0, 0, 0)], memory=(8, 4), disk=(100, 50), uptime_ms=0
    )

    WindowsPlatform(win32=win32).read_host_metrics()

    assert win32.disk_paths == ["D:\\"]


def test_windows_unreadable_metrics_read_as_defaults():
    win32 = FakeMetricsWin32(
        times=[], memory=(0, 0), disk=(0, 0), uptime_ms=0, error=OSError("no api")
    )
    assert WindowsPlatform(win32=win32).read_host_metrics() == HostMetrics()


# --- run-as is an account with a logged-on session only ---


def test_windows_runs_as_an_account_with_a_session_only():
    win32 = FakeWin32(sessions=[session(2, "Alice")])
    win32.run_result = completed(returncode=0, stdout="ran")
    platform = WindowsPlatform(win32=win32)

    result = platform.run_as_account("alice", ["cmd", "/c", "echo"], stdin="typed")

    assert result.stdout == "ran"
    assert ("run", 2, ("cmd", "/c", "echo"), "typed", 120) in win32.calls

    with pytest.raises(PlatformUnsupportedError) as caught:
        platform.run_as_account("bob", ["cmd"])
    assert caught.value.code == "unsupported_platform"


def test_windows_no_session_anywhere_refuses_run_as():
    platform = WindowsPlatform(win32=FakeWin32(sessions=[]))
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


def test_windows_account_home_comes_from_the_profile_database():
    win32 = FakeWin32()
    win32.profile_dirs = {
        "SYSTEM": "C:\\Windows\\system32\\config\\systemprofile",
        "alice": "C:\\Users\\alice",
    }
    platform = WindowsPlatform(win32=win32)

    # SYSTEM's home is its systemprofile, never a C:\Users child.
    assert (
        platform.account_home("SYSTEM")
        == "C:\\Windows\\system32\\config\\systemprofile"
    )
    assert platform.account_home("alice") == "C:\\Users\\alice"
    # A name the database cannot place falls back to the profiles directory.
    assert platform.account_home("ghost") == WindowsPlatform().account_home("ghost")


def test_windows_path_judgment_is_the_profile():
    platform = WindowsPlatform()
    home = platform.account_home("bob")

    assert platform.is_path_writable(account="bob", path=home) is True
    assert platform.is_path_writable(account="bob", path=home + "\\nas") is True
    assert platform.is_path_writable(account="bob", path="C:/Users/bob/nas") is True
    assert platform.is_path_writable(account="bob", path="C:\\Users\\bobby") is False
    assert platform.is_path_writable(account="bob", path="D:\\data") is False
    assert platform.is_path_writable(account="", path="D:\\data") is True
    # A free drive letter is a mount location an ordinary account may claim.
    assert platform.is_path_writable(account="bob", path="Z:") is True
    assert platform.is_path_writable(account="bob", path="Z:\\") is True


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


# --- what the page offers as a mount location ---


def test_windows_suggests_the_top_free_drive_letter(monkeypatch):
    """Z: first: the low letters are where Windows and removable media land,
    and a suggestion that collides is one the person retypes. Found on a
    laptop offered `C:\\Users\\x/nas/share`, a path with two kinds of slash
    that no drive-letter machine could take."""
    taken = {"C:\\", "D:\\", "Z:\\", "Y:\\"}
    monkeypatch.setattr(windows_module.os.path, "exists", lambda path: path in taken)

    assert WindowsPlatform().suggest_mount_location() == "X:"


def test_windows_suggests_nothing_when_every_letter_is_taken(monkeypatch):
    monkeypatch.setattr(windows_module.os.path, "exists", lambda path: True)

    assert WindowsPlatform().suggest_mount_location() == ""


# --- a window on the screen a person is at ---


def test_windows_starts_the_client_in_the_seated_session():
    """The agent's own session is 0, where a window is a window nobody
    sees. Found on a laptop: Connect did nothing visible."""
    win32 = FakeWin32(
        sessions=[
            {"session_id": 0, "account": "", "state": WTS_CONNECTSTATE_ACTIVE},
            {"session_id": 2, "account": "Pat", "state": WTS_CONNECTSTATE_ACTIVE},
        ]
    )
    win32.started = []
    win32.start_in_session = lambda session_id, argv: win32.started.append(
        (session_id, tuple(argv))
    )
    platform = WindowsPlatform()
    platform._win32 = lambda: win32

    outcome = platform.start_on_screen(["rustdesk.exe", "--connect", "10.0.0.6"])

    assert outcome is None
    assert win32.started == [(2, ("rustdesk.exe", "--connect", "10.0.0.6"))]


def test_windows_refuses_a_window_with_nobody_seated():
    win32 = FakeWin32(
        sessions=[
            {"session_id": 0, "account": "", "state": WTS_CONNECTSTATE_ACTIVE},
            {"session_id": 3, "account": "Pat", "state": WTS_CONNECTSTATE_DISCONNECTED},
        ]
    )
    platform = WindowsPlatform()
    platform._win32 = lambda: win32

    outcome = platform.start_on_screen(["rustdesk.exe", "--connect", "10.0.0.6"])

    assert outcome == {"code": "rdp_no_desktop", "params": {}}


def test_windows_reports_a_refused_spawn_as_a_launch_failure():
    win32 = FakeWin32(
        sessions=[{"session_id": 2, "account": "Pat", "state": WTS_CONNECTSTATE_ACTIVE}]
    )

    def refuse(session_id, argv):
        raise OSError("access denied")

    win32.start_in_session = refuse
    platform = WindowsPlatform()
    platform._win32 = lambda: win32

    outcome = platform.start_on_screen(["rustdesk.exe", "--connect", "10.0.0.6"])

    assert outcome == {
        "code": "rdp_launch_failed",
        "params": {"detail": "access denied"},
    }


def test_windows_lists_the_busiest_processes_between_two_beats():
    """Each row's processor time between two beats over the wall time
    between them is its share of one core, as on Linux; the working set
    over physical memory is its share of memory. The first beat has nothing
    to compare against and lists none."""
    gib = 1024**3
    win32 = FakeMetricsWin32(
        times=[(0, 0, 0), (0, 0, 0), (0, 0, 0)],
        memory=(4 * gib, 2 * gib),
        disk=(100, 50),
        uptime_ms=[10_000, 15_000, 20_000],
    )
    win32.process_samples = [
        [
            {
                "pid": 7,
                "name": "app.exe",
                "user": "Pat",
                "cpu_100ns": 0,
                "resident_bytes": gib,
            },
            {
                "pid": 9,
                "name": "idle.exe",
                "user": "",
                "cpu_100ns": 5_000,
                "resident_bytes": 0,
            },
        ],
        [
            # 2.5 s of processor time over a 5 s beat: half of one core.
            {
                "pid": 7,
                "name": "app.exe",
                "user": "Pat",
                "cpu_100ns": 25_000_000,
                "resident_bytes": gib,
            },
            {
                "pid": 9,
                "name": "idle.exe",
                "user": "",
                "cpu_100ns": 5_000,
                "resident_bytes": 0,
            },
            # New since the last beat: no share to compute yet.
            {
                "pid": 11,
                "name": "new.exe",
                "user": "Pat",
                "cpu_100ns": 9_000_000,
                "resident_bytes": 0,
            },
        ],
    ]
    platform = WindowsPlatform(win32=win32)

    first = platform.read_host_metrics()
    second = platform.read_host_metrics()

    assert first.processes == []
    rows = {process.pid: process for process in second.processes}
    assert [process.pid for process in second.processes] == [7, 9, 11]
    assert rows[7].name == "app.exe" and rows[7].user == "Pat"
    assert rows[7].cpu_percent == 50.0
    assert rows[7].memory_percent == 25.0
    assert rows[9].cpu_percent == 0.0
    assert rows[11].cpu_percent == 0.0


def test_windows_processes_are_capped_at_the_monitors_dozen():
    win32 = FakeMetricsWin32(
        times=[(0, 0, 0), (0, 0, 0)], memory=(1, 0), disk=(1, 0), uptime_ms=[0, 1000]
    )
    rows = [
        {
            "pid": pid,
            "name": f"{pid}.exe",
            "user": "",
            "cpu_100ns": pid,
            "resident_bytes": 0,
        }
        for pid in range(1, 30)
    ]
    win32.process_samples = [rows, rows]
    platform = WindowsPlatform(win32=win32)

    platform.read_host_metrics()
    listed = platform.read_host_metrics().processes

    assert len(listed) == windows_module.PROCESS_TOP_COUNT


def test_a_refused_process_walk_lists_none_and_keeps_the_rest():
    win32 = FakeMetricsWin32(
        times=[(0, 0, 0)], memory=(4, 2), disk=(100, 50), uptime_ms=7_000
    )

    def refuse():
        raise OSError("no")

    win32.processes = refuse

    sample = WindowsPlatform(win32=win32).read_host_metrics()

    assert sample.processes == []
    assert sample.uptime_s == 7
