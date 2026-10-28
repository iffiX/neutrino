"""The Windows platform: native metrics, the Win32 reads, the PowerShell host, sc.

Nothing here needs Windows: kernel32, ntdll, advapi32, pdh, gdi32 and
shell32 are fakes that fill the structures they are handed, the PowerShell
host is a recording one, ``sc`` and icacls are faked at ``subprocess.run``
or as the injected runner, the iphlpapi and netapi32 reads are replaced at
their seam, and the registry is a fake ``winreg``. What is pinned is what
each source is turned into, every request the host is sent, the
one-shot tasks of one account taking turns with the account's batch logon
right held for each run, and the relays on WSL's adapter with their
firewall rules read and written through the host.
"""

import contextlib
import ctypes
import subprocess
import threading

import pytest

import neutrino_agent.core.metrics as metrics_module
import neutrino_agent.platforms.windows as windows_module
from neutrino_agent.constants import AGENT_PROCESS_TOP_COUNT
from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.shared.subprocess_run import CommandResult
from neutrino_agent.platforms import win32
from neutrino_agent.platforms.base import RelayAddress, RelayRule, is_added_name
from neutrino_agent.platforms.windows import (
    cmd_argument,
    WindowsHostMetricsReader,
    WindowsPlatform,
)
from tests.conftest import FakeBatchLogon, FakeProcessTable, RecordingHost


@pytest.fixture(autouse=True)
def _no_nvidia_smi(monkeypatch):
    """The machine running the tests has no NVIDIA tool, unless a test says."""
    monkeypatch.setattr(metrics_module.shutil, "which", lambda name: None)


class FakeKernel32:
    """GetSystemTimes, GlobalMemoryStatusEx, GetTickCount64 and process
    handles, scripted."""

    def __init__(self):
        self.times = [(0, 0, 0)]
        self.memory = (8 * 1024**3, 2 * 1024**3)
        self.ticks_ms = 90_061_000
        self.is_failing = False
        self.denied_pids = set()
        self.closed = []

    def OpenProcess(self, access, is_inherited, pid):
        assert access == win32.PROCESS_QUERY_LIMITED_INFORMATION
        return 0 if pid in self.denied_pids else 0x1000 + pid

    def CloseHandle(self, handle):
        self.closed.append(getattr(handle, "value", handle))
        return 1

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


def refusing_host():
    """A PowerShell host that cannot answer."""
    return RecordingHost({"thermal_zones": OSError("the host is not here")})


def unreadable_disk(path):
    raise OSError(path)


def test_memory_uptime_and_disk_are_read_and_a_missing_source_is_empty(monkeypatch):
    usage = type("Usage", (), {"total": 200, "used": 50, "free": 150})()
    seen = []

    def disk_usage(path):
        seen.append(path)
        return usage

    monkeypatch.setattr(windows_module.shutil, "disk_usage", disk_usage)
    monkeypatch.setenv("SystemDrive", "D:")

    metrics = WindowsHostMetricsReader(
        kernel32=FakeKernel32(), powershell=refusing_host()
    ).read()

    assert metrics.memory_percent == pytest.approx(75.0)
    assert metrics.uptime_s == 90_061
    assert metrics.disk_percent == pytest.approx(25.0)
    assert seen == ["D:\\"]
    assert metrics.load_average == []
    assert metrics.cpu_core_percents == []
    assert metrics.processes == []
    assert metrics.gpus == []
    assert metrics.temperature_c is None


def test_a_refusing_kernel32_reads_as_the_defaults(monkeypatch):
    kernel32 = FakeKernel32()
    kernel32.is_failing = True

    def disk_usage(path):
        raise OSError(path)

    monkeypatch.setattr(windows_module.shutil, "disk_usage", disk_usage)

    metrics = WindowsHostMetricsReader(
        kernel32=kernel32, powershell=refusing_host()
    ).read()

    assert (metrics.cpu_percent, metrics.memory_percent, metrics.disk_percent) == (
        0.0,
        0.0,
        0.0,
    )


def core_times(*cores):
    """One SystemProcessorPerformanceInformation buffer: (idle, kernel, user)
    per core, the kernel time holding the idle time."""
    entries = (win32.SystemProcessorPerformanceInformation * len(cores))()
    for entry, (idle, kernel, user) in zip(entries, cores):
        entry.IdleTime, entry.KernelTime, entry.UserTime = idle, kernel, user
    return entries


class ProcessTable:
    """One SystemProcessInformation buffer, each image name inside it, as
    the kernel lays the table out."""

    def __init__(self, processes):
        """
        Args:
            processes: ``(pid, image name, user+kernel time, working set)``.
        """
        entry_size = ctypes.sizeof(win32.SystemProcessInformation)
        names = [name.encode("utf-16-le") for _pid, name, _time, _ws in processes]
        strides = [(entry_size + len(name) + 7) // 8 * 8 for name in names]
        self.buffer = ctypes.create_string_buffer(sum(strides))
        self.offsets: list = []
        offset = 0
        for index, (pid, _name, times, working_set) in enumerate(processes):
            self.offsets.append(offset)
            entry = win32.SystemProcessInformation.from_buffer(self.buffer, offset)
            is_last = index == len(processes) - 1
            entry.NextEntryOffset = 0 if is_last else strides[index]
            entry.UniqueProcessId = pid
            entry.UserTime = times // 2
            entry.KernelTime = times - times // 2
            entry.WorkingSetSize = working_set
            name = names[index]
            ctypes.memmove(
                ctypes.addressof(self.buffer) + offset + entry_size, name, len(name)
            )
            entry.ImageName.Length = len(name)
            entry.ImageName.MaximumLength = len(name)
            entry.ImageName.Buffer = (
                ctypes.addressof(self.buffer) + offset + entry_size if name else None
            )
            offset += strides[index]

    def fill(self, buffer) -> None:
        """Copy the table into the caller's buffer, its names pointing inside it."""
        ctypes.memmove(buffer, self.buffer, ctypes.sizeof(self.buffer))
        shift = ctypes.addressof(buffer) - ctypes.addressof(self.buffer)
        for offset in self.offsets:
            entry = win32.SystemProcessInformation.from_buffer(buffer, offset)
            if entry.ImageName.Buffer:
                entry.ImageName.Buffer += shift


class FakeNtdll:
    """NtQuerySystemInformation answering each class from its own queue,
    the last answer repeating."""

    def __init__(self, *, cores=(), tables=()):
        self.answers = {
            win32.SYSTEM_PROCESSOR_PERFORMANCE_INFORMATION_CLASS: list(cores),
            win32.SYSTEM_PROCESS_INFORMATION_CLASS: list(tables),
        }
        self.sizes = []

    def NtQuerySystemInformation(self, info_class, buffer, size, needed):
        queue = self.answers[info_class]
        answer = queue.pop(0) if len(queue) > 1 else queue[0]
        data = answer.buffer if isinstance(answer, ProcessTable) else answer
        self.sizes.append((info_class, size))
        needed._obj.value = ctypes.sizeof(data)
        if size < ctypes.sizeof(data):
            return win32.STATUS_INFO_LENGTH_MISMATCH
        if isinstance(answer, ProcessTable):
            answer.fill(buffer)
        else:
            ctypes.memmove(buffer, data, ctypes.sizeof(data))
        return 0


class FakeAdvapi32:
    """A process token naming an account by its SID."""

    def __init__(self, accounts: dict):
        """
        Args:
            accounts: Each pid to the account its token names.
        """
        self._sids = {}
        self._names = {}
        for pid, account in accounts.items():
            sid = ctypes.create_string_buffer(f"sid-{account}".encode())
            self._sids[0x1000 + pid] = sid
            self._names[ctypes.addressof(sid)] = account
        self.lookups = []

    def OpenProcessToken(self, process, access, token):
        assert access == win32.TOKEN_QUERY
        token._obj.value = process
        return 1

    def GetTokenInformation(self, token, kind, buffer, length, size):
        assert kind == win32.TOKEN_USER_CLASS
        sid = self._sids.get(token.value)
        if sid is None:
            return 0
        if buffer is None:
            size._obj.value = ctypes.sizeof(win32.SidAndAttributes)
            return 0
        head = win32.SidAndAttributes(Sid=ctypes.addressof(sid))
        ctypes.memmove(buffer, ctypes.byref(head), ctypes.sizeof(head))
        return 1

    def GetLengthSid(self, sid):
        return len(f"sid-{self._names[sid]}")

    def LookupAccountSidW(self, system, sid, name, name_size, domain, *rest):
        self.lookups.append(sid)
        name.value = self._names[sid]
        domain.value = "NMXWIN"
        return 1


# What the GPU counters hold: two engines of one card busy, a video engine
# beside them, and the software adapter's memory.
ENGINE_ITEMS = [
    ("pid_100_luid_0x00000000_0x0000D1B2_phys_0_eng_0_engtype_3D", 30.0),
    ("pid_200_luid_0x00000000_0x0000D1B2_phys_0_eng_0_engtype_3D", 15.0),
    ("pid_100_luid_0x00000000_0x0000D1B2_phys_0_eng_3_engtype_VideoDecode", 20.0),
]
MEMORY_ITEMS = [
    ("luid_0x00000000_0x0000D1B2_phys_0", 512 * 1024 * 1024),
    ("luid_0x00000000_0x0000E000_phys_0", 64 * 1024 * 1024),
]


class FakePdh:
    """One query with two wildcard counters; the engines' rate is invalid
    until the second collection, as PDH's is."""

    ENGINE = 10
    MEMORY = 11

    def __init__(self, *, engines=ENGINE_ITEMS, memory=MEMORY_ITEMS):
        self.items = {self.ENGINE: list(engines), self.MEMORY: list(memory)}
        self.paths = []
        self.collected = 0
        self._held = []

    def PdhOpenQueryW(self, source, user_data, query):
        query._obj.value = 1
        return 0

    def PdhAddEnglishCounterW(self, query, path, user_data, counter):
        self.paths.append(path)
        counter._obj.value = self.ENGINE if "Engine" in path else self.MEMORY
        return 0

    def PdhCollectQueryData(self, query):
        self.collected += 1
        return 0

    def PdhGetFormattedCounterArrayW(self, counter, value_format, size, count, items):
        rows = self.items[counter.value]
        array = (win32.PdhFmtCounterValueItem * len(rows))()
        for item, (name, value) in zip(array, rows):
            item.szName = name
            if counter.value == self.ENGINE:
                assert value_format == win32.PDH_FMT_DOUBLE
                item.FmtValue.value.doubleValue = value
                item.FmtValue.CStatus = 0 if self.collected > 1 else 0xC0000BC6
            else:
                assert value_format == win32.PDH_FMT_LARGE
                item.FmtValue.value.largeValue = value
        self._held.append(array)
        if items is None:
            size._obj.value = ctypes.sizeof(array)
            count._obj.value = len(rows)
            return win32.PDH_MORE_DATA
        ctypes.memmove(items, array, ctypes.sizeof(array))
        return 0

    def PdhCloseQuery(self, query):
        return 0


class FakeGdi32:
    """The graphics kernel listing a card and the software renderer."""

    def __init__(self, adapters):
        """
        Args:
            adapters: ``(handle, luid low part, name, type bits, dedicated
                bytes)``.
        """
        self.adapters = adapters
        self.closed = []

    def D3DKMTEnumAdapters2(self, enumeration):
        listed = enumeration._obj
        listed.NumAdapters = len(self.adapters)
        if listed.pAdapters:
            infos = (win32.D3dkmtAdapterInfo * len(self.adapters)).from_address(
                listed.pAdapters
            )
            for info, (handle, low, _name, _bits, _memory) in zip(infos, self.adapters):
                info.hAdapter = handle
                info.AdapterLuid.LowPart = low
        return 0

    def D3DKMTQueryAdapterInfo(self, query):
        asked = query._obj
        handle, _low, name, bits, memory = next(
            adapter for adapter in self.adapters if adapter[0] == asked.hAdapter
        )
        if asked.Type == win32.KMTQAITYPE_ADAPTERTYPE:
            ctypes.c_uint32.from_address(asked.pPrivateDriverData).value = bits
        elif asked.Type == win32.KMTQAITYPE_ADAPTERREGISTRYINFO:
            assert asked.PrivateDriverDataSize == 4 * 260 * 2
            info = win32.D3dkmtAdapterRegistryInfo.from_address(
                asked.pPrivateDriverData
            )
            encoded = name.encode("utf-16-le")
            ctypes.memmove(ctypes.addressof(info.AdapterString), encoded, len(encoded))
        elif asked.Type == win32.KMTQAITYPE_GETSEGMENTSIZE:
            info = win32.D3dkmtSegmentSizeInfo.from_address(asked.pPrivateDriverData)
            info.DedicatedVideoMemorySize = memory
        else:
            return 0xC000000D
        return 0

    def D3DKMTCloseAdapter(self, close):
        self.closed.append(close._obj.hAdapter)
        return 0


GDI_ADAPTERS = [
    (1, 0xD1B2, "NVIDIA GeForce RTX 3060", 0x3, 12 * 1024**3),
    (2, 0xE000, "Microsoft Basic Render Driver", 0x5, 0),
]


def thermal_host(readings):
    """A PowerShell host answering the thermal zones in tenths of a kelvin."""
    return RecordingHost({"thermal_zones": {"readings": readings}})


def windows_reader(**overrides):
    kernel32 = FakeKernel32()
    kernel32.times = [(100, 300, 100), (400, 800, 200)]
    kernel32.denied_pids = {4}
    parts = {
        "kernel32": kernel32,
        "ntdll": FakeNtdll(
            cores=[
                core_times((100, 200, 100), (200, 300, 0)),
                core_times((150, 300, 200), (400, 500, 0)),
            ],
            tables=[
                ProcessTable(
                    [
                        (0, "", 9_000, 8192),
                        (4, "System", 1_000, 1024**2),
                        (100, "Code.exe", 0, 2 * 1024**3),
                        (200, "svchost.exe", 50, 100 * 1024**2),
                    ]
                ),
                ProcessTable(
                    [
                        (0, "", 9_400, 8192),
                        (4, "System", 1_060, 1024**2),
                        (100, "Code.exe", 150, 2 * 1024**3),
                        (200, "svchost.exe", 50, 100 * 1024**2),
                        (300, "new.exe", 30, 1024**2),
                    ]
                ),
            ],
        ),
        "advapi32": FakeAdvapi32({100: "pat", 200: "SYSTEM", 300: "pat"}),
        "pdh": FakePdh(),
        "gdi32": FakeGdi32(GDI_ADAPTERS),
        "powershell": thermal_host([3011.5, 3231.5]),
    }
    parts.update(overrides)
    return WindowsHostMetricsReader(**parts), parts


def test_every_windows_field_is_filled_from_its_native_source(monkeypatch):
    usage = type("Usage", (), {"total": 200, "used": 50, "free": 150})()
    monkeypatch.setattr(windows_module.shutil, "disk_usage", lambda path: usage)
    reader, parts = windows_reader()

    first = reader.read().to_dict()
    second = reader.read().to_dict()

    assert first["cpu_core_percents"] == [0.0, 0.0]
    assert [process["cpu_percent"] for process in first["processes"]] == [
        0.0,
        0.0,
        0.0,
    ]
    assert first["gpus"][0]["utilization_percent"] is None
    assert second == {
        "cpu_percent": 50.0,
        # Core 0 moved busy 150 of 200, core 1 none of 200.
        "cpu_core_percents": [75.0, 0.0],
        "memory_percent": 75.0,
        "disk_percent": 25.0,
        "temperature_c": 50.0,
        "uptime_s": 90_061,
        "load_average": [],
        "gpus": [
            {
                "vendor": "nvidia",
                "name": "NVIDIA GeForce RTX 3060",
                # The 3D engine's two processes, the busiest engine type.
                "utilization_percent": 45.0,
                "memory_used_mb": 512,
                "memory_total_mb": 12 * 1024,
                "temperature_c": None,
                "power_w": None,
            }
        ],
        # Shares of one core against the all-core delta of 600 on two cores;
        # the idle process is left out and the System's token is denied.
        "processes": [
            {
                "pid": 100,
                "user": "pat",
                "name": "Code.exe",
                "cpu_percent": 50.0,
                "memory_percent": 25.0,
            },
            {
                "pid": 4,
                "user": "",
                "name": "System",
                "cpu_percent": 20.0,
                "memory_percent": 0.0,
            },
            {
                "pid": 200,
                "user": "SYSTEM",
                "name": "svchost.exe",
                "cpu_percent": 0.0,
                "memory_percent": 1.2,
            },
            {
                "pid": 300,
                "user": "pat",
                "name": "new.exe",
                "cpu_percent": 0.0,
                "memory_percent": 0.0,
            },
        ],
    }
    assert parts["pdh"].paths == [
        "\\GPU Engine(*)\\Utilization Percentage",
        "\\GPU Adapter Memory(*)\\Dedicated Usage",
    ]
    assert parts["gdi32"].closed == [1, 2]
    # One account name per SID, and one thermal reading per minute.
    assert len(parts["advapi32"].lookups) == 2
    assert parts["powershell"].calls == [("thermal_zones", {})]


def test_the_process_table_lists_the_busiest_few(monkeypatch):
    monkeypatch.setattr(windows_module.shutil, "disk_usage", unreadable_disk)
    table = ProcessTable([(pid, f"p{pid}.exe", 0, pid * 1024) for pid in range(1, 40)])
    reader, _parts = windows_reader(
        ntdll=FakeNtdll(cores=[core_times()], tables=[table])
    )

    processes = reader.read().processes

    assert len(processes) == AGENT_PROCESS_TOP_COUNT
    assert [process.pid for process in processes][:3] == [39, 38, 37]


def test_a_buffer_too_small_grows_to_what_the_kernel_asks(monkeypatch):
    monkeypatch.setattr(windows_module.shutil, "disk_usage", unreadable_disk)
    many = core_times(*[(0, 0, 0)] * 65)
    ntdll = FakeNtdll(cores=[many], tables=[ProcessTable([(4, "System", 0, 0)])])
    reader, _parts = windows_reader(ntdll=ntdll)

    assert len(reader.read().cpu_core_percents) == 65
    core_sizes = [
        size
        for info_class, size in ntdll.sizes
        if info_class == win32.SYSTEM_PROCESSOR_PERFORMANCE_INFORMATION_CLASS
    ]
    assert core_sizes[0] == 64 * 48
    assert core_sizes[1] >= 65 * 48


def test_nvidia_smi_answers_for_the_cards_where_it_is_installed(monkeypatch):
    monkeypatch.setattr(windows_module.shutil, "disk_usage", unreadable_disk)
    monkeypatch.setattr(metrics_module.shutil, "which", lambda name: "nvidia-smi.exe")
    commands = []

    def run(command, **kwargs):
        commands.append(list(command))
        return completed("NVIDIA GeForce RTX 3060, 12, 2048, 12288, 41, 35.5\n")

    monkeypatch.setattr(metrics_module.subprocess, "run", run)
    reader, parts = windows_reader()

    gpus = reader.read().gpus

    assert [gpu.to_dict() for gpu in gpus] == [
        {
            "vendor": "nvidia",
            "name": "NVIDIA GeForce RTX 3060",
            "utilization_percent": 12.0,
            "memory_used_mb": 2048,
            "memory_total_mb": 12288,
            "temperature_c": 41.0,
            "power_w": 35.5,
        }
    ]
    assert commands[0][0] == "nvidia-smi"
    assert parts["pdh"].paths == []


def test_without_the_graphics_kernel_the_cards_are_the_counters_adapters(
    monkeypatch,
):
    monkeypatch.setattr(windows_module.shutil, "disk_usage", unreadable_disk)
    reader, _parts = windows_reader(gdi32=object())

    gpus = reader.read().gpus

    assert [(gpu.name, gpu.vendor, gpu.memory_used_mb) for gpu in gpus] == [
        ("", "", 512),
        ("", "", 64),
    ]


def test_missing_native_sources_read_as_empty_fields(monkeypatch):
    monkeypatch.setattr(windows_module.shutil, "disk_usage", unreadable_disk)

    class Refusing:
        def NtQuerySystemInformation(self, *args):
            return 0xC0000022

        def PdhOpenQueryW(self, *args):
            return 0xC0000BB8

    reader, _parts = windows_reader(
        ntdll=Refusing(),
        pdh=Refusing(),
        gdi32=object(),
        powershell=thermal_host([]),
    )

    metrics = reader.read()

    assert metrics.cpu_core_percents == []
    assert metrics.processes == []
    assert metrics.gpus == []
    assert metrics.temperature_c is None


def test_the_thermal_zones_are_asked_of_the_host_once_a_minute(monkeypatch):
    monkeypatch.setattr(windows_module.shutil, "disk_usage", unreadable_disk)
    now = [100.0]
    monkeypatch.setattr(windows_module.time, "monotonic", lambda: now[0])
    host = thermal_host([3011.5])
    reader, _parts = windows_reader(powershell=host)

    assert reader.read().temperature_c == pytest.approx(28.0)
    now[0] += 59
    reader.read()
    assert len(host.calls) == 1
    now[0] += 2
    reader.read()
    assert len(host.calls) == 2


def test_a_machine_whose_firmware_has_no_zone_is_asked_again_an_hour_later(
    monkeypatch,
):
    monkeypatch.setattr(windows_module.shutil, "disk_usage", unreadable_disk)
    now = [100.0]
    monkeypatch.setattr(windows_module.time, "monotonic", lambda: now[0])
    host = thermal_host([0, "not a number"])
    reader, _parts = windows_reader(powershell=host)

    assert reader.read().temperature_c is None
    now[0] += 3599
    reader.read()
    assert len(host.calls) == 1
    now[0] += 2
    reader.read()
    assert len(host.calls) == 2


def test_a_host_that_cannot_answer_is_asked_again_a_minute_later(monkeypatch):
    monkeypatch.setattr(windows_module.shutil, "disk_usage", unreadable_disk)
    now = [100.0]
    monkeypatch.setattr(windows_module.time, "monotonic", lambda: now[0])
    host = refusing_host()
    reader, _parts = windows_reader(powershell=host)

    assert reader.read().temperature_c is None
    now[0] += 61
    reader.read()
    assert len(host.calls) == 2


INTERFACES = [
    {
        "name": "Ethernet",
        "mac": "02:00:00:00:00:01",
        "addresses": ["fe80::1", "192.0.2.10"],
    },
    {"name": "WireGuard", "mac": "", "addresses": ["10.8.0.2"]},
]


def test_the_interfaces_are_iphlpapi_s_adapters_read_every_time(monkeypatch):
    seen = []

    def read_interfaces(iphlpapi):
        seen.append(iphlpapi)
        return [dict(entry) for entry in INTERFACES]

    monkeypatch.setattr(windows_module, "read_interfaces", read_interfaces)
    iphlpapi = object()
    platform = WindowsPlatform(iphlpapi=iphlpapi)

    assert platform.read_network_interfaces() == INTERFACES
    assert platform.read_network_interfaces() == INTERFACES
    assert seen == [iphlpapi, iphlpapi]


@pytest.mark.parametrize(
    "error", [OSError(87, "GetAdaptersAddresses answered 87"), ValueError("short")]
)
def test_adapters_that_cannot_be_read_are_no_interfaces(monkeypatch, error):
    def read_interfaces(iphlpapi):
        raise error

    monkeypatch.setattr(windows_module, "read_interfaces", read_interfaces)

    assert WindowsPlatform().read_network_interfaces() == []


def test_off_windows_the_adapters_cannot_be_read():
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


class Icacls:
    """icacls, recording each argument vector and exiting with a set code."""

    def __init__(self, code=0):
        self.calls: list = []
        self.code = code

    def __call__(self, argv, **_):
        self.calls.append(list(argv))
        return CommandResult(
            command=list(argv), exit_code=self.code, stdout="", stderr=""
        )


def test_a_directory_opened_to_accounts_grants_the_users_group_read_and_run():
    icacls = Icacls()

    assert "hub_packages" in WindowsPlatform.capabilities
    WindowsPlatform(run=icacls).open_to_accounts("D:\\state\\vscode")

    assert icacls.calls == [
        ["icacls.exe", "D:\\state\\vscode", "/grant", "*S-1-5-32-545:(OI)(CI)RX"]
    ]


def test_a_directory_icacls_will_not_open_is_an_os_error():
    with pytest.raises(OSError, match="icacls exited 5"):
        WindowsPlatform(run=Icacls(5)).open_to_accounts("D:\\state\\vscode")


class FakeSeat:
    """The console session, with whoever is signed in at it."""

    def __init__(self, accounts):
        self.accounts = accounts

    def graphical_accounts(self):
        return None if self.accounts is None else list(self.accounts)


def homes_of(table):
    """``account_home`` answering from a table: a path, or what to raise."""

    def account_home(account, *, advapi32=None, kernel32=None):
        found = table.get(account, KeyError(account))
        if isinstance(found, BaseException):
            raise found
        return found

    return account_home


def test_a_shell_starts_in_the_console_accounts_profile(monkeypatch, tmp_path):
    monkeypatch.setattr(
        windows_module, "account_home", homes_of({"alice": str(tmp_path)})
    )
    platform = WindowsPlatform(seat=FakeSeat(["alice"]))

    assert platform.shell_start_dir() == str(tmp_path)


@pytest.mark.parametrize(
    "accounts, homes",
    [
        ([], {}),
        (None, {}),
        (["alice"], {}),
        (["alice"], {"alice": "Z:\\no\\such\\profile"}),
        (["alice"], {"alice": OSError("the registry cannot be read")}),
    ],
    ids=["nobody", "no_session_api", "no_account", "missing_profile", "no_answer"],
)
def test_a_shell_without_a_profile_starts_at_the_system_drives_root(
    monkeypatch, accounts, homes
):
    monkeypatch.setenv("SystemDrive", "D:")
    monkeypatch.setattr(windows_module, "account_home", homes_of(homes))
    platform = WindowsPlatform(seat=FakeSeat(accounts))

    assert platform.shell_start_dir() == "D:\\"


def test_off_windows_the_shell_starts_at_the_root(monkeypatch):
    monkeypatch.delenv("SystemDrive", raising=False)

    platform = WindowsPlatform(seat=FakeSeat(["alice"]))

    assert platform.shell_start_dir() == "C:\\"


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


def test_the_roots_are_under_program_data(monkeypatch):
    monkeypatch.setenv("ProgramData", "E:\\Data")
    platform = WindowsPlatform()

    assert platform.agent_data_dir() == "E:\\Data\\Neutrino\\agent\\config"
    assert platform.agent_var_dir() == "E:\\Data\\Neutrino\\agent\\state"

    monkeypatch.delenv("ProgramData")
    assert platform.agent_data_dir() == "C:\\ProgramData\\Neutrino\\agent\\config"


def test_the_control_channel_is_the_agents_named_pipe():
    assert WindowsPlatform().control_socket_path() == "\\\\.\\pipe\\neutrino_agent"


@pytest.mark.parametrize("answer, is_elevated", [(1, True), (0, False)])
def test_elevation_is_what_is_user_an_admin_says(answer, is_elevated):
    assert WindowsPlatform(shell32=FakeShell32(answer)).is_elevated() is is_elevated


def users_reading(users):
    """``read_users`` answering a list, or raising what it is handed."""
    calls = []

    def read_users(netapi32):
        calls.append(netapi32)
        if isinstance(users, BaseException):
            raise users
        return [dict(user) for user in users]

    read_users.calls = calls
    return read_users


def user(name, description="", is_enabled=True):
    return {"name": name, "description": description, "is_enabled": is_enabled}


def test_the_accounts_are_the_enabled_people_without_the_builtin_or_share_ones(
    monkeypatch,
):
    reading = users_reading(
        [
            user("zoe"),
            user("Administrator", "Built-in account"),
            user("DefaultAccount"),
            user("WDAGUtilityAccount"),
            user("Guest"),
            user("media", "neutrino:"),
            user("old", is_enabled=False),
            user(""),
            user("hanha", "Hanha's account"),
        ]
    )
    monkeypatch.setattr(windows_module, "read_users", reading)
    netapi32 = object()

    accounts = WindowsPlatform(netapi32=netapi32).human_accounts()

    assert accounts == ["hanha", "zoe"]
    assert reading.calls == [netapi32]
    assert "accounts" in WindowsPlatform.capabilities


def test_the_accounts_are_read_every_time(monkeypatch):
    reading = users_reading([user("hanha")])
    monkeypatch.setattr(windows_module, "read_users", reading)
    platform = WindowsPlatform()

    platform.human_accounts()
    platform.human_accounts()

    assert len(reading.calls) == 2


@pytest.mark.parametrize("error", [OSError(5, "denied"), ValueError("short")])
def test_accounts_that_cannot_be_listed_are_none(monkeypatch, error):
    monkeypatch.setattr(windows_module, "read_users", users_reading(error))

    assert WindowsPlatform().human_accounts() == []


def test_off_windows_no_account_is_listed():
    assert WindowsPlatform().human_accounts() == []


def test_an_account_home_is_what_the_profile_list_names(monkeypatch):
    seen = []

    def account_home(account, *, advapi32=None, kernel32=None):
        seen.append((account, advapi32, kernel32))
        return "C:\\Users\\hanha"

    monkeypatch.setattr(windows_module, "account_home", account_home)
    advapi32, kernel32 = object(), object()

    home = WindowsPlatform(advapi32=advapi32, kernel32=kernel32).account_home("hanha")

    assert home == "C:\\Users\\hanha"
    assert seen == [("hanha", advapi32, kernel32)]


@pytest.mark.parametrize("error", [KeyError("ghost"), OSError(5, "denied")])
def test_an_account_home_keeps_its_contract(monkeypatch, error):
    monkeypatch.setattr(windows_module, "account_home", homes_of({"ghost": error}))

    with pytest.raises(type(error)):
        WindowsPlatform().account_home("ghost")


def test_a_step_runs_on_this_thread_acting_as_the_account(monkeypatch):
    acted = []

    @contextlib.contextmanager
    def impersonated(account, password, *, advapi32=None, kernel32=None):
        acted.append(("logon", account, password))
        yield
        acted.append(("revert", account))

    def step(path, text):
        acted.append(("step", path, text))
        return "done"

    monkeypatch.setattr(windows_module, "impersonated", impersonated)

    answer = WindowsPlatform().as_account("ann", step, "C:\\x", "y", password="pw")

    assert answer == "done"
    assert acted == [
        ("logon", "ann", "pw"),
        ("step", "C:\\x", "y"),
        ("revert", "ann"),
    ]
    assert "act_as" in WindowsPlatform.capabilities


def test_a_refused_logon_runs_no_step(monkeypatch):
    @contextlib.contextmanager
    def impersonated(account, password, *, advapi32=None, kernel32=None):
        raise ModuleApplyError("credential_invalid", {"account": account})
        yield

    def step():
        raise AssertionError("the step ran")

    monkeypatch.setattr(windows_module, "impersonated", impersonated)

    with pytest.raises(ModuleApplyError) as caught:
        WindowsPlatform().as_account("ann", step, password="old")

    assert caught.value.code == "credential_invalid"


def test_the_agent_s_log_is_agent_log_under_the_log_root(monkeypatch):
    monkeypatch.setenv("ProgramData", "D:\\Data")

    assert (
        WindowsPlatform().agent_log_path()
        == "D:\\Data\\Neutrino\\agent\\log\\agent.log"
    )


class TerminatingKernel32:
    """OpenProcess, TerminateProcess and CloseHandle, recording each call."""

    def __init__(self, *, is_open=True, is_terminated=True):
        self.is_open = is_open
        self.is_terminated = is_terminated
        self.calls: list = []

    def OpenProcess(self, access, is_inherited, pid):
        self.calls.append(("open", access, is_inherited, pid))
        return 0x2000 if self.is_open else 0

    def TerminateProcess(self, process, exit_code):
        self.calls.append(("terminate", process, exit_code))
        return 1 if self.is_terminated else 0

    def CloseHandle(self, handle):
        self.calls.append(("close", handle))
        return 1


def win_error(code: int) -> OSError:
    error = OSError(code, f"error {code}")
    error.winerror = code
    return error


def test_terminate_process_opens_ends_and_closes_the_process():
    kernel32 = TerminatingKernel32()

    WindowsPlatform(kernel32=kernel32).terminate_process(4242)

    assert kernel32.calls == [
        ("open", win32.PROCESS_TERMINATE, False, 4242),
        ("terminate", 0x2000, win32.TERMINATED_EXIT_CODE),
        ("close", 0x2000),
    ]


def test_terminate_process_of_a_pid_nobody_holds_is_a_lookup_error(monkeypatch):
    monkeypatch.setattr(
        win32, "last_error", lambda: win_error(win32.ERROR_INVALID_PARAMETER)
    )
    kernel32 = TerminatingKernel32(is_open=False)

    with pytest.raises(ProcessLookupError):
        WindowsPlatform(kernel32=kernel32).terminate_process(4242)
    assert [call[0] for call in kernel32.calls] == ["open"]


def test_terminate_process_denied_is_an_os_error_and_the_handle_closes(monkeypatch):
    monkeypatch.setattr(win32, "last_error", lambda: win_error(5))
    denied = TerminatingKernel32(is_open=False)
    refused = TerminatingKernel32(is_terminated=False)

    with pytest.raises(OSError) as opening:
        WindowsPlatform(kernel32=denied).terminate_process(4242)
    with pytest.raises(OSError):
        WindowsPlatform(kernel32=refused).terminate_process(4242)

    assert not isinstance(opening.value, ProcessLookupError)
    assert refused.calls[-1] == ("close", 0x2000)


ADDED = {
    "services": ["neutrino_gitea", "neutrino_agent", "neutrino_hub"],
    "tasks": [
        "neutrino_vscode_ann",
        "neutrino_cloudcli_install_bob",
        "neutrino_client_tray",
    ],
    "rules": [
        "neutrino_smb_fence",
        "neutrino_vscode_port_ann",
        "neutrino_hub_panel",
    ],
}


def test_windows_removal_takes_the_modules_tasks_and_rules_and_leaves_the_hubs(
    monkeypatch, tmp_path
):
    """The fence is one of the rules; the hub's own rules stay, every
    process under the state root is ended with the tasks, a child with its
    parent, without regard to case, and every batch logon right the agent
    granted is taken away last."""
    monkeypatch.setenv("ProgramData", f"{tmp_path}/")
    host = RecordingHost({"added_list": ADDED})
    state = f"{tmp_path}/Neutrino\\agent\\state"
    table = FakeProcessTable(
        [
            (4, 0, 0, "System", "", ""),
            (30, 4, 100, "cmd.exe", f'cmd /c "x >> {state.upper()}\\ann.log"', ""),
            (31, 30, 101, "code.exe", "code serve-web", ""),
            (40, 4, 100, "node.exe", "node index.js", f"{state}\\cloudcli\\node.exe"),
            (41, 40, 99, "old.exe", "a pid reused before node started", ""),
            (50, 4, 100, "explorer.exe", "explorer", "C:\\Windows\\explorer.exe"),
        ]
    )
    run_as = tmp_path / "Neutrino\\agent\\state\\run_as"
    run_as.mkdir()
    (run_as / "left.txt").write_text("x")

    batch_logon = FakeBatchLogon(host.calls)
    batch_logon.taken = ["bob"]

    removed = WindowsPlatform(
        powershell=host, processes=table, batch_logon=batch_logon
    ).remove_added()

    assert host.calls == [
        ("added_list", {"prefix": "neutrino_"}),
        (
            "added_remove",
            {
                "services": ["neutrino_gitea"],
                "tasks": ["neutrino_cloudcli_install_bob", "neutrino_vscode_ann"],
                "rules": ["neutrino_smb_fence", "neutrino_vscode_port_ann"],
            },
        ),
        ("batch_logon_release_all", {}),
    ]
    assert table.ended == [30, 40, 31]
    assert not run_as.exists()
    assert removed == [
        "service neutrino_gitea",
        "task neutrino_cloudcli_install_bob",
        "task neutrino_vscode_ann",
        "firewall rule neutrino_smb_fence",
        "firewall rule neutrino_vscode_port_ann",
        "batch logon right of bob",
    ]


def test_windows_removal_with_nothing_added_removes_nothing(monkeypatch, tmp_path):
    monkeypatch.setenv("ProgramData", f"{tmp_path}/")
    host = RecordingHost({"added_list": {"services": [], "tasks": [], "rules": []}})

    removed = WindowsPlatform(
        powershell=host, processes=FakeProcessTable()
    ).remove_added()

    assert removed == []
    assert host.args_of("added_remove") == [{"services": [], "tasks": [], "rules": []}]


@pytest.mark.parametrize("failing", ["added_list", "added_remove"])
def test_windows_removal_says_when_the_host_does_not_answer(failing):
    host = RecordingHost({"added_list": ADDED, failing: TimeoutError("busy")})

    with pytest.raises(OSError):
        WindowsPlatform(powershell=host, processes=FakeProcessTable()).remove_added()


def test_windows_removal_says_when_the_process_table_is_refused(monkeypatch, tmp_path):
    monkeypatch.setenv("ProgramData", f"{tmp_path}/")
    table = FakeProcessTable()
    table.is_refusing = True

    with pytest.raises(OSError):
        WindowsPlatform(powershell=RecordingHost(), processes=table).remove_added()


def test_a_one_shot_run_as_task_is_one_the_removal_takes():
    assert is_added_name("neutrino_run_as_ann", "neutrino_")


class OneShotTask:
    """The host's one-shot task: it runs the script at once, writing the
    output and the exit code its script would, and records each request."""

    def __init__(self, *, exit_text="3\r\n", output="drawn"):
        self.exit_text = exit_text
        self.output = output
        self.host = RecordingHost({"task_run_once": self.run})
        self.seen: dict = {}

    def run(self, args):
        script = args["arguments"][len('/d /c "') : -1]
        directory = script[: -len("\\command.cmd")]
        with open(script, encoding="utf-8", newline="") as stream:
            self.seen["script"] = stream.read()
        with open(directory + "\\command.input", encoding="utf-8") as stream:
            self.seen["input"] = stream.read()
        with open(directory + "\\command.output", "w", encoding="utf-8") as stream:
            stream.write(self.output)
        if self.exit_text is not None:
            with open(directory + "\\command.done", "w", encoding="utf-8") as stream:
                stream.write(self.exit_text)
        return {}


def run_as_platform(task, icacls=None, batch_logon=None):
    return WindowsPlatform(
        kernel32=FakeKernel32(),
        powershell=task.host,
        run=icacls if icacls is not None else Icacls(),
        sleep=lambda seconds: None,
        batch_logon=batch_logon if batch_logon is not None else FakeBatchLogon(),
    )


def test_windows_runs_as_an_account_in_a_one_shot_task_under_its_login(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("ProgramData", f"{tmp_path}/")
    task = OneShotTask()
    icacls = Icacls()
    platform = run_as_platform(task, icacls, FakeBatchLogon(task.host.calls))

    done = platform.run_as_account(
        "ann",
        ["C:\\P F\\cc-switch.exe", "--app", "claude"],
        stdin="in",
        password="pw",  # scan: allow
        timeout_s=30,
    )

    assert (done.returncode, done.stdout) == (3, "drawn")
    directory = f"{tmp_path}/Neutrino\\agent\\state\\run_as\\ann"
    assert task.host.calls == [
        ("batch_logon_hold", {"account": "ann", "task": "neutrino_run_as_ann"}),
        (
            "task_run_once",
            {
                "task": "neutrino_run_as_ann",
                "program": "cmd.exe",
                "arguments": f'/d /c "{directory}\\command.cmd"',
                "account": "ann",
                "password": "pw",  # scan: allow
                "timeout_s": 30,
            },
        ),
        ("task_remove", {"task": "neutrino_run_as_ann"}),
        ("batch_logon_release", {"account": "ann", "task": "neutrino_run_as_ann"}),
    ]
    assert icacls.calls == [
        [
            "icacls.exe",
            directory,
            "/inheritance:r",
            "/grant:r",
            "ann:(OI)(CI)M",
            "*S-1-5-18:(OI)(CI)F",
            "*S-1-5-32-544:(OI)(CI)F",
        ]
    ]
    assert task.seen["input"] == "in"
    lines = task.seen["script"].split("\r\n")
    assert lines[1] == 'cd /d "%USERPROFILE%"'
    assert lines[2] == (
        '"C:\\P F\\cc-switch.exe" "--app" "claude" < '
        f'"{directory}\\command.input" > "{directory}\\command.output" 2>&1'
    )
    assert lines[3] == f'>"{directory}\\command.done" echo %errorlevel%'
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "Neutrino\\agent\\state\\run_as\\ann"
    ]


def test_a_command_that_never_wrote_its_end_reads_minus_one(monkeypatch, tmp_path):
    monkeypatch.setenv("ProgramData", f"{tmp_path}/")
    task = OneShotTask(exit_text=None, output="half")
    clock = [0.0]
    monkeypatch.setattr(windows_module.time, "monotonic", lambda: clock[0])
    waits = []

    def sleep(seconds):
        waits.append(seconds)
        clock[0] += seconds

    platform = WindowsPlatform(
        powershell=task.host,
        run=Icacls(),
        sleep=sleep,
        kernel32=FakeKernel32(),
        batch_logon=FakeBatchLogon(),
    )

    done = platform.run_as_account("ann", ["cc.exe"], password="pw", timeout_s=3)

    assert (done.returncode, done.stdout) == (-1, "half")
    assert sum(waits) >= 3
    assert task.host.ops() == ["task_run_once", "task_remove"]


def test_a_login_windows_refuses_leaves_no_task_and_no_file(monkeypatch, tmp_path):
    monkeypatch.setenv("ProgramData", f"{tmp_path}/")
    refusal = ModuleApplyError("credential_invalid", {"account": "ann"})
    host = RecordingHost({"task_run_once": refusal})
    platform = WindowsPlatform(
        powershell=host,
        run=Icacls(),
        kernel32=FakeKernel32(),
        batch_logon=FakeBatchLogon(host.calls),
    )

    with pytest.raises(ModuleApplyError) as caught:
        platform.run_as_account("ann", ["cc.exe"], stdin="secret", password="old")

    assert caught.value.code == "credential_invalid"
    assert host.ops() == [
        "batch_logon_hold",
        "task_run_once",
        "task_remove",
        "batch_logon_release",
    ]
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "Neutrino\\agent\\state\\run_as\\ann"
    ]


def test_a_run_folder_icacls_refuses_starts_no_task(monkeypatch, tmp_path):
    monkeypatch.setenv("ProgramData", f"{tmp_path}/")
    host = RecordingHost()
    platform = WindowsPlatform(
        powershell=host,
        run=Icacls(5),
        kernel32=FakeKernel32(),
        batch_logon=FakeBatchLogon(host.calls),
    )

    with pytest.raises(OSError, match="icacls refused"):
        platform.run_as_account("ann", ["cc.exe"], password="pw")

    assert host.calls == []


def test_windows_answers_a_question_through_its_own_program_inside_the_task(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("ProgramData", f"{tmp_path}/")
    monkeypatch.setenv("ProgramFiles", "C:\\Program Files")
    task = OneShotTask(exit_text="0", output="Deleted")
    platform = run_as_platform(task)

    answered = platform.run_as_account_answering(
        "ann",
        ["cc.exe", "provider", "delete", "neutrino"],
        prompt="(y/N)",
        answer="y\n",
        password="pw",
    )

    assert answered == (0, "Deleted")
    assert (
        task.seen["script"]
        .split("\r\n")[2]
        .startswith(
            '"C:\\Program Files\\Neutrino\\agent\\nagent.exe" "answer" "--prompt" "(y/N)" '
            '"--answer" "y" "--" "cc.exe" "provider" "delete" "neutrino" <'
        )
    )


def test_every_argument_of_a_task_s_command_is_quoted_and_expands_nothing():
    assert cmd_argument("a&b") == '"a&b"'
    assert cmd_argument("50%") == '"50%%"'
    assert cmd_argument("C:\\dir\\") == '"C:\\dir\\\\"'
    assert cmd_argument("") == '""'


def test_the_uninstall_disables_the_agents_service(monkeypatch):
    """Run by hand, nagent service uninstall leaves the service as the
    package's removal does: stopped and not started at the next boot."""
    commands = []

    def record(command, **kwargs):
        commands.append(list(command))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(windows_module.subprocess, "run", record)

    WindowsPlatform().disable_agent_service()

    assert commands == [["sc", "config", "neutrino_agent", "start=", "disabled"]]


def test_the_one_shot_task_sets_the_variables_it_is_given_first(monkeypatch, tmp_path):
    monkeypatch.setenv("ProgramData", f"{tmp_path}/")
    task = OneShotTask(exit_text="0", output="")
    platform = run_as_platform(task)

    platform.run_as_account(
        "ann",
        ["cc.exe"],
        password="pw",  # scan: allow
        environment={"CC_SWITCH_CONFIG_DIR": "C:\\Users\\ann\\x%y"},
    )

    lines = task.seen["script"].split("\r\n")
    assert lines[2] == 'set "CC_SWITCH_CONFIG_DIR=C:\\Users\\ann\\x%%y"'
    assert lines[3].startswith('"cc.exe"')


class HeldTask(OneShotTask):
    """The one-shot task, each run held until the test lets them end, with
    the most runs seen at once counted."""

    def __init__(self):
        super().__init__(exit_text="0", output="")
        self.started = threading.Semaphore(0)
        self.release = threading.Event()
        self._count_lock = threading.Lock()
        self.running = 0
        self.most = 0

    def run(self, args):
        with self._count_lock:
            self.running += 1
            self.most = max(self.most, self.running)
        self.started.release()
        self.release.wait(5)
        try:
            return super().run(args)
        finally:
            with self._count_lock:
                self.running -= 1


def run_in_thread(platform, account: str) -> threading.Thread:
    thread = threading.Thread(
        target=platform.run_as_account,
        args=(account, ["cc.exe"]),
        kwargs={"password": "pw"},  # scan: allow
        daemon=True,
    )
    thread.start()
    return thread


def test_two_runs_for_one_account_take_turns_whatever_its_names_case(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("ProgramData", f"{tmp_path}/")
    task = HeldTask()
    platform = run_as_platform(task)

    first = run_in_thread(platform, "ann")
    assert task.started.acquire(timeout=5)
    second = run_in_thread(platform, "Ann")

    assert task.started.acquire(timeout=0.3) is False
    assert task.host.ops() == ["task_run_once"]
    task.release.set()
    first.join(5)
    second.join(5)
    assert task.most == 1
    assert task.host.ops() == [
        "task_run_once",
        "task_remove",
        "task_run_once",
        "task_remove",
    ]


def test_runs_for_two_accounts_do_not_wait_on_each_other(monkeypatch, tmp_path):
    monkeypatch.setenv("ProgramData", f"{tmp_path}/")
    task = HeldTask()
    platform = run_as_platform(task)

    first = run_in_thread(platform, "ann")
    second = run_in_thread(platform, "bob")

    assert task.started.acquire(timeout=5)
    assert task.started.acquire(timeout=5)
    assert task.most == 2
    task.release.set()
    first.join(5)
    second.join(5)
    assert task.host.ops().count("task_remove") == 2


# --- the relays ---

WSL_ADAPTER = "vEthernet (WSL (Hyper-V firewall))"
RELAY_ADAPTERS = [
    {"name": "Ethernet Instance 0 2", "mac": "", "addresses": ["192.168.122.46"]},
    {"name": WSL_ADAPTER, "mac": "", "addresses": ["fe80::1", "172.20.208.1"]},
]


def relay_rule(port):
    return RelayRule(interface=WSL_ADAPTER, address="172.20.208.1", prefix=0, port=port)


def test_the_platform_reads_the_wsl_adapter(monkeypatch):
    monkeypatch.setattr(
        windows_module, "read_interfaces", lambda iphlpapi: RELAY_ADAPTERS
    )

    assert WindowsPlatform().read_relay_addresses() == [
        RelayAddress(interface=WSL_ADAPTER, index=0, address="172.20.208.1", prefix=0)
    ]


def test_the_platform_writes_the_rules_through_the_host_when_they_differ():
    host = RecordingHost(
        {
            "relay_rules_read": {
                "rules": [
                    {
                        "name": "neutrino_agent_relay_9000",
                        "port": "9000",
                        "alias": WSL_ADAPTER,
                    }
                ]
            }
        }
    )

    lines = WindowsPlatform(powershell=host).sync_relay_rules(
        frozenset({relay_rule(8317)})
    )

    assert host.calls == [
        ("relay_rules_read", {"prefix": "neutrino_agent_relay_"}),
        (
            "relay_rules_write",
            {
                "add": [
                    {
                        "name": "neutrino_agent_relay_8317",
                        "port": "8317",
                        "alias": WSL_ADAPTER,
                    }
                ],
                "remove": ["neutrino_agent_relay_9000"],
            },
        ),
    ]
    assert lines == [
        "removed firewall rule neutrino_agent_relay_9000",
        f"added firewall rule neutrino_agent_relay_8317 on {WSL_ADAPTER}",
    ]


def test_the_platform_writes_nothing_when_the_rules_stand():
    host = RecordingHost(
        {
            "relay_rules_read": {
                "rules": [
                    {
                        "name": "neutrino_agent_relay_8317",
                        "port": "8317",
                        "alias": WSL_ADAPTER,
                    }
                ]
            }
        }
    )

    assert (
        WindowsPlatform(powershell=host).sync_relay_rules(frozenset({relay_rule(8317)}))
        == []
    )
    assert host.ops() == ["relay_rules_read"]


def test_a_refusal_of_the_host_is_an_os_error():
    host = RecordingHost(
        {
            "relay_rules_read": {"rules": []},
            "relay_rules_write": ModuleApplyError("access_denied", {}),
        }
    )

    with pytest.raises(OSError):
        WindowsPlatform(powershell=host).sync_relay_rules(frozenset({relay_rule(8317)}))
