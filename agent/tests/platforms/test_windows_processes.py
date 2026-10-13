"""The machine's processes as Windows lists them, from built buffers and faked calls.

What these pin: a ``SystemProcessInformation`` buffer decodes to each
process's id, parent, start, image name, times and working set, a name
outside the buffer reads empty and an entry past its end ends the walk; a
tree is its roots and every process they started, a child never older than
its parent; a lineage climbs from a process to the ones that started it and
stops at a parent younger than its child; a process's command line and
image path are read from its parameters through its environment block, and
one that cannot be opened or read is empty; a listener read that fails is
no listener; and ending processes leaves the ones already gone.
"""

import ctypes
import struct

import pytest

from neutrino_agent.platforms import win32
from neutrino_agent.platforms.windows_processes import (
    WindowsProcessEntry,
    WindowsProcessTable,
    lineage,
    process_entries,
    process_tree,
    query_system_information,
)

BASE = 0x40000


def process_buffer(processes, base=BASE) -> bytes:
    """A process table as the kernel fills it at ``base``: ``(pid, parent,
    created, name, cpu, working set)`` per process, each name after its entry."""
    entry_size = ctypes.sizeof(win32.SystemProcessInformation)
    names = [process[3].encode("utf-16-le") for process in processes]
    strides = [(entry_size + len(name) + 7) // 8 * 8 for name in names]
    data = bytearray(sum(strides))
    offset = 0
    for index, (pid, parent, created, _name, cpu, working_set) in enumerate(processes):
        entry = win32.SystemProcessInformation.from_buffer(data, offset)
        is_last = index == len(processes) - 1
        entry.NextEntryOffset = 0 if is_last else strides[index]
        entry.UniqueProcessId = pid
        entry.InheritedFromUniqueProcessId = parent
        entry.CreateTime = created
        entry.UserTime = cpu // 2
        entry.KernelTime = cpu - cpu // 2
        entry.WorkingSetSize = working_set
        name = names[index]
        data[offset + entry_size : offset + entry_size + len(name)] = name
        entry.ImageName.Length = len(name)
        entry.ImageName.MaximumLength = len(name)
        entry.ImageName.Buffer = base + offset + entry_size if name else None
        offset += strides[index]
    return bytes(data)


TABLE = [
    (0, 0, 0, "", 900, 8),
    (4, 0, 1, "System", 10, 1024),
    (30, 4, 100, "cmd.exe", 3, 2048),
    (31, 30, 101, "node.exe", 7, 4096),
]


def entry(pid, parent, created):
    return WindowsProcessEntry(pid, parent, created, "", 0, 0)


def test_the_process_table_decodes_each_process():
    entries = process_entries(process_buffer(TABLE), BASE)

    assert entries == [
        WindowsProcessEntry(0, 0, 0, "", 900, 8),
        WindowsProcessEntry(4, 0, 1, "System", 10, 1024),
        WindowsProcessEntry(30, 4, 100, "cmd.exe", 3, 2048),
        WindowsProcessEntry(31, 30, 101, "node.exe", 7, 4096),
    ]


def test_a_name_outside_the_buffer_reads_empty_and_a_short_entry_ends_the_walk():
    data = process_buffer(TABLE)

    assert [e.name for e in process_entries(data, BASE + 0x1000)] == ["", "", "", ""]
    assert [e.pid for e in process_entries(data[:400], BASE)] == [0, 4]
    assert process_entries(b"", BASE) == []


def test_a_tree_is_its_roots_and_every_process_they_started():
    entries = [
        entry(4, 0, 1),
        entry(30, 4, 100),
        entry(31, 30, 101),
        entry(32, 31, 102),
        entry(33, 30, 50),
        entry(40, 4, 100),
    ]

    assert process_tree(entries, [30, 30, 99]) == [30, 31, 32]
    assert process_tree(entries, []) == []


def test_a_lineage_climbs_while_each_parent_is_no_younger_than_its_child():
    entries = [entry(0, 0, 0), entry(4, 0, 1), entry(30, 4, 100), entry(31, 30, 101)]
    reused = [entry(4, 0, 1), entry(30, 4, 500), entry(31, 30, 101)]

    assert lineage(entries, 31) == [31, 30, 4, 0]
    assert lineage(reused, 31) == [31]
    assert lineage(entries, 77) == []


class FakeNtdll:
    """NtQuerySystemInformation and NtQueryInformationProcess, scripted."""

    def __init__(self, processes=(), pebs=None):
        self.processes = list(processes)
        self.pebs = dict(pebs or {})

    def NtQuerySystemInformation(self, info_class, buffer, size, needed):
        assert info_class == win32.SYSTEM_PROCESS_INFORMATION_CLASS
        table = process_buffer(self.processes, base=ctypes.addressof(buffer))
        needed._obj.value = len(table)
        if size < len(table):
            return win32.STATUS_INFO_LENGTH_MISMATCH
        ctypes.memmove(buffer, table, len(table))
        return 0

    def NtQueryInformationProcess(self, process, kind, information, size, length):
        assert kind == win32.PROCESS_BASIC_INFORMATION_CLASS
        assert size == 48
        peb = self.pebs.get(process)
        if peb is None:
            return 0xC0000022
        information._obj.PebBaseAddress = peb
        return 0


class FakeKernel32:
    """OpenProcess and ReadProcessMemory over a memory of addresses."""

    def __init__(self, memory, *, openable=()):
        self.memory = dict(memory)
        self.openable = set(openable)
        self.closed: list = []
        self.terminated: list = []

    def OpenProcess(self, access, is_inherited, pid):
        if access == win32.PROCESS_TERMINATE:
            return 0x900 + pid
        assert access == win32.PROCESS_QUERY_INFORMATION | win32.PROCESS_VM_READ
        return 0x800 + pid if pid in self.openable else 0

    def ReadProcessMemory(self, process, address, buffer, size, done):
        data = self.memory.get(address.value)
        if data is None or len(data) < size:
            return 0
        ctypes.memmove(buffer, data, size)
        done._obj.value = size
        return 1

    def TerminateProcess(self, process, code):
        if process == 0x900 + 13:
            return 0
        self.terminated.append(process - 0x900)
        return 1

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return 1


def process_memory(pid, command, image):
    """The memory one process's parameters are read from: its environment
    block's pointer to the parameters, two counted strings and their text."""
    peb = 0x10000 * pid
    parameters = peb + 0x1000
    command_text = command.encode("utf-16-le")
    image_text = image.encode("utf-16-le")
    command_at = parameters + 0x400
    image_at = parameters + 0x800

    def counted(text, at):
        return struct.pack("<HHIQ", len(text), len(text), 0, at)

    memory = {
        peb + 0x20: struct.pack("<Q", parameters),
        parameters + 0x70: counted(command_text, command_at),
        parameters + 0x60: counted(image_text, image_at),
        command_at: command_text,
        image_at: image_text,
    }
    return peb, memory


def test_a_process_s_command_line_and_image_path_are_its_start_parameters():
    peb, memory = process_memory(31, "node index.js --port 8000", "C:\\node\\node.exe")
    kernel32 = FakeKernel32(memory, openable={31})
    table = WindowsProcessTable(
        ntdll=FakeNtdll(pebs={0x800 + 31: peb}), kernel32=kernel32
    )

    assert table.command_line(31) == "node index.js --port 8000"
    assert table.image_path(31) == "C:\\node\\node.exe"
    assert kernel32.closed == [0x800 + 31, 0x800 + 31]


def test_a_process_that_cannot_be_opened_or_read_has_an_empty_command_line():
    peb, memory = process_memory(31, "node", "C:\\node.exe")
    del memory[peb + 0x20]
    kernel32 = FakeKernel32(memory, openable={31, 32})
    table = WindowsProcessTable(
        ntdll=FakeNtdll(pebs={0x800 + 31: peb}), kernel32=kernel32
    )

    assert table.command_line(30) == ""
    assert table.command_line(31) == ""
    assert table.command_line(32) == ""


def test_the_table_reads_every_process_now():
    table = WindowsProcessTable(ntdll=FakeNtdll(TABLE))

    assert [e.pid for e in table.entries()] == [0, 4, 30, 31]
    assert table.entries()[3].name == "node.exe"


def test_a_table_the_kernel_refuses_is_an_os_error():
    class Refusing:
        def NtQuerySystemInformation(self, *args):
            return 0xC0000022

    with pytest.raises(OSError):
        WindowsProcessTable(ntdll=Refusing()).entries()
    assert query_system_information(Refusing(), 5, 16) is None


def test_a_listener_read_that_fails_is_no_listener():
    def failing(port):
        raise OSError("refused")

    def listening(port):
        return [31] if port == 8000 else []

    assert WindowsProcessTable(read_listeners=failing).listener_pids(8000) == []
    assert WindowsProcessTable(read_listeners=listening).listener_pids(8000) == [31]


def test_ending_processes_leaves_the_ones_that_will_not_end(monkeypatch):
    monkeypatch.setattr(win32, "last_error", lambda: OSError(5, "denied"))
    kernel32 = FakeKernel32({})

    WindowsProcessTable(kernel32=kernel32).end([12, 13, 14])

    assert kernel32.terminated == [12, 14]


def test_off_windows_no_parameter_is_read():
    assert WindowsProcessTable().command_line(4) == ""
    with pytest.raises(OSError):
        WindowsProcessTable().entries()
