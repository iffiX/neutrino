"""The macOS platform: dscl, launchctl, Mach, vm_stat, ps, ioreg, powermetrics.

Nothing here needs a Mac: every command is faked at ``subprocess.run`` by
its argument vector, libSystem is a fake that fills the tick counters, and
the account database is a fake ``pwd``. What is pinned is what each source
is turned into.
"""

import collections
import ctypes
import subprocess

import pytest

import neutrino_agent.platforms.darwin as darwin_module
from neutrino_agent.constants import AGENT_PROCESS_TOP_COUNT
from neutrino_agent.platforms.darwin import (
    DarwinHostMetricsReader,
    DarwinPlatform,
    parse_ifconfig,
    parse_ioreg_gpus,
    parse_ps,
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


def test_the_file_share_drives_the_mac_s_own_smb_server(tmp_path):
    from neutrino_agent.modules.samba.darwin_applier import SambaDarwinApplier

    applier = DarwinPlatform().smb_server_applier()

    assert "smb_server" in DarwinPlatform.capabilities
    assert isinstance(applier, SambaDarwinApplier)
    assert applier._rules_path == (
        "/Library/Application Support/Neutrino/agent/state/samba_pf.conf"
    )


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


PS_SAMPLE = """  PID USER              %CPU %MEM COMM
    1 root               0.0  0.1 /sbin/launchd
  301 _windowserver     12.5  1.4 /System/Library/PrivateFrameworks/SkyLight.framework/Resources/WindowServer
  842 pat               30.1  4.2 /Applications/Google Chrome.app/Contents/MacOS/Google Chrome
    0 root               5.0  0.9 kernel_task
"""

IOREG_APPLE_SAMPLE = """+-o AGXAcceleratorG13X  <class AGXAcceleratorG13X, id 0x1000008b1, registered, matched, active, busy 0 (0 ms), retain 51>
    {
      "IOClass" = "AGXAcceleratorG13X"
      "model" = "Apple M1"
      "gpu-core-count" = 8
      "PerformanceStatistics" = {"In use system memory (driver)"=0,"Alloc system memory"=1610612736,"Tiler Utilization %"=3,"Renderer Utilization %"=5,"Device Utilization %"=6,"In use system memory"=268435456}
    }
"""

IOREG_INTEL_MAC_SAMPLE = """+-o AMDRadeonX6000_AMDNavi14GraphicsAccelerator  <class AMDRadeonX6000_AMDNavi14GraphicsAccelerator, id 0x100000488, registered, matched, active, busy 0 (0 ms), retain 30>
    {
      "IOClass" = "AMDRadeonX6000_AMDNavi14GraphicsAccelerator"
      "PerformanceStatistics" = {"vramFreeBytes"=3221225472,"Device Utilization %"=17,"vramUsedBytes"=1073741824,"GPU Activity(%)"=17}
    }
+-o IntelAccelerator  <class IntelAccelerator, id 0x100000492, registered, matched, active, busy 0 (0 ms), retain 24>
    {
      "IOClass" = "IntelAccelerator"
      "PerformanceStatistics" = {"Device Utilization %"=2,"inUseVidMemoryBytes"=0}
    }
"""

POWERMETRICS_INTEL_SAMPLE = """Machine model: MacBookPro16,1
OS version: 21G115

*** Sampled system activity (Mon Oct  3 10:00:00 2026 +0000) (1.02ms elapsed) ***

**** SMC sensors ****

CPU Thermal level: 0
GPU Thermal level: 0
IO Thermal level: 0
Fan: 1823.55 rpm
CPU die temperature: 52.31 C
GPU die temperature: 48.00 C
"""


def fixed_time():
    return 4600.0


def fixed_load():
    return (1.5, 1.0, 0.5)


def quarter_used(path):
    return type("Usage", (), {"total": 400, "used": 100, "free": 300})()


def task_port(libsystem):
    return 259


class FakeProcessorInfo(FakeLibSystem):
    """host_statistics, and host_processor_info handing out each core's
    ticks in an array the caller must give back."""

    def __init__(self, samples, core_samples):
        super().__init__(samples)
        self.core_samples = list(core_samples)
        self.deallocated = []
        self._held = []

    def host_processor_info(self, host, flavor, count, info, info_count):
        assert (host, flavor) == (7, 2)
        cores = self.core_samples.pop(0)
        array = (ctypes.c_uint * (4 * len(cores)))(*[t for core in cores for t in core])
        self._held.append(array)
        count._obj.value = len(cores)
        info._obj.value = ctypes.addressof(array)
        info_count._obj.value = 4 * len(cores)
        return 0

    def vm_deallocate(self, task, address, size):
        self.deallocated.append((task.value, address.value, size.value))
        return 0


def test_ps_is_read_into_the_busiest_processes():
    processes = parse_ps(PS_SAMPLE)

    assert [process.to_dict() for process in processes] == [
        {
            "pid": 842,
            "user": "pat",
            "name": "Google Chrome",
            "cpu_percent": 30.1,
            "memory_percent": 4.2,
        },
        {
            "pid": 301,
            "user": "_windowserver",
            "name": "WindowServer",
            "cpu_percent": 12.5,
            "memory_percent": 1.4,
        },
        {
            "pid": 0,
            "user": "root",
            "name": "kernel_task",
            "cpu_percent": 5.0,
            "memory_percent": 0.9,
        },
        {
            "pid": 1,
            "user": "root",
            "name": "launchd",
            "cpu_percent": 0.0,
            "memory_percent": 0.1,
        },
    ]


def test_ps_lists_no_more_than_a_report_carries():
    lines = ["  PID USER %CPU %MEM COMM"]
    lines += [f"{pid} pat {pid}.0 0.1 /bin/p{pid}" for pid in range(1, 40)]

    processes = parse_ps("\n".join(lines))

    assert len(processes) == AGENT_PROCESS_TOP_COUNT
    assert processes[0].pid == 39


def test_an_apple_silicon_gpu_is_its_model_load_and_memory_in_use():
    assert [gpu.to_dict() for gpu in parse_ioreg_gpus(IOREG_APPLE_SAMPLE)] == [
        {
            "vendor": "apple",
            "name": "Apple M1",
            "utilization_percent": 6.0,
            "memory_used_mb": 256,
            "memory_total_mb": None,
            "temperature_c": None,
            "power_w": None,
        }
    ]


def test_an_intel_mac_s_gpus_are_named_by_their_driver():
    gpus = parse_ioreg_gpus(IOREG_INTEL_MAC_SAMPLE)

    assert [
        (gpu.vendor, gpu.utilization_percent, gpu.memory_used_mb, gpu.memory_total_mb)
        for gpu in gpus
    ] == [("amd", 17.0, 1024, 4096), ("intel", 2.0, 0, None)]
    assert gpus[0].name == "AMDRadeonX6000_AMDNavi14GraphicsAccelerator"


def test_a_mac_without_an_accelerator_has_no_gpus():
    assert parse_ioreg_gpus("") == []


def test_every_mac_field_is_filled_from_its_tool(monkeypatch):
    total = 16 * 1024**3
    replies = {
        ("sysctl", "-n", "hw.memsize"): completed(f"{total}\n"),
        ("sysctl", "-n", "kern.boottime"): completed("{ sec = 1000, usec = 5 }\n"),
        ("vm_stat",): completed(VM_STAT_SAMPLE),
        darwin_module.DARWIN_PS_COMMAND: completed(PS_SAMPLE),
        darwin_module.DARWIN_IOREG_GPU_COMMAND: completed(IOREG_APPLE_SAMPLE),
        darwin_module.DARWIN_POWERMETRICS_COMMAND: completed(POWERMETRICS_INTEL_SAMPLE),
    }
    calls = []

    def run(command, **kwargs):
        calls.append(tuple(command))
        return replies[tuple(command)]

    monkeypatch.setattr(darwin_module.subprocess, "run", run)
    monkeypatch.setattr(darwin_module.time, "time", fixed_time)
    monkeypatch.setattr(darwin_module.os, "getloadavg", fixed_load)
    monkeypatch.setattr(darwin_module.shutil, "disk_usage", quarter_used)
    monkeypatch.setattr(darwin_module, "_mach_task_self", task_port)
    libsystem = FakeProcessorInfo(
        [(10, 10, 80, 0), (40, 20, 130, 10)],
        [[(10, 10, 80, 0), (0, 0, 100, 0)], [(60, 10, 130, 0), (0, 0, 200, 0)]],
    )
    reader = DarwinHostMetricsReader(libsystem=libsystem)

    reader.read()
    metrics = reader.read().to_dict()

    # Core 0 moved busy 50 of 100 ticks, core 1 none of 100.
    assert metrics["cpu_core_percents"] == [50.0, 0.0]
    assert metrics["temperature_c"] == 52.3
    assert metrics["load_average"] == [1.5, 1.0, 0.5]
    assert [gpu["name"] for gpu in metrics["gpus"]] == ["Apple M1"]
    assert [process["pid"] for process in metrics["processes"]] == [842, 301, 0, 1]
    assert all(metrics[key] for key in ("cpu_percent", "memory_percent", "uptime_s"))
    # Each array the kernel handed out is given back whole.
    assert [entry[0] for entry in libsystem.deallocated] == [259, 259]
    assert [entry[2] for entry in libsystem.deallocated] == [32, 32]
    # The temperature is read once per thirty seconds.
    assert calls.count(darwin_module.DARWIN_POWERMETRICS_COMMAND) == 1


def test_apple_silicon_has_no_die_temperature_to_report(monkeypatch):
    answering(monkeypatch, {("powermetrics", "--samplers"): completed("", 1)})

    metrics = DarwinHostMetricsReader(libsystem=FakeLibSystem([(0, 0, 1, 0)])).read()

    assert metrics.temperature_c is None
    assert metrics.gpus == []
    assert metrics.processes == []
    assert metrics.cpu_core_percents == []


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

    assert platform.agent_data_dir() == (
        "/Library/Application Support/Neutrino/agent/config"
    )
    assert platform.agent_var_dir() == (
        "/Library/Application Support/Neutrino/agent/state"
    )
    assert "hub_packages" in DarwinPlatform.capabilities
    assert platform.control_socket_path() == "/var/run/neutrino/agent/agent.sock"
    assert platform.agent_log_path() == "/Library/Logs/Neutrino/agent/agent.log"


def test_darwin_removal_takes_the_modules_jobs_and_empties_the_fence(
    monkeypatch, tmp_path
):
    """Every module's LaunchDaemon, code-server's included, goes; the agent's
    own job, the hub's, the client's and RustDesk's stay. The fence's anchors
    are emptied and its rules file deleted."""
    daemons = tmp_path / "LaunchDaemons"
    daemons.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    (state / "samba_pf.conf").write_text("block in proto tcp to any port 445\n")
    for label in (
        "com.neutrino.vscode.ann",
        "com.neutrino.cloudcli.ann",
        "com.neutrino.code_server.bob",
        "com.neutrino.agent",
        "com.neutrino.hub",
        "com.neutrino.client.netbird",
        "com.carriez.RustDesk_service",
    ):
        (daemons / f"{label}.plist").write_text("<plist/>")
    (daemons / "com.neutrino.vscode.notes.txt").write_text("")
    calls = []
    answering(
        monkeypatch,
        {
            ("launchctl", "bootout"): completed(),
            ("pfctl", "-a"): completed(
                "  com.apple/250.ApplicationFirewall\n  com.apple/neutrino_smb\n"
            ),
        },
        calls,
    )
    monkeypatch.setattr(darwin_module, "AGENT_LAUNCHD_DAEMON_DIR", str(daemons))
    monkeypatch.setattr(darwin_module, "AGENT_VAR_DIR_DARWIN", str(state))

    removed = DarwinPlatform().remove_added()

    assert removed == [
        "com.neutrino.cloudcli.ann",
        "com.neutrino.code_server.bob",
        "com.neutrino.vscode.ann",
        "pf anchor com.apple/neutrino_smb",
    ]
    for label in removed[:3]:
        assert ["launchctl", "bootout", f"system/{label}"] in calls
    assert ["pfctl", "-a", "com.apple/neutrino_smb", "-F", "all"] in calls
    assert [
        "pfctl",
        "-a",
        "com.apple/250.ApplicationFirewall",
        "-F",
        "all",
    ] not in calls
    assert sorted(path.name for path in daemons.iterdir()) == [
        "com.carriez.RustDesk_service.plist",
        "com.neutrino.agent.plist",
        "com.neutrino.client.netbird.plist",
        "com.neutrino.hub.plist",
        "com.neutrino.vscode.notes.txt",
    ]
    assert not (state / "samba_pf.conf").exists()


def test_darwin_removal_empties_the_fence_even_when_pfctl_lists_nothing(
    monkeypatch, tmp_path
):
    calls = []
    answering(monkeypatch, {("pfctl", "-a"): completed("")}, calls)
    monkeypatch.setattr(darwin_module, "AGENT_LAUNCHD_DAEMON_DIR", str(tmp_path / "no"))
    monkeypatch.setattr(darwin_module, "AGENT_VAR_DIR_DARWIN", str(tmp_path))

    assert DarwinPlatform().remove_added() == ["pf anchor com.apple/neutrino_smb"]
    assert ["pfctl", "-a", "com.apple/neutrino_smb", "-F", "all"] in calls


def test_darwin_removes_the_agent_itself_and_keeps_its_configuration_and_state(
    monkeypatch, tmp_path
):
    """The jobs are unloaded before their files go, the program directory is
    the last thing deleted, and nothing under config or state is named."""
    link = tmp_path / "nagent"
    link.write_text("")
    calls = []
    answering(
        monkeypatch,
        {
            ("launchctl", "bootout"): completed(),
            ("pkgutil", "--forget"): completed(),
            ("rm", "-rf"): completed(),
        },
        calls,
    )
    monkeypatch.setattr(darwin_module, "AGENT_DARWIN_LINK_PATH", str(link))

    removed = DarwinPlatform().remove_agent_program()

    assert "com.neutrino.agent" in removed
    assert [call for call in calls if call[0] == "launchctl"][:2] == [
        ["launchctl", "bootout", "system/com.carriez.RustDesk_service"],
        ["launchctl", "bootout", "system/com.neutrino.agent"],
    ]
    assert ["pkgutil", "--forget", "com.neutrino.agent"] in calls
    assert calls[-1] == [
        "rm",
        "-rf",
        "/Applications/RustDesk.app",
        "/Library/Application Support/Neutrino/agent/app",
    ]
    assert not link.exists()
    named = " ".join(" ".join(call) for call in calls)
    assert "agent/config" not in named
    assert "agent/state" not in named


AccountEntry = collections.namedtuple("AccountEntry", "pw_name pw_uid pw_gid pw_dir")


def test_a_mac_runs_as_the_account_with_its_uid_its_group_and_no_other(monkeypatch):
    monkeypatch.setattr(
        darwin_module.pwd,
        "getpwnam",
        lambda name: AccountEntry("alice", 501, 20, "/Users/alice"),
    )
    seen = {}

    def record(command, **kwargs):
        seen["command"] = list(command)
        seen.update(kwargs)
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr(darwin_module.subprocess, "run", record)

    done = DarwinPlatform().run_as_account("alice", ["id"], stdin="x")

    assert done.stdout == "ok"
    assert seen["command"] == ["id"]
    assert (seen["user"], seen["group"], seen["extra_groups"]) == (501, 20, [])
    assert seen["cwd"] == "/Users/alice"
    assert seen["env"] == {
        "HOME": "/Users/alice",
        "USER": "alice",
        "LOGNAME": "alice",
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
    }
    assert seen["input"] == "x"


def test_a_mac_answers_a_question_as_the_account_on_a_pty(monkeypatch):
    monkeypatch.setattr(
        darwin_module.pwd,
        "getpwnam",
        lambda name: AccountEntry("alice", 501, 20, "/Users/alice"),
    )
    seen = {}

    def on_pty(argv, **kwargs):
        seen["argv"] = list(argv)
        seen.update(kwargs)
        return 0, "Deleted"

    monkeypatch.setattr(darwin_module, "run_on_pty", on_pty)

    answered = DarwinPlatform().run_as_account_answering(
        "alice", ["cc-switch"], prompt="(y/N)", answer="y\n"
    )

    assert answered == (0, "Deleted")
    assert (seen["user"], seen["group"], seen["cwd"]) == (501, 20, "/Users/alice")
    assert seen["env"]["USER"] == "alice"


def test_a_mac_account_the_database_lacks_is_a_key_error(monkeypatch):
    def lacks(name):
        raise KeyError(name)

    monkeypatch.setattr(darwin_module.pwd, "getpwnam", lacks)

    with pytest.raises(KeyError):
        DarwinPlatform().run_as_account("ghost", ["id"])


def test_a_mac_starts_a_long_lived_process_with_the_accounts_identity(monkeypatch):
    monkeypatch.setattr(
        darwin_module.pwd,
        "getpwnam",
        lambda name: AccountEntry("alice", 501, 20, "/Users/alice"),
    )

    command, process = DarwinPlatform().account_process("alice", ["/bin/zsh", "-l"])

    assert command == ["/bin/zsh", "-l"]
    assert (process["user"], process["group"], process["extra_groups"]) == (
        501,
        20,
        [],
    )
    assert process["cwd"] == "/Users/alice"
    assert process["env"]["HOME"] == "/Users/alice"
