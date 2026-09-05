"""The platform contract: advertised capabilities, honest refusals.

A platform says what it has; invoking what it lacks answers
``unsupported_platform``, never a guess. The shared file operations ride one
step-down seam, and the home they resolve comes from the account database.
"""

import os
import subprocess

import pytest

from neutrino_agent.constants import AGENT_STEP_DOWN_TIMEOUT_S
from neutrino_agent.platforms.base import AgentPlatform, PlatformUnsupportedError
from neutrino_agent.platforms.darwin import DarwinPlatform
from neutrino_agent.platforms.linux import LinuxPlatform
from neutrino_agent.platforms.windows import WindowsPlatform

ACCOUNT_HOME = "/home/alice"


class RecordingPlatform(AgentPlatform):
    """A platform whose only mechanism is a recorded step-down."""

    os_name = "recording"
    capabilities = frozenset({"accounts", "account_files", "run_as"})

    def __init__(self):
        self.calls = []
        self.stdout = ""
        self.stderr = ""
        self.returncode = 0

    def account_home(self, account: str) -> str:
        return ACCOUNT_HOME

    def run_as_account(
        self,
        account: str,
        argv: list,
        *,
        stdin: str = "",
        timeout_s: int = AGENT_STEP_DOWN_TIMEOUT_S,
    ) -> "subprocess.CompletedProcess":
        self.calls.append(
            {
                "account": account,
                "argv": list(argv),
                "stdin": stdin,
                "timeout_s": timeout_s,
            }
        )
        return subprocess.CompletedProcess(
            argv, self.returncode, stdout=self.stdout, stderr=self.stderr
        )


def test_the_base_platform_advertises_nothing():
    assert AgentPlatform().capabilities == frozenset()


def test_each_platform_advertises_its_capability_set():
    assert LinuxPlatform().capabilities == frozenset(
        {
            "accounts",
            "account_files",
            "run_as",
            "control_socket",
            "agent_service",
            "power",
            "system_packages",
            "metrics",
            "packages",
            "openssh",
            "shares",
        }
    )
    assert DarwinPlatform().capabilities == frozenset(
        {
            "accounts",
            "account_files",
            "run_as",
            "control_socket",
            "packages",
            "openssh",
        }
    )
    assert WindowsPlatform().capabilities == frozenset(
        {"account_files", "packages", "openssh"}
    )


def test_only_linux_advertises_shares_so_far():
    assert LinuxPlatform().has_capability("shares")
    for platform in (DarwinPlatform(), WindowsPlatform()):
        assert not platform.has_capability("shares")


def test_an_absent_capability_is_refused_not_guessed():
    with pytest.raises(PlatformUnsupportedError) as caught:
        WindowsPlatform().run_as_account("bob", ["id"])
    assert caught.value.code == "unsupported_platform"
    with pytest.raises(PlatformUnsupportedError):
        AgentPlatform().read_host_metrics()
    with pytest.raises(PlatformUnsupportedError):
        DarwinPlatform().power("reboot")
    with pytest.raises(PlatformUnsupportedError):
        WindowsPlatform().human_accounts()
    with pytest.raises(PlatformUnsupportedError):
        DarwinPlatform().is_share_attached(location="/mnt/share")


def test_base_file_operations_refuse_without_run_as():
    with pytest.raises(PlatformUnsupportedError):
        AgentPlatform().read_account_file(account="alice", relative="f")


def test_base_account_home_refuses_rather_than_reading_the_environment(monkeypatch):
    monkeypatch.setenv("HOME", "/home/lying")

    with pytest.raises(PlatformUnsupportedError) as caught:
        AgentPlatform().account_home("alice")

    assert caught.value.code == "unsupported_platform"


def test_base_account_files_resolve_the_home_from_the_account_database(monkeypatch):
    """A root agent's $HOME names root's home; the snippet must carry the
    account database's answer instead."""
    monkeypatch.setenv("HOME", "/home/lying")
    platform = RecordingPlatform()

    platform.write_account_file(
        account="alice",
        relative=".claude/settings.json",
        text='{"model": "opus"}',
        mode="600",
    )

    call = platform.calls[-1]
    assert call["account"] == "alice"
    assert os.path.basename(call["argv"][0]) in ("python3", "python")
    assert call["argv"][1] == "-c"
    script = call["argv"][2]
    assert f"p = pathlib.Path('{ACCOUNT_HOME}') / '.claude/settings.json'" in script
    assert "/home/lying" not in script
    assert "pathlib.Path.home()" not in script
    assert "m = '600'" in script
    assert "p.chmod(int(m, 8))" in script
    assert call["stdin"] == '{"model": "opus"}'
    assert '{"model": "opus"}' not in script
    assert call["timeout_s"] == AGENT_STEP_DOWN_TIMEOUT_S


def test_base_account_files_read_and_remove_the_same_path(monkeypatch):
    monkeypatch.setenv("HOME", "/home/lying")
    platform = RecordingPlatform()
    platform.stdout = '{"model": "opus"}'

    assert (
        platform.read_account_file(account="alice", relative=".claude/settings.json")
        == '{"model": "opus"}'
    )
    platform.stdout = "600\n"
    assert (
        platform.read_account_file_mode(
            account="alice", relative=".claude/settings.json"
        )
        == "600"
    )
    platform.remove_account_file(account="alice", relative=".claude/settings.json")
    platform.read_account_file(account="", relative="own.json")

    scripts = [call["argv"][2] for call in platform.calls]
    for script in scripts[:3]:
        assert f"pathlib.Path('{ACCOUNT_HOME}') / '.claude/settings.json'" in script
    assert "p.read_text() if p.is_file() else ''" in scripts[0]
    assert "oct(p.stat().st_mode & 0o777)[2:]" in scripts[1]
    assert "p.unlink() if p.is_file() else None" in scripts[2]
    assert "pathlib.Path.home() / 'own.json'" in scripts[3]
    assert platform.calls[3]["account"] == ""
    assert "/home/lying" not in "".join(scripts)


def test_base_directory_operations_step_down_to_the_account():
    platform = RecordingPlatform()
    platform.stdout = '["docs", "media"]'

    assert platform.list_directories(account="alice", path="/srv/pool") == [
        "docs",
        "media",
    ]
    platform.make_directory(account="alice", path="/srv/pool/new")
    platform.stdout = "1"
    assert platform.is_path_writable(account="alice", path="/srv/pool/new")
    platform.stdout = "0"
    assert not platform.is_path_writable(account="alice", path="/srv/pool/new")

    assert [call["account"] for call in platform.calls] == ["alice"] * 4
    assert "os.scandir('/srv/pool')" in platform.calls[0]["argv"][2]
    assert "os.makedirs('/srv/pool/new', exist_ok=True)" in platform.calls[1]["argv"][2]
    assert "os.path.abspath('/srv/pool/new')" in platform.calls[2]["argv"][2]

    platform.returncode = 1
    platform.stderr = "Permission denied"
    with pytest.raises(OSError) as caught:
        platform.list_directories(account="alice", path="/root")
    assert "Permission denied" in str(caught.value)
    with pytest.raises(OSError):
        platform.make_directory(account="alice", path="/root/new")
    assert not platform.is_path_writable(account="alice", path="/root/new")
