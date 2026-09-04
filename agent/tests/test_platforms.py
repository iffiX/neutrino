"""The platform contract: advertised capabilities, honest refusals.

A platform says what it has; invoking what it lacks answers
``unsupported_platform``, never a guess. Linux steps down with ``runuser``
and judges people by its own floor.
"""

import collections
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
            "agent_service",
            "power",
            "metrics",
            "packages",
            "openssh",
        }
    )
    assert DarwinPlatform().capabilities == frozenset(
        {"accounts", "account_files", "run_as", "packages", "openssh"}
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
