"""The Windows platform: native metrics, PowerShell interfaces, sc, winreg.

Nothing here needs Windows: kernel32, ntdll, advapi32, pdh, gdi32 and
shell32 are fakes that fill the structures they are handed, PowerShell and
``sc`` are faked at ``subprocess.run`` or as the injected runner, and the
registry is a fake ``winreg``. What is pinned is what each source is turned
into.
"""

import ctypes
import json
import subprocess

import pytest

import neutrino_agent.core.metrics as metrics_module
import neutrino_agent.platforms.windows as windows_module
from neutrino_agent.constants import AGENT_PROCESS_TOP_COUNT
from neutrino_agent.platforms import win32
from neutrino_agent.platforms.windows import WindowsHostMetricsReader, WindowsPlatform


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


def refusing_powershell(script, document):
    raise OSError("powershell is not here")


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
        kernel32=FakeKernel32(), powershell=refusing_powershell
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
        kernel32=kernel32, powershell=refusing_powershell
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
        offset = 0
        for index, (pid, _name, times, working_set) in enumerate(processes):
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


class FakeThermalZones:
    """The PowerShell runner, answering the thermal zones in tenths of K."""

    def __init__(self, readings):
        self.readings = readings
        self.scripts = []

    def __call__(self, script, document):
        self.scripts.append(script)
        return {"readings": self.readings}


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
        "powershell": FakeThermalZones([3011.5, 3231.5]),
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
    assert len(parts["powershell"].scripts) == 1
    assert "MSAcpi_ThermalZoneTemperature" in parts["powershell"].scripts[0]


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
        powershell=FakeThermalZones([]),
    )

    metrics = reader.read()

    assert metrics.cpu_core_percents == []
    assert metrics.processes == []
    assert metrics.gpus == []
    assert metrics.temperature_c is None


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


def test_a_directory_opened_to_accounts_grants_the_users_group_read_and_run():
    calls = []

    def powershell(script, document):
        calls.append((script, document))
        return {"is_open": True}

    assert "hub_packages" in WindowsPlatform.capabilities
    WindowsPlatform(powershell=powershell).open_to_accounts("D:\\state\\vscode")

    script, document = calls[0]
    assert document == {"directory": "D:\\state\\vscode"}
    assert "'*S-1-5-32-545:(OI)(CI)RX'" in script


class FakeSeat:
    """The console session, with whoever is signed in at it."""

    def __init__(self, accounts):
        self.accounts = accounts

    def graphical_accounts(self):
        return None if self.accounts is None else list(self.accounts)


def test_a_shell_starts_in_the_console_accounts_profile(tmp_path):
    platform = WindowsPlatform(
        seat=FakeSeat(["alice"]),
        powershell=lambda script, document: {"is_present": True, "home": str(tmp_path)},
    )

    assert platform.shell_start_dir() == str(tmp_path)


@pytest.mark.parametrize(
    "accounts, read",
    [
        ([], {"is_present": True, "home": "unused"}),
        (None, {"is_present": True, "home": "unused"}),
        (["alice"], {"is_present": False, "home": ""}),
        (["alice"], {"is_present": True, "home": ""}),
        (["alice"], {"is_present": True, "home": "Z:\\no\\such\\profile"}),
    ],
    ids=["nobody", "no_session_api", "no_account", "no_profile", "missing_profile"],
)
def test_a_shell_without_a_profile_starts_at_the_system_drives_root(
    monkeypatch, accounts, read
):
    monkeypatch.setenv("SystemDrive", "D:")
    platform = WindowsPlatform(
        seat=FakeSeat(accounts), powershell=lambda script, document: read
    )

    assert platform.shell_start_dir() == "D:\\"


def test_a_powershell_that_cannot_answer_starts_the_shell_at_the_root(monkeypatch):
    monkeypatch.delenv("SystemDrive", raising=False)

    def powershell(script, document):
        raise subprocess.TimeoutExpired("powershell", 1)

    platform = WindowsPlatform(seat=FakeSeat(["alice"]), powershell=powershell)

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


class FakePowerShell:
    """PowerShell, recorded, answering one document or raising."""

    def __init__(self, answer=None, error=None):
        self.runs: list = []
        self._answer = answer or {}
        self._error = error

    def __call__(self, script, document):
        self.runs.append((script, document))
        if self._error is not None:
            raise self._error
        return dict(self._answer)


def test_the_accounts_are_the_enabled_people_without_the_builtin_or_share_ones():
    powershell = FakePowerShell(
        {
            "users": [
                {"name": "zoe", "description": ""},
                {"name": "Administrator", "description": "Built-in account"},
                {"name": "DefaultAccount", "description": ""},
                {"name": "WDAGUtilityAccount", "description": ""},
                {"name": "Guest", "description": ""},
                {"name": "media", "description": "neutrino:"},
                {"name": "hanha", "description": "Hanha's account"},
            ]
        }
    )

    accounts = WindowsPlatform(powershell=powershell).human_accounts()

    assert accounts == ["hanha", "zoe"]
    ((script, _document),) = powershell.runs
    assert "Get-LocalUser" in script and "$_.Enabled" in script
    assert "accounts" in WindowsPlatform.capabilities


def test_one_account_printed_bare_is_still_read():
    powershell = FakePowerShell({"users": {"name": "hanha", "description": ""}})

    assert WindowsPlatform(powershell=powershell).human_accounts() == ["hanha"]


def test_a_powershell_that_fails_reads_as_no_accounts():
    powershell = FakePowerShell(error=OSError("powershell exited 1"))

    assert WindowsPlatform(powershell=powershell).human_accounts() == []


def test_the_accounts_are_read_once_per_thirty_seconds(monkeypatch):
    powershell = FakePowerShell({"users": [{"name": "hanha", "description": ""}]})
    now = [100.0]
    monkeypatch.setattr(windows_module.time, "monotonic", lambda: now[0])
    platform = WindowsPlatform(powershell=powershell)

    platform.human_accounts()
    now[0] += 29
    platform.human_accounts()
    assert len(powershell.runs) == 1
    now[0] += 2
    platform.human_accounts()
    assert len(powershell.runs) == 2


def test_an_account_home_is_its_profile_directory():
    powershell = FakePowerShell({"is_present": True, "home": "C:\\Users\\hanha"})

    home = WindowsPlatform(powershell=powershell).account_home("hanha")

    assert home == "C:\\Users\\hanha"
    ((script, document),) = powershell.runs
    assert "Win32_UserProfile" in script
    assert document == {"name": "hanha"}


@pytest.mark.parametrize(
    "answer",
    [{"is_present": False, "home": ""}, {"is_present": True, "home": ""}],
)
def test_an_account_with_no_profile_has_no_home(answer):
    platform = WindowsPlatform(powershell=FakePowerShell(answer))

    with pytest.raises(KeyError):
        platform.account_home("ghost")


def test_an_account_home_powershell_cannot_give_is_an_os_error():
    powershell = FakePowerShell(error=subprocess.TimeoutExpired("powershell", 120))

    with pytest.raises(OSError):
        WindowsPlatform(powershell=powershell).account_home("hanha")


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
