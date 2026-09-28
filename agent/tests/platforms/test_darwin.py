"""The macOS platform: dscl, launchctl, host_statistics, vm_stat, ifconfig, ioreg.

Nothing here needs a Mac: every command is faked at ``subprocess.run`` by
its argument vector, libSystem is a fake that fills the tick counters, and
the account database is a fake ``pwd``. What is pinned is what each source
is turned into.
"""

import collections
import subprocess

import pytest

import neutrino_agent.platforms.darwin as darwin_module
from neutrino_agent.platforms.darwin import (
    DarwinHostMetricsReader,
    DarwinPlatform,
    parse_ifconfig,
)

PwdEntry = collections.namedtuple("PwdEntry", "pw_name pw_dir")


def completed(stdout="", returncode=0):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr="")


def answering(monkeypatch, replies: dict, calls: "list | None" = None):
    """Fake subprocess.run: each argument vector's first two words to a reply."""

    def run(command, **kwargs):
        if calls is not None:
            calls.append(list(command))
        reply = replies.get(tuple(command[:2]))
        if reply is None:
            raise FileNotFoundError(command[0])
        return reply

    monkeypatch.setattr(darwin_module.subprocess, "run", run)


class FakePwd:
    def __init__(self, homes: dict):
        self._homes = homes

    def getpwnam(self, name):
        if name not in self._homes:
            raise KeyError(name)
        return PwdEntry(name, self._homes[name])


DSCL_SAMPLE = """_mbsetupuser             248
_www                     70
daemon                   1
nobody                   -2
root                     0
pat                      501
sam                      502
guest                    201
ghost                    503
"""


def test_the_people_are_uid_501_up_with_a_home_under_users(monkeypatch, tmp_path):
    answering(monkeypatch, {("dscl", "."): completed(DSCL_SAMPLE)})
    homes = {"pat": "/Users/pat", "sam": "/Users/sam", "ghost": "/var/empty"}
    monkeypatch.setattr(darwin_module, "pwd", FakePwd(homes))
    monkeypatch.setattr(darwin_module.os.path, "isdir", lambda path: True)

    assert DarwinPlatform().human_accounts() == ["pat", "sam"]


def test_an_account_home_comes_from_the_account_database(monkeypatch):
    monkeypatch.setattr(darwin_module, "pwd", FakePwd({"pat": "/Users/pat"}))

    assert DarwinPlatform().account_home("pat") == "/Users/pat"
    with pytest.raises(KeyError):
        DarwinPlatform().account_home("nobody-here")


LAUNCHCTL_PRINT = """system/com.neutrino.agent = {
	active count = 1
	path = /Library/LaunchDaemons/com.neutrino.agent.plist
	state = running
	program = /usr/local/bin/nagent
}
"""


def test_the_service_state_is_what_launchctl_prints(monkeypatch):
    calls = []
    answering(monkeypatch, {("launchctl", "print"): completed(LAUNCHCTL_PRINT)}, calls)

    assert DarwinPlatform().read_agent_service_state() == "running"
    assert calls == [["launchctl", "print", "system/com.neutrino.agent"]]


def test_a_job_launchd_does_not_hold_is_stopped(monkeypatch):
    answering(monkeypatch, {("launchctl", "print"): completed("", returncode=113)})

    assert DarwinPlatform().read_agent_service_state() == "stopped"


def test_starting_the_service_bootstraps_and_kicks_the_job(monkeypatch):
    calls = []
    answering(
        monkeypatch,
        {
            ("launchctl", "bootstrap"): completed(""),
            ("launchctl", "kickstart"): completed(""),
        },
        calls,
    )

    DarwinPlatform().start_agent_service()

    assert calls == [
        [
            "launchctl",
            "bootstrap",
            "system",
            "/Library/LaunchDaemons/com.neutrino.agent.plist",
        ],
        ["launchctl", "kickstart", "system/com.neutrino.agent"],
    ]
    assert "launchctl bootstrap" in DarwinPlatform().agent_service_start_hint()


@pytest.mark.parametrize(
    "action, command",
    [("reboot", ["shutdown", "-r", "now"]), ("poweroff", ["shutdown", "-h", "now"])],
)
def test_power_runs_shutdown_now(monkeypatch, action, command):
    calls = []
    answering(monkeypatch, {tuple(command[:2]): completed("")}, calls)

    assert DarwinPlatform().power(action) == (0, "")
    assert calls == [command]


class FakeLibSystem:
    """host_statistics filling user, system, idle and nice ticks."""

    def __init__(self, samples):
        self.samples = list(samples)

    def mach_host_self(self):
        return 7

    def host_statistics(self, host, flavor, info, count):
        assert (host, flavor) == (7, 3)
        for index, value in enumerate(self.samples.pop(0)):
            info._obj[index] = value
        return 0


VM_STAT_SAMPLE = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                               100000.
Pages active:                             300000.
Pages inactive:                           150000.
Pages speculative:                         50000.
Pages throttled:                               0.
Pages wired down:                         200000.
"Translation faults":                  123456789.
"""


def test_the_metrics_come_from_mach_vm_stat_and_sysctl(monkeypatch):
    total = 16 * 1024**3

    def run(command, **kwargs):
        if command == ["sysctl", "-n", "hw.memsize"]:
            return completed(f"{total}\n")
        if command == ["sysctl", "-n", "kern.boottime"]:
            return completed("{ sec = 1000, usec = 5 } Thu Jan  1 00:16:40 1970\n")
        if command == ["vm_stat"]:
            return completed(VM_STAT_SAMPLE)
        raise FileNotFoundError(command[0])

    monkeypatch.setattr(darwin_module.subprocess, "run", run)
    monkeypatch.setattr(darwin_module.time, "time", lambda: 4600.0)
    monkeypatch.setattr(darwin_module.os, "getloadavg", lambda: (1.5, 1.0, 0.5))
    usage = type("Usage", (), {"total": 400, "used": 100, "free": 300})()
    monkeypatch.setattr(darwin_module.shutil, "disk_usage", lambda path: usage)
    libsystem = FakeLibSystem([(10, 10, 80, 0), (40, 20, 130, 10)])
    reader = DarwinHostMetricsReader(libsystem=libsystem)

    first = reader.read()
    second = reader.read()

    assert first.cpu_percent == 0.0
    # busy moved 70-20 = 50 of 200-100 = 100 ticks.
    assert second.cpu_percent == pytest.approx(50.0)
    available = (100000 + 150000 + 50000) * 16384
    assert second.memory_percent == pytest.approx(100.0 * (total - available) / total)
    assert second.uptime_s == 3600
    assert second.disk_percent == pytest.approx(25.0)
    assert second.load_average == [1.5, 1.0, 0.5]


def test_unreadable_sources_read_as_the_defaults(monkeypatch):
    answering(monkeypatch, {})

    class Refusing:
        def mach_host_self(self):
            return 7

        def host_statistics(self, *args):
            return 5

    metrics = DarwinHostMetricsReader(libsystem=Refusing()).read()

    assert (metrics.cpu_percent, metrics.memory_percent, metrics.uptime_s) == (
        0.0,
        0.0,
        0,
    )


IFCONFIG_SAMPLE = """lo0: flags=8049<UP,LOOPBACK,RUNNING,MULTICAST> mtu 16384
	options=1203<RXCSUM,TXCSUM,TXSTATUS,SW_TIMESTAMP>
	inet 127.0.0.1 netmask 0xff000000
	inet6 ::1 prefixlen 128
	inet6 fe80::1%lo0 prefixlen 64 scopeid 0x1
en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
	options=6460<TSO4,TSO6,CHANNEL_IO,PARTIAL_CSUM,ZEROINVERT_CSUM>
	ether 02:00:00:00:00:0A
	inet6 fe80::10%en0 prefixlen 64 secured scopeid 0xb
	inet 192.0.2.20 netmask 0xffffff00 broadcast 192.0.2.255
	status: active
utun3: flags=8051<UP,POINTOPOINT,RUNNING,MULTICAST> mtu 1380
	inet 10.8.0.3 --> 10.8.0.3 netmask 0xffffff00
"""


def test_ifconfig_is_read_into_interfaces_without_loopback(monkeypatch):
    assert parse_ifconfig(IFCONFIG_SAMPLE) == [
        {
            "name": "en0",
            "mac": "02:00:00:00:00:0a",
            "addresses": ["fe80::10", "192.0.2.20"],
        },
        {"name": "utun3", "mac": "", "addresses": ["10.8.0.3"]},
    ]
    answering(monkeypatch, {("ifconfig", "-a"): completed(IFCONFIG_SAMPLE)})
    assert [entry["name"] for entry in DarwinPlatform().read_network_interfaces()] == [
        "en0",
        "utun3",
    ]


IOREG_SAMPLE = """+-o J316sAP  <class IOPlatformExpertDevice, id 0x100000224>
    {
      "IOPlatformSerialNumber" = "C02XXXXXXXXX"
      "IOPlatformUUID" = "00000000-0000-1000-8000-000000000002"
    }
"""


def test_the_machine_id_is_the_platform_uuid(monkeypatch):
    calls = []
    answering(monkeypatch, {("ioreg", "-rd1"): completed(IOREG_SAMPLE)}, calls)

    assert DarwinPlatform().read_machine_id() == "00000000-0000-1000-8000-000000000002"
    assert calls == [["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"]]


def test_no_platform_uuid_is_no_machine_id(monkeypatch):
    answering(monkeypatch, {})

    assert DarwinPlatform().read_machine_id() == ""


def test_the_roots_and_the_socket_are_the_macs_own():
    platform = DarwinPlatform()

    assert platform.agent_data_dir() == "/Library/Application Support/Neutrino/agent"
    assert platform.agent_var_dir() == platform.agent_data_dir()
    assert platform.control_socket_path() == "/var/run/neutrino_agent/agent.sock"
