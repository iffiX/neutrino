"""The Linux platform: the account floor, ``runuser``, systemd, iproute2.

Linux steps down with ``runuser`` and judges people by its own floor; homes
come from the account database, never ``$HOME``; the interfaces are what
``ip -j addr`` prints, loopback left out; the machine id is the first file
systemd or dbus wrote that holds one.
"""

import collections
import json
import subprocess

import pytest

import neutrino_agent.platforms.linux as linux_module
from neutrino_agent.constants import AGENT_SERVICE_NAME
from neutrino_agent.platforms.linux import LinuxPlatform

PwdEntry = collections.namedtuple("PwdEntry", "pw_name pw_uid pw_shell pw_dir")

# What ``ip -j addr`` prints on a machine with a wire, a radio, a tunnel and
# an empty bridge; the fields the reader ignores are left as iproute2 prints
# them.
IP_ADDR_SAMPLE = [
    {
        "ifindex": 1,
        "ifname": "lo",
        "flags": ["LOOPBACK", "UP", "LOWER_UP"],
        "link_type": "loopback",
        "address": "00:00:00:00:00:00",
        "addr_info": [
            {"family": "inet", "local": "127.0.0.1", "prefixlen": 8, "scope": "host"},
            {"family": "inet6", "local": "::1", "prefixlen": 128, "scope": "host"},
        ],
    },
    {
        "ifindex": 2,
        "ifname": "eth0",
        "flags": ["BROADCAST", "MULTICAST", "UP", "LOWER_UP"],
        "link_type": "ether",
        "address": "02:00:00:00:00:01",
        "addr_info": [
            {
                "family": "inet",
                "local": "192.0.2.10",
                "prefixlen": 24,
                "scope": "global",
                "label": "eth0",
            },
            {
                "family": "inet6",
                "local": "fe80::ff:fe00:1",
                "prefixlen": 64,
                "scope": "link",
            },
        ],
    },
    {
        "ifindex": 3,
        "ifname": "wlan0",
        "flags": ["BROADCAST", "MULTICAST", "UP", "LOWER_UP"],
        "link_type": "ether",
        "address": "02:00:00:00:00:02",
        "addr_info": [
            {"family": "inet", "local": "10.0.0.5", "prefixlen": 24, "scope": "global"}
        ],
    },
    {
        "ifindex": 4,
        "ifname": "tun0",
        "flags": ["POINTOPOINT", "MULTICAST", "NOARP", "UP", "LOWER_UP"],
        "link_type": "none",
        "addr_info": [
            {"family": "inet", "local": "10.8.0.2", "prefixlen": 24, "scope": "global"}
        ],
    },
    {
        "ifindex": 5,
        "ifname": "br0",
        "flags": ["BROADCAST", "MULTICAST"],
        "link_type": "ether",
        "address": "00:00:00:00:00:00",
        "addr_info": [],
    },
]


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
    assert commands[-1] == ["systemctl", "reboot", "--force"]
    platform.power("poweroff")
    assert commands[-1] == ["systemctl", "poweroff", "--force"]
    platform.start_agent_service()
    assert commands[-1] == ["systemctl", "enable", "--now", AGENT_SERVICE_NAME]

    def refuse(command, **kwargs):
        raise OSError("no systemctl")

    monkeypatch.setattr(linux_module.subprocess, "run", refuse)
    assert platform.read_agent_service_state() == "unknown"


def test_linux_interfaces_come_from_iproute2_without_loopback(monkeypatch):
    recorded = {}

    def record(command, **kwargs):
        recorded["command"] = list(command)
        return subprocess.CompletedProcess(
            command, 0, stdout=json.dumps(IP_ADDR_SAMPLE), stderr=""
        )

    monkeypatch.setattr(linux_module.subprocess, "run", record)

    assert LinuxPlatform().read_network_interfaces() == [
        {
            "name": "eth0",
            "mac": "02:00:00:00:00:01",
            "addresses": ["192.0.2.10", "fe80::ff:fe00:1"],
        },
        {"name": "wlan0", "mac": "02:00:00:00:00:02", "addresses": ["10.0.0.5"]},
        {"name": "tun0", "mac": "", "addresses": ["10.8.0.2"]},
        {"name": "br0", "mac": "", "addresses": []},
    ]
    assert recorded["command"] == ["ip", "-j", "addr"]


@pytest.mark.parametrize(
    "outcome",
    [
        OSError("no ip"),
        subprocess.TimeoutExpired(["ip"], 10),
        (1, ""),
        (0, None),
        (0, "Cannot open netlink socket"),
        (0, "{}"),
    ],
)
def test_linux_interfaces_are_empty_when_iproute2_cannot_answer(monkeypatch, outcome):
    def answer(command, **kwargs):
        if isinstance(outcome, Exception):
            raise outcome
        returncode, stdout = outcome
        return subprocess.CompletedProcess(
            command, returncode, stdout=stdout, stderr=""
        )

    monkeypatch.setattr(linux_module.subprocess, "run", answer)

    assert LinuxPlatform().read_network_interfaces() == []


def test_linux_machine_id_is_the_first_file_that_holds_one(monkeypatch, tmp_path):
    missing = tmp_path / "etc-machine-id"
    dbus = tmp_path / "dbus-machine-id"
    dbus.write_text("0123456789abcdef0123456789abcdef\n")
    monkeypatch.setattr(
        linux_module, "LINUX_MACHINE_ID_PATHS", (str(missing), str(dbus))
    )

    assert LinuxPlatform().read_machine_id() == "0123456789abcdef0123456789abcdef"


def test_linux_machine_id_is_empty_when_no_file_holds_one(monkeypatch, tmp_path):
    empty = tmp_path / "machine-id"
    empty.write_text("\n")
    monkeypatch.setattr(
        linux_module, "LINUX_MACHINE_ID_PATHS", (str(tmp_path / "gone"), str(empty))
    )

    assert LinuxPlatform().read_machine_id() == ""
