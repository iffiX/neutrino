"""The machine's processes as Windows lists them: the table, and each one's own start.

The table is ``NtQuerySystemInformation``'s process class: each process's
id, its parent's, when it started, its image name, its times and its working
set. A process's image path and command line are the ones it started with,
read from its process environment block: ``NtQueryInformationProcess``
names the block, ``ReadProcessMemory`` reads the parameters it points at.
The decoder takes the bytes the kernel filled and the address they sat at,
never a live handle; the calls take the bound libraries as their seam.

Not pure: calls ntdll and kernel32, and ends processes.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import ctypes
from dataclasses import dataclass

from neutrino_agent.platforms import win32
from neutrino_agent.platforms.windows_net import read_listener_pids

# Where the process table's buffer starts; a buffer too small grows to what
# the kernel asks for, a few times at most.
WINDOWS_PROCESSES_BUFFER_BYTES = 512 * 1024
WINDOWS_PROCESSES_QUERY_ATTEMPTS = 4
WINDOWS_PROCESSES_QUERY_SLACK_BYTES = 64 * 1024
# The access a process is opened with to read its parameters.
WINDOWS_PROCESSES_READ_ACCESS = win32.PROCESS_QUERY_INFORMATION | win32.PROCESS_VM_READ
WINDOWS_PROCESSES_POINTER_BYTES = 8


def query_system_information(ntdll, info_class: int, size: int):
    """One system information class, the buffer grown until it fits.

    Args:
        ntdll: The bound ntdll.
        info_class: The class asked for.
        size: The buffer's first size.

    Returns:
        The buffer and the length the kernel filled, or None when the
        kernel refuses.
    """
    for _attempt in range(WINDOWS_PROCESSES_QUERY_ATTEMPTS):
        buffer = ctypes.create_string_buffer(size)
        needed = win32.DWORD(0)
        status = ntdll.NtQuerySystemInformation(
            info_class, buffer, size, ctypes.byref(needed)
        )
        if status == 0:
            return buffer, min(needed.value, size)
        if status != win32.STATUS_INFO_LENGTH_MISMATCH:
            return None
        size = max(size * 2, needed.value + WINDOWS_PROCESSES_QUERY_SLACK_BYTES)
    return None


def process_entries(data: bytes, base: int) -> list:
    """The processes a ``SystemProcessInformation`` buffer lists.

    An entry that does not fit the buffer ends the walk, and an image name
    whose characters lie outside it reads as empty.

    Args:
        data: The buffer's bytes.
        base: The address the buffer sat at, which the names count from.

    Returns:
        :class:`WindowsProcessEntry` per process, in the table's order.
    """
    entries = []
    entry_size = ctypes.sizeof(win32.SystemProcessInformation)
    offset = 0
    while offset + entry_size <= len(data):
        entry = win32.SystemProcessInformation.from_buffer_copy(data, offset)
        entries.append(
            WindowsProcessEntry(
                pid=entry.UniqueProcessId or 0,
                parent_pid=entry.InheritedFromUniqueProcessId or 0,
                create_time=entry.CreateTime,
                name=_counted_text(data, base, entry.ImageName),
                cpu_time=entry.UserTime + entry.KernelTime,
                working_set=entry.WorkingSetSize,
            )
        )
        if entry.NextEntryOffset == 0:
            break
        offset += entry.NextEntryOffset
    return entries


def process_tree(entries: list, roots: list) -> list:
    """Some processes and every process they started, a child never older than its parent.

    Args:
        entries: The table, as :func:`process_entries` reads it.
        roots: The pids the tree starts from.

    Returns:
        The roots, then their descendants, each pid once.
    """
    by_pid = {entry.pid: entry for entry in entries}
    tree = [pid for pid in dict.fromkeys(roots) if pid in by_pid]
    members = set(tree)
    index = 0
    while index < len(tree):
        parent = by_pid[tree[index]]
        for child in entries:
            if (
                child.parent_pid == parent.pid
                and child.create_time >= parent.create_time
                and child.pid not in members
            ):
                tree.append(child.pid)
                members.add(child.pid)
        index += 1
    return tree


def lineage(entries: list, pid: int) -> list:
    """A process and the processes that started it, each no younger than its child.

    Args:
        entries: The table, as :func:`process_entries` reads it.
        pid: The process.

    Returns:
        Its pid, its parent's, and so on up; empty when the table does not
        hold it.
    """
    by_pid = {entry.pid: entry for entry in entries}
    chain = []
    current = by_pid.get(pid)
    while current is not None and current.pid not in chain:
        chain.append(current.pid)
        parent = by_pid.get(current.parent_pid)
        if parent is None or parent.create_time > current.create_time:
            break
        current = parent
    return chain


def terminate_process(kernel32, pid: int) -> None:
    """End one process at once through ``TerminateProcess``.

    Args:
        kernel32: The bound kernel32.
        pid: The process to end.

    Raises:
        ProcessLookupError: When no process holds the pid.
        OSError: When the process cannot be opened or ended.
    """
    process = kernel32.OpenProcess(win32.PROCESS_TERMINATE, False, pid)
    if not process:
        error = win32.last_error()
        if getattr(error, "winerror", None) == win32.ERROR_INVALID_PARAMETER:
            raise ProcessLookupError(pid)
        raise error
    try:
        if not kernel32.TerminateProcess(process, win32.TERMINATED_EXIT_CODE):
            raise win32.last_error()
    finally:
        kernel32.CloseHandle(process)


def _read(kernel32, process, address: int, size: int) -> bytes:
    """Bytes of another process's memory, all of them or OSError."""
    buffer = ctypes.create_string_buffer(size)
    done = ctypes.c_size_t(0)
    if not kernel32.ReadProcessMemory(
        process, ctypes.c_void_p(address), buffer, size, ctypes.byref(done)
    ):
        raise OSError(f"ReadProcessMemory refused {size} bytes at {address:#x}")
    if done.value != size:
        raise OSError(f"ReadProcessMemory read {done.value} of {size} bytes")
    return buffer.raw


def _counted_text(data: bytes, base: int, string: "win32.UnicodeString") -> str:
    """A counted UTF-16 string inside the buffer; empty when it lies outside."""
    if not string.Buffer or not string.Length:
        return ""
    offset = string.Buffer - base
    if offset < 0 or offset + string.Length > len(data):
        return ""
    return data[offset : offset + string.Length].decode("utf-16-le", "replace")


@dataclass(frozen=True)
class WindowsProcessEntry:
    """One process in the table.

    Attributes:
        pid: Its id; 0 is the idle process.
        parent_pid: The id of the process that started it.
        create_time: When it started, in 100-nanosecond intervals.
        name: Its image name, such as ``node.exe``.
        cpu_time: Its user and kernel time together.
        working_set: Its working set, in bytes.
    """

    pid: int
    parent_pid: int
    create_time: int
    name: str
    cpu_time: int
    working_set: int


class WindowsProcessTable:
    """The machine's processes: the table, how each started, who listens, ending one."""

    def __init__(self, *, ntdll=None, kernel32=None, read_listeners=None):
        """
        Args:
            ntdll: The bound ntdll; None binds the real one on first use.
            kernel32: The bound kernel32; None binds the real one on first
                use.
            read_listeners: Returns the pids listening on a TCP port; None
                reads the socket tables.
        """
        self._ntdll = ntdll
        self._kernel32 = kernel32
        self._read_listeners = (
            read_listeners if read_listeners is not None else read_listener_pids
        )

    def entries(self) -> list:
        """Every process now.

        Returns:
            :class:`WindowsProcessEntry` per process.

        Raises:
            OSError: When the kernel refuses the table.
        """
        ntdll = self._ntdll or win32.libraries().ntdll
        answer = query_system_information(
            ntdll,
            win32.SYSTEM_PROCESS_INFORMATION_CLASS,
            WINDOWS_PROCESSES_BUFFER_BYTES,
        )
        if answer is None:
            raise OSError("NtQuerySystemInformation refused the process table")
        buffer, _length = answer
        return process_entries(buffer.raw, ctypes.addressof(buffer))

    def command_line(self, pid: int) -> str:
        """The command line one process started with.

        Args:
            pid: The process.

        Returns:
            The command line; empty when it cannot be read.
        """
        return self._parameter(pid, win32.PROCESS_PARAMETERS_COMMAND_LINE_OFFSET)

    def image_path(self, pid: int) -> str:
        """The program one process started from, as it was named then.

        Args:
            pid: The process.

        Returns:
            The program's path; empty when it cannot be read.
        """
        return self._parameter(pid, win32.PROCESS_PARAMETERS_IMAGE_PATH_OFFSET)

    def listener_pids(self, port: int) -> list:
        """The processes listening on one TCP port, IPv4 or IPv6.

        Args:
            port: The port.

        Returns:
            Their pids; empty when the socket tables cannot be read.
        """
        try:
            return list(self._read_listeners(port))
        except (OSError, ValueError):
            return []

    def end(self, pids: list) -> None:
        """End processes at once, leaving the ones already gone or protected.

        Args:
            pids: The processes.
        """
        kernel32 = self._kernel32 or win32.libraries().kernel32
        for pid in pids:
            try:
                terminate_process(kernel32, pid)
            except OSError:
                continue

    def _parameter(self, pid: int, offset: int) -> str:
        """One string of a process's parameters; empty when it cannot be read."""
        try:
            kernel32 = self._kernel32 or win32.libraries().kernel32
            ntdll = self._ntdll or win32.libraries().ntdll
        except OSError:
            return ""
        process = kernel32.OpenProcess(WINDOWS_PROCESSES_READ_ACCESS, False, pid)
        if not process:
            return ""
        try:
            information = win32.ProcessBasicInformation()
            if ntdll.NtQueryInformationProcess(
                process,
                win32.PROCESS_BASIC_INFORMATION_CLASS,
                ctypes.byref(information),
                ctypes.sizeof(information),
                None,
            ):
                return ""
            pointer = _read(
                kernel32,
                process,
                information.PebBaseAddress + win32.PEB_PROCESS_PARAMETERS_OFFSET,
                WINDOWS_PROCESSES_POINTER_BYTES,
            )
            parameters = int.from_bytes(pointer, "little")
            string = win32.UnicodeString.from_buffer_copy(
                _read(
                    kernel32,
                    process,
                    parameters + offset,
                    ctypes.sizeof(win32.UnicodeString),
                )
            )
            if not string.Buffer or not string.Length:
                return ""
            text = _read(kernel32, process, string.Buffer, string.Length)
            return text.decode("utf-16-le", "replace")
        except OSError:
            return ""
        finally:
            kernel32.CloseHandle(process)
