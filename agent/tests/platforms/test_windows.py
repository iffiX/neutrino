"""The Windows platform: kernel32 metrics, PowerShell interfaces, sc, winreg.

Nothing here needs Windows: kernel32 and shell32 are fakes that fill the
structures they are handed, PowerShell and ``sc`` are faked at
``subprocess.run``, and the registry is a fake ``winreg``. What is pinned is
what each source is turned into.
"""

import json
import subprocess

import pytest

import neutrino_agent.platforms.windows as windows_module
from neutrino_agent.platforms.windows import WindowsHostMetricsReader, WindowsPlatform


class FakeKernel32:
    """GetSystemTimes, GlobalMemoryStatusEx and GetTickCount64, scripted."""

    def __init__(self):
        self.times = [(0, 0, 0)]
        self.memory = (8 * 1024**3, 2 * 1024**3)
        self.ticks_ms = 90_061_000
        self.is_failing = False

    def GetSystemTimes(self, idle, kernel, user):
        if self.is_failing:
            return 0
        values = self.times.pop(0) if len(self.times) > 1 else self.times[0]
        for reference, value in zip((idle, kernel, user), values):
            reference._obj.dwLowDateTime = value & 0xFFFFFFFF
            reference._obj.dwHighDateTime = value >> 32
        return 1

    def GlobalMemoryStatusEx(self, reference):
        if self.is_failing:
            return 0
        assert reference._obj.dwLength == 64
        reference._obj.ullTotalPhys, reference._obj.ullAvailPhys = self.memory
        return 1

    def GetTickCount64(self):
        return self.ticks_ms


class FakeShell32:
    def __init__(self, answer):
        self.answer = answer

    def IsUserAnAdmin(self):
        return self.answer


class FakeKey:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeWinreg:
    """The registry, holding one value or none."""

    HKEY_LOCAL_MACHINE = "HKLM"
    KEY_READ = 0x20019

    def __init__(self, value=None):
        self.value = value
        self.opened = []

    def OpenKey(self, root, path, reserved, access):
        self.opened.append((root, path, access))
        if self.value is None:
            raise FileNotFoundError(path)
        return FakeKey()

    def QueryValueEx(self, key, name):
        return self.value, 1


def completed(stdout="", returncode=0):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr="")


def test_the_first_cpu_sample_is_zero_and_the_next_is_the_share_busy():
    kernel32 = FakeKernel32()
    # idle, kernel (idle included), user
    kernel32.times = [(100, 300, 100), (400, 800, 200)]
    reader = WindowsHostMetricsReader(kernel32=kernel32)

    assert reader.read().cpu_percent == 0.0
    # busy moved (800+200-400) - (300+100-100) = 300 of 600 total.
    assert reader.read().cpu_percent == pytest.approx(50.0)


def test_memory_uptime_and_disk_are_read_and_nothing_else_is_claimed(monkeypatch):
    usage = type("Usage", (), {"total": 200, "used": 50, "free": 150})()
    seen = []

    def disk_usage(path):
        seen.append(path)
        return usage

    monkeypatch.setattr(windows_module.shutil, "disk_usage", disk_usage)
    monkeypatch.setenv("SystemDrive", "D:")

    metrics = WindowsHostMetricsReader(kernel32=FakeKernel32()).read()

    assert metrics.memory_percent == pytest.approx(75.0)
    assert metrics.uptime_s == 90_061
    assert metrics.disk_percent == pytest.approx(25.0)
    assert seen == ["D:\\"]
    assert metrics.load_average == []
    assert metrics.processes == []
    assert metrics.temperature_c is None


def test_a_refusing_kernel32_reads_as_the_defaults(monkeypatch):
    kernel32 = FakeKernel32()
    kernel32.is_failing = True

    def disk_usage(path):
        raise OSError(path)

    monkeypatch.setattr(windows_module.shutil, "disk_usage", disk_usage)

    metrics = WindowsHostMetricsReader(kernel32=kernel32).read()

    assert (metrics.cpu_percent, metrics.memory_percent, metrics.disk_percent) == (
        0.0,
        0.0,
        0.0,
    )


# What the PowerShell call prints on a machine with a wire, a radio with
# no address, and a VPN adapter with no MAC; the loopback pseudo interface
# holds addresses and no adapter.
POWERSHELL_SAMPLE = {
    "adapters": [
        {"Name": "Ethernet", "ifIndex": 12, "MacAddress": "02-00-00-00-00-01"},
        {"Name": "Wi-Fi", "ifIndex": 14, "MacAddress": "02-00-00-00-00-02"},
        {"Name": "WireGuard", "ifIndex": 20, "MacAddress": ""},
    ],
    "addresses": [
        {"InterfaceIndex": 1, "IPAddress": "127.0.0.1"},
        {"InterfaceIndex": 1, "IPAddress": "::1"},
        {"InterfaceIndex": 12, "IPAddress": "fe80::1%12"},
        {"InterfaceIndex": 12, "IPAddress": "192.0.2.10"},
        {"InterfaceIndex": 20, "IPAddress": "10.8.0.2"},
    ],
}


def test_the_interfaces_join_adapters_to_their_addresses(monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return completed(json.dumps(POWERSHELL_SAMPLE))

    monkeypatch.setattr(windows_module.subprocess, "run", run)

    interfaces = WindowsPlatform().read_network_interfaces()

    assert interfaces == [
        {
            "name": "Ethernet",
            "mac": "02:00:00:00:00:01",
            "addresses": ["fe80::1", "192.0.2.10"],
        },
        {"name": "Wi-Fi", "mac": "02:00:00:00:00:02", "addresses": []},
        {"name": "WireGuard", "mac": "", "addresses": ["10.8.0.2"]},
    ]
    assert calls[0][0] == "powershell.exe"
    assert "Get-NetAdapter" in calls[0][-1] and "Get-NetIPAddress" in calls[0][-1]


def test_one_adapter_printed_bare_is_still_read(monkeypatch):
    sample = {
        "adapters": {
            "Name": "Ethernet",
            "ifIndex": 3,
            "MacAddress": "02-00-00-00-00-03",
        },
        "addresses": {"InterfaceIndex": 3, "IPAddress": "192.0.2.3"},
    }
    monkeypatch.setattr(
        windows_module.subprocess, "run", lambda *a, **k: completed(json.dumps(sample))
    )

    assert WindowsPlatform().read_network_interfaces() == [
        {"name": "Ethernet", "mac": "02:00:00:00:00:03", "addresses": ["192.0.2.3"]}
    ]


def test_the_interfaces_are_read_once_per_thirty_seconds(monkeypatch):
    calls = []
    now = [100.0]

    def run(command, **kwargs):
        calls.append(command)
        return completed(json.dumps(POWERSHELL_SAMPLE))

    monkeypatch.setattr(windows_module.subprocess, "run", run)
    monkeypatch.setattr(windows_module.time, "monotonic", lambda: now[0])
    platform = WindowsPlatform()

    platform.read_network_interfaces()
    now[0] += 29
    platform.read_network_interfaces()
    assert len(calls) == 1
    now[0] += 2
    platform.read_network_interfaces()
    assert len(calls) == 2


@pytest.mark.parametrize(
    "outcome",
    [
        completed("", returncode=1),
        completed("not json"),
        completed("[]"),
    ],
)
def test_a_powershell_that_fails_reads_as_no_interfaces(monkeypatch, outcome):
    monkeypatch.setattr(windows_module.subprocess, "run", lambda *a, **k: outcome)

    assert WindowsPlatform().read_network_interfaces() == []


def test_a_missing_powershell_reads_as_no_interfaces(monkeypatch):
    def run(*args, **kwargs):
        raise FileNotFoundError("powershell.exe")

    monkeypatch.setattr(windows_module.subprocess, "run", run)

    assert WindowsPlatform().read_network_interfaces() == []


SC_QUERY_RUNNING = """
SERVICE_NAME: neutrino_agent
        TYPE               : 10  WIN32_OWN_PROCESS
        STATE              : 4  RUNNING
                                (STOPPABLE, NOT_PAUSABLE, ACCEPTS_SHUTDOWN)
        WIN32_EXIT_CODE    : 0  (0x0)
"""


@pytest.mark.parametrize(
    "printed, state",
    [
        (SC_QUERY_RUNNING, "running"),
        (SC_QUERY_RUNNING.replace("4  RUNNING", "1  STOPPED"), "stopped"),
        (SC_QUERY_RUNNING.replace("4  RUNNING", "2  START_PENDING"), "start_pending"),
        ("[SC] EnumQueryServicesStatus:OpenService FAILED 1060", "unknown"),
    ],
)
def test_the_service_state_is_read_off_sc_query(monkeypatch, printed, state):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return completed(printed)

    monkeypatch.setattr(windows_module.subprocess, "run", run)

    assert WindowsPlatform().read_agent_service_state() == state
    assert calls == [["sc", "query", "neutrino_agent"]]


def test_the_start_hint_names_the_service_control_manager():
    assert WindowsPlatform().agent_service_start_hint() == "sc start neutrino_agent"


def test_the_file_share_drives_windows_own_smb_server():
    from neutrino_agent.modules.samba.windows_applier import SambaWindowsApplier

    assert "smb_server" in WindowsPlatform.capabilities
    assert isinstance(WindowsPlatform().smb_server_applier(), SambaWindowsApplier)


@pytest.mark.parametrize(
    "action, command",
    [
        ("reboot", ["shutdown", "/r", "/t", "0"]),
        ("poweroff", ["shutdown", "/s", "/t", "0"]),
    ],
)
def test_power_runs_shutdown_at_once(monkeypatch, action, command):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return completed("")

    monkeypatch.setattr(windows_module.subprocess, "run", run)

    assert WindowsPlatform().power(action) == (0, "")
    assert calls == [command]


def test_the_machine_id_is_the_registrys_machine_guid(monkeypatch):
    registry = FakeWinreg("  4c4c4544-0000-1000-8000-000000000001  ")
    monkeypatch.setattr(windows_module, "winreg", registry)

    assert WindowsPlatform().read_machine_id() == "4c4c4544-0000-1000-8000-000000000001"
    root, path, access = registry.opened[0]
    assert (root, path) == ("HKLM", "SOFTWARE\\Microsoft\\Cryptography")
    assert access & 0x0100


def test_an_unreadable_registry_is_no_machine_id(monkeypatch):
    monkeypatch.setattr(windows_module, "winreg", FakeWinreg(None))
    assert WindowsPlatform().read_machine_id() == ""

    monkeypatch.setattr(windows_module, "winreg", None)
    assert WindowsPlatform().read_machine_id() == ""


def test_the_data_root_is_under_program_data(monkeypatch):
    monkeypatch.setenv("ProgramData", "E:\\Data")
    platform = WindowsPlatform()

    assert platform.agent_data_dir() == "E:\\Data\\Neutrino\\agent"
    assert platform.agent_var_dir() == "E:\\Data\\Neutrino\\agent"

    monkeypatch.delenv("ProgramData")
    assert platform.agent_data_dir() == "C:\\ProgramData\\Neutrino\\agent"


def test_the_control_channel_is_the_agents_named_pipe():
    assert WindowsPlatform().control_socket_path() == "\\\\.\\pipe\\neutrino_agent"


@pytest.mark.parametrize("answer, is_elevated", [(1, True), (0, False)])
def test_elevation_is_what_is_user_an_admin_says(answer, is_elevated):
    assert WindowsPlatform(shell32=FakeShell32(answer)).is_elevated() is is_elevated
