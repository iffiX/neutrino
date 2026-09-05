"""The platform contract: advertised capabilities, honest refusals.

A platform says what it has; invoking what it lacks answers
``unsupported_platform``, never a guess. Linux steps down with ``runuser``
and judges people by its own floor.
"""

import collections
import struct
import subprocess

import pytest

import neutrino_agent.platforms.linux as linux_module
from neutrino_agent.platforms.base import AgentPlatform, PlatformUnsupportedError
from neutrino_agent.platforms.darwin import DarwinPlatform
from neutrino_agent.platforms.linux import LinuxPlatform
from neutrino_agent.platforms.windows import WindowsPlatform

PwdEntry = collections.namedtuple("PwdEntry", "pw_name pw_uid pw_shell pw_dir")


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
            "metrics",
            "packages",
            "openssh",
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


def test_no_platform_advertises_shares_yet():
    for platform in (LinuxPlatform(), DarwinPlatform(), WindowsPlatform()):
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
        LinuxPlatform().is_share_attached(location="/mnt/share")


def test_base_file_operations_refuse_without_run_as():
    with pytest.raises(PlatformUnsupportedError):
        AgentPlatform().read_account_file(account="alice", relative="f")


class FakePeerConnection:
    def __init__(self, credential: bytes):
        self._credential = credential

    def getsockopt(self, level, option, length):
        return self._credential[:length]


def test_linux_reads_peer_identity_from_peercred(monkeypatch):
    entry = PwdEntry("alice", 1000, "/bin/bash", "/home/alice")
    monkeypatch.setattr(linux_module.pwd, "getpwuid", lambda uid: entry)
    connection = FakePeerConnection(struct.pack("3i", 42, 1000, 1000))

    identity = LinuxPlatform().read_peer_identity(connection)

    assert identity == {"account": "alice", "uid": 1000, "is_privileged": False}


def test_linux_peer_uid_zero_is_privileged():
    connection = FakePeerConnection(struct.pack("3i", 1, 0, 0))

    identity = LinuxPlatform().read_peer_identity(connection)

    assert identity == {"account": "root", "uid": 0, "is_privileged": True}


def test_linux_refuses_an_unresolvable_peer_uid(monkeypatch):
    def unknown(uid):
        raise KeyError(uid)

    monkeypatch.setattr(linux_module.pwd, "getpwuid", unknown)
    connection = FakePeerConnection(struct.pack("3i", 42, 4242, 4242))

    with pytest.raises(KeyError):
        LinuxPlatform().read_peer_identity(connection)


def test_windows_has_no_peer_identity_yet():
    with pytest.raises(PlatformUnsupportedError):
        WindowsPlatform().read_peer_identity(object())
    with pytest.raises(PlatformUnsupportedError):
        WindowsPlatform().control_socket_path()


def test_linux_human_accounts_apply_the_floor(monkeypatch, tmp_path):
    home = tmp_path / "alice"
    home.mkdir()
    entries = [
        PwdEntry("root", 0, "/bin/bash", "/root"),
        PwdEntry("daemon", 1, "/usr/sbin/nologin", "/usr/sbin"),
        PwdEntry("service", 999, "/bin/bash", str(home)),
        PwdEntry("alice", 1000, "/bin/bash", str(home)),
        PwdEntry("shell_less", 1001, "/usr/sbin/nologin", str(home)),
        PwdEntry("homeless", 1002, "/bin/bash", str(tmp_path / "missing")),
        PwdEntry("nobody", 65534, "/bin/sh", "/nonexistent"),
    ]
    monkeypatch.setattr(linux_module.pwd, "getpwall", lambda: entries)

    assert LinuxPlatform().human_accounts() == ["alice"]


def test_linux_steps_down_with_runuser(monkeypatch):
    recorded = {}

    def record(command, **kwargs):
        recorded["command"] = list(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(linux_module.subprocess, "run", record)
    monkeypatch.setattr(linux_module.os, "geteuid", lambda: 0)

    LinuxPlatform().run_as_account("alice", ["id"])

    assert recorded["command"] == ["runuser", "-u", "alice", "--", "id"]


def test_linux_runs_directly_without_root_or_account(monkeypatch):
    recorded = []

    def record(command, **kwargs):
        recorded.append(list(command))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(linux_module.subprocess, "run", record)
    monkeypatch.setattr(linux_module.os, "geteuid", lambda: 1000)
    LinuxPlatform().run_as_account("alice", ["id"])
    monkeypatch.setattr(linux_module.os, "geteuid", lambda: 0)
    LinuxPlatform().run_as_account("", ["id"])

    assert recorded == [["id"], ["id"]]


def test_account_file_ops_ignore_the_home_variable(monkeypatch, tmp_path):
    """The account database, not $HOME, names the home: a root agent's
    environment says /root, and writing there is the bug of record."""
    home = tmp_path / "alice"
    home.mkdir()
    wrong = tmp_path / "wrong"
    wrong.mkdir()
    monkeypatch.setenv("HOME", str(wrong))
    entry = PwdEntry("alice", 1000, "/bin/bash", str(home))
    monkeypatch.setattr(linux_module.pwd, "getpwnam", lambda name: entry)
    platform = LinuxPlatform()

    platform.write_account_file(
        account="alice", relative=".claude/settings.json", text='{"model": "opus"}'
    )

    assert (home / ".claude/settings.json").read_text() == '{"model": "opus"}'
    assert not (wrong / ".claude").exists()
    assert (
        platform.read_account_file(account="alice", relative=".claude/settings.json")
        == '{"model": "opus"}'
    )


def test_linux_step_down_env_carries_the_target_identity(monkeypatch):
    """runuser passes the environment through, so the child's HOME, USER and
    LOGNAME must be set to the target account's own values."""
    entry = PwdEntry("alice", 1000, "/bin/bash", "/home/alice")
    monkeypatch.setattr(linux_module.pwd, "getpwnam", lambda name: entry)
    recorded = {}

    def record(command, **kwargs):
        recorded["command"] = list(command)
        recorded["env"] = kwargs.get("env")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(linux_module.subprocess, "run", record)
    monkeypatch.setattr(linux_module.os, "geteuid", lambda: 0)

    LinuxPlatform().run_as_account("alice", ["id"])

    assert recorded["command"][:4] == ["runuser", "-u", "alice", "--"]
    assert recorded["env"]["HOME"] == "/home/alice"
    assert recorded["env"]["USER"] == "alice"
    assert recorded["env"]["LOGNAME"] == "alice"
