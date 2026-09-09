"""The Linux platform: the account floor, ``runuser``, systemd.

Linux steps down with ``runuser`` and judges people by its own floor; homes
come from the account database, never ``$HOME``.
"""

import collections
import subprocess

import pytest

import neutrino_agent.platforms.linux as linux_module
from neutrino_agent.constants import AGENT_SERVICE_NAME
from neutrino_agent.platforms.linux import LinuxPlatform

PwdEntry = collections.namedtuple("PwdEntry", "pw_name pw_uid pw_shell pw_dir")


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


def test_linux_the_account_floor_is_the_platform_classes_own_number(
    monkeypatch, tmp_path
):
    home = tmp_path / "home"
    home.mkdir()
    assert linux_module.LINUX_HUMAN_UID_FLOOR == 1000
    entries = [
        PwdEntry("under_the_floor", 999, "/bin/bash", str(home)),
        PwdEntry("at_the_floor", 1000, "/bin/bash", str(home)),
    ]
    monkeypatch.setattr(linux_module.pwd, "getpwall", lambda: entries)

    assert LinuxPlatform().human_accounts() == ["at_the_floor"]


def test_linux_account_home_reads_the_account_database_not_the_environment(monkeypatch):
    monkeypatch.setenv("HOME", "/home/lying")
    entry = PwdEntry("alice", 1000, "/bin/bash", "/home/alice")
    monkeypatch.setattr(linux_module.pwd, "getpwnam", lambda name: entry)

    assert LinuxPlatform().account_home("alice") == "/home/alice"

    def unknown(name):
        raise KeyError(name)

    monkeypatch.setattr(linux_module.pwd, "getpwnam", unknown)
    with pytest.raises(KeyError):
        LinuxPlatform().account_home("ghost")


def test_linux_system_packages_ride_the_machines_own_package_manager(monkeypatch):
    present = {"apt-get": "/usr/bin/apt-get", "dnf": "/usr/bin/dnf"}
    monkeypatch.setattr(linux_module.shutil, "which", present.get)
    calls = []

    def record(command, **kwargs):
        calls.append((list(command), kwargs.get("timeout_s")))
        return "ok"

    monkeypatch.setattr(linux_module.installers, "run_checked", record)
    platform = LinuxPlatform()

    assert platform.install_system_packages(["cifs-utils"]) == "ok"
    present["apt-get"] = None
    platform.install_system_packages(["cifs-utils"])
    present["dnf"] = None
    platform.install_system_packages(["cifs-utils"])

    assert calls == [
        (
            ["apt-get", "install", "-y", "cifs-utils"],
            linux_module.installers.INSTALL_TIMEOUT_S,
        ),
        (
            ["dnf", "install", "-y", "cifs-utils"],
            linux_module.installers.INSTALL_TIMEOUT_S,
        ),
        (
            ["yum", "install", "-y", "cifs-utils"],
            linux_module.installers.INSTALL_TIMEOUT_S,
        ),
    ]


def test_linux_system_package_removal_purges_on_apt(monkeypatch):
    present = {"apt-get": "/usr/bin/apt-get", "dnf": "/usr/bin/dnf"}
    monkeypatch.setattr(linux_module.shutil, "which", present.get)
    calls = []

    def record(command, **kwargs):
        calls.append(list(command))
        return ""

    monkeypatch.setattr(linux_module.installers, "run_checked", record)
    platform = LinuxPlatform()

    platform.remove_system_packages(["cifs-utils"])
    present["apt-get"] = None
    platform.remove_system_packages(["cifs-utils"])
    assert platform.remove_system_packages([]) == ""

    assert calls == [
        ["apt-get", "purge", "-y", "cifs-utils"],
        ["dnf", "remove", "-y", "cifs-utils"],
    ]


def test_linux_service_state_and_power_go_through_systemd(monkeypatch):
    commands = []
    result = {"returncode": 0, "stdout": "active\n"}

    def record(command, **kwargs):
        commands.append(list(command))
        return subprocess.CompletedProcess(
            command, result["returncode"], stdout=result["stdout"], stderr=""
        )

    monkeypatch.setattr(linux_module.subprocess, "run", record)
    platform = LinuxPlatform()

    assert platform.read_agent_service_state() == "running"
    assert commands[-1] == ["systemctl", "is-active", AGENT_SERVICE_NAME]
    result["stdout"] = "failed\n"
    assert platform.read_agent_service_state() == "failed"

    result["stdout"] = "reboot scheduled"
    assert platform.power("reboot") == (0, "reboot scheduled")
    assert commands[-1] == ["systemctl", "reboot"]
    platform.power("poweroff")
    assert commands[-1] == ["systemctl", "poweroff"]
    platform.start_agent_service()
    assert commands[-1] == ["systemctl", "enable", "--now", AGENT_SERVICE_NAME]

    def refuse(command, **kwargs):
        raise OSError("no systemctl")

    monkeypatch.setattr(linux_module.subprocess, "run", refuse)
    assert platform.read_agent_service_state() == "unknown"
