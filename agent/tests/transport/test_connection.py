"""A local connection: a Unix socket, or a Windows pipe read and written
overlapped, here against a ``_winapi`` a test plays."""

import socket

import pytest

from neutrino_agent.transport.connection import (
    ERROR_BROKEN_PIPE,
    ERROR_PIPE_BUSY,
    LocalSocketConnection,
    WindowsPipeConnection,
    open_local,
)


class Overlapped:
    def __init__(self, data=b"", count=0, error=0):
        self.event = object()
        self._data = data
        self._count = count
        self._error = error
        self.is_cancelled = False

    def GetOverlappedResult(self, wait):
        return self._count, self._error

    def getbuffer(self):
        return memoryview(self._data)

    def cancel(self):
        self.is_cancelled = True


class FakeWinapi:
    GENERIC_READ = 1
    GENERIC_WRITE = 2
    NULL = 0
    OPEN_EXISTING = 3
    FILE_FLAG_OVERLAPPED = 0x40000000
    ERROR_IO_PENDING = 997
    ERROR_MORE_DATA = 234
    WAIT_OBJECT_0 = 0

    def __init__(self, reads=(), busy=0, write_sizes=()):
        self.reads = list(reads)
        self.busy = busy
        self.write_sizes = list(write_sizes)
        self.written: list = []
        self.closed = False
        self.waited_for_pipe = 0

    def CreateFile(self, name, access, share, security, disposition, flags, template):
        assert flags == self.FILE_FLAG_OVERLAPPED
        if self.busy:
            self.busy -= 1
            error = OSError("busy")
            error.winerror = ERROR_PIPE_BUSY
            raise error
        return 77

    def WaitNamedPipe(self, name, timeout):
        self.waited_for_pipe += 1

    def ReadFile(self, handle, size, overlapped):
        item = self.reads.pop(0)
        if isinstance(item, Exception):
            raise item
        return Overlapped(data=item, count=len(item)), self.ERROR_IO_PENDING

    def WriteFile(self, handle, data, overlapped):
        size = self.write_sizes.pop(0) if self.write_sizes else len(data)
        self.written.append(bytes(data[:size]))
        return Overlapped(count=size), 0

    def WaitForMultipleObjects(self, events, wait_all, timeout):
        return self.WAIT_OBJECT_0

    def CloseHandle(self, handle):
        self.closed = True


def broken() -> OSError:
    error = OSError("broken")
    error.winerror = ERROR_BROKEN_PIPE
    return error


def test_a_pipe_reads_what_comes_and_ends_empty_when_it_breaks():
    api = FakeWinapi(reads=[b"line\n", broken()])
    pipe = WindowsPipeConnection("\\\\.\\pipe\\x", api=api)

    assert pipe.recv(1024) == b"line\n"
    assert pipe.recv(1024) == b""


def test_a_pipe_writes_every_byte_across_short_writes():
    api = FakeWinapi(write_sizes=[3, 2])
    pipe = WindowsPipeConnection("\\\\.\\pipe\\x", api=api)

    pipe.sendall(b"hello")

    assert api.written == [b"hel", b"lo"]


def test_a_busy_pipe_is_waited_for():
    api = FakeWinapi(busy=2)

    WindowsPipeConnection("\\\\.\\pipe\\x", api=api)

    assert api.waited_for_pipe == 2


def test_a_closed_pipe_writes_nothing_more():
    api = FakeWinapi()
    pipe = WindowsPipeConnection("\\\\.\\pipe\\x", api=api)

    pipe.close()

    assert api.closed
    with pytest.raises(OSError):
        pipe.sendall(b"x")


def test_a_pipe_name_opens_a_pipe_and_a_path_a_socket(monkeypatch, tmp_path):
    opened: list = []
    monkeypatch.setattr(
        "neutrino_agent.transport.connection.WindowsPipeConnection",
        lambda name, timeout_s: opened.append(name) or "pipe",
    )

    assert open_local("\\\\.\\pipe\\neutrino_agent_transport") == "pipe"
    assert opened == ["\\\\.\\pipe\\neutrino_agent_transport"]
    with pytest.raises(OSError):
        open_local(str(tmp_path / "nothing.sock"))


def test_closing_a_socket_wakes_a_reader():
    near, far = socket.socketpair()
    connection = LocalSocketConnection("", sock=near)

    connection.close()

    assert far.recv(1) == b""
