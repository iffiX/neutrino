"""PowerShell on a pseudo console, served through a fake kernel32.

The fake plays the console and the shell: the output it was scripted with is
what ReadFile hands back, the bytes written to the console's input are
recorded, and the shell exits when it is told ``exit`` or terminated. What
these pin: the console's output arrives as bytes and the exit code closes
the stream, the hub's bytes reach the console with credit offered back, a
resize resizes the console, a close from the hub terminates the shell and
closes its job, the shell starts suspended with the agent's standard
handles set aside and is resumed only once it is in the job, it starts in
the console account's profile directory or the system drive's root when
nobody is signed in, and a Windows without a pseudo console is refused.
"""

import ctypes
import threading
import time

import pytest

from neutrino_agent.exceptions import StreamRefused
from neutrino_agent.platforms import win32
from neutrino_agent.platforms.windows import WindowsPlatform
from neutrino_agent.streams import shell as shell_module
from neutrino_agent.streams.shell_session import ShellSessionRegistry
from neutrino_agent.streams.windows_shell import WindowsShellStream
from tests.streams.fake_channel import FakeChannel

WAIT_TIMEOUT = 258

CONSOLE = 0x50
PROCESS = 0x60
THREAD = 0x61
JOB = 0x70
STD_HANDLES = (0x11, 0x12, 0x13)


class FakeKernel32:
    """The pseudo console calls and one scripted shell behind them."""

    def __init__(self, output=(), *, exit_on=b"exit"):
        self.output = list(output)
        self.exit_on = exit_on
        self.calls = []
        self.written = []
        self.resizes = []
        self.closed = []
        self.std = dict(zip(win32.STD_HANDLE_NAMES, STD_HANDLES))
        self.std_at_create = None
        self.start_dir = None
        self.exit_code = None
        self.is_console_closed = threading.Event()
        self.next_handle = 0x100

    # -- pipes and the console --

    def CreatePipe(self, read, write, attributes, size):
        self.next_handle += 2
        read._obj.value = self.next_handle
        write._obj.value = self.next_handle + 1
        return 1

    def CreatePseudoConsole(self, size, console_input, console_output, flags, out):
        self.calls.append(("CreatePseudoConsole", size.X, size.Y))
        out._obj.value = CONSOLE
        return 0

    def ResizePseudoConsole(self, console, size):
        self.resizes.append((getattr(console, "value", console), size.X, size.Y))
        return 0

    def ClosePseudoConsole(self, console):
        self.calls.append(("ClosePseudoConsole", console))
        self.is_console_closed.set()

    def ReadFile(self, handle, buffer, size, read, overlapped):
        if self.output:
            chunk = self.output.pop(0)
            ctypes.memmove(buffer, chunk, len(chunk))
            read._obj.value = len(chunk)
            return 1
        self.is_console_closed.wait(timeout=5)
        read._obj.value = 0
        return 0

    def WriteFile(self, handle, data, size, written, overlapped):
        self.written.append(bytes(data))
        written._obj.value = size
        if self.exit_on in bytes(data):
            self.exit_code = int(bytes(data).split()[-1])
        return 1

    # -- the process --

    def InitializeProcThreadAttributeList(self, attributes, count, flags, size):
        size._obj.value = 48
        return 1

    def UpdateProcThreadAttribute(self, attributes, flags, name, value, size, *rest):
        self.calls.append(("UpdateProcThreadAttribute", name, value.value))
        return 1

    def DeleteProcThreadAttributeList(self, attributes):
        self.calls.append(("DeleteProcThreadAttributeList",))

    def GetStdHandle(self, name):
        return self.std[name]

    def SetStdHandle(self, name, handle):
        self.std[name] = handle
        return 1

    def CreateProcessW(self, application, command_line, *rest):
        flags = rest[3]
        process = rest[-1]._obj
        self.std_at_create = dict(self.std)
        self.start_dir = rest[5]
        self.calls.append(("CreateProcessW", command_line, flags))
        process.hProcess = PROCESS
        process.hThread = THREAD
        return 1

    def CreateJobObjectW(self, attributes, name):
        self.calls.append(("CreateJobObjectW",))
        return JOB

    def SetInformationJobObject(self, job, information_class, limits, size):
        flags = limits._obj.BasicLimitInformation.LimitFlags
        self.calls.append(("SetInformationJobObject", information_class, flags))
        return 1

    def AssignProcessToJobObject(self, job, process):
        self.calls.append(("AssignProcessToJobObject", job, process))
        return 1

    def ResumeThread(self, thread):
        self.calls.append(("ResumeThread", thread))
        return 1

    def WaitForSingleObject(self, handle, milliseconds):
        if self.exit_code is not None:
            return win32.WAIT_OBJECT_0
        time.sleep(0.01)
        return WAIT_TIMEOUT

    def TerminateProcess(self, handle, code):
        self.calls.append(("TerminateProcess", handle, code))
        if self.exit_code is None:
            self.exit_code = code
        return 1

    def GetExitCodeProcess(self, handle, code):
        code._obj.value = self.exit_code
        return 1

    def CloseHandle(self, handle):
        self.closed.append(getattr(handle, "value", handle))
        return 1

    def names(self):
        return [call[0] for call in self.calls]


class NoConsoleKernel32:
    """A Windows before 1809: kernel32 with no pseudo console."""


class FakeSeat:
    """The console session, with whoever is signed in at it."""

    def __init__(self, accounts):
        self.accounts = accounts

    def graphical_accounts(self):
        return list(self.accounts)


class FakePlatform:
    """A platform that names one start directory."""

    def shell_start_dir(self):
        return "C:\\Users\\alice"


def run_shell(kernel32, channel, *, platform=None, **args):
    stream = WindowsShellStream(
        channel,
        {"cols": 80, "rows": 24, **args},
        kernel32=kernel32,
        platform=platform or FakePlatform(),
    )
    stream.open()
    return stream.run()


def test_the_consoles_output_arrives_as_bytes_and_the_exit_code_closes():
    kernel32 = FakeKernel32([b"PS C:\\> ", b"hello\r\n"])
    channel = FakeChannel()
    channel.feed(("data", b"exit 3\r"))

    closed = run_shell(kernel32, channel)

    assert channel.output() == b"PS C:\\> hello\r\n"
    assert closed == {"code": "", "params": {"exit_code": 3}}
    assert channel.credits[0] > 0


def test_the_first_size_is_the_consoles():
    kernel32 = FakeKernel32()
    channel = FakeChannel()
    channel.feed(("data", b"exit 0\r"))

    run_shell(kernel32, channel, cols=132, rows=50)

    assert ("CreatePseudoConsole", 132, 50) in kernel32.calls


def test_the_hubs_bytes_reach_the_console_and_credit_comes_back():
    kernel32 = FakeKernel32()
    channel = FakeChannel()
    channel.feed(("data", b"Get-Date\r"))
    channel.feed(("data", b"exit 0\r"))

    run_shell(kernel32, channel)

    assert kernel32.written == [b"Get-Date\r", b"exit 0\r"]
    assert channel.credits[1:] == [len(b"Get-Date\r"), len(b"exit 0\r")]


def test_a_resize_resizes_the_console():
    kernel32 = FakeKernel32()
    channel = FakeChannel()
    channel.feed(("resize", 132, 50))
    channel.feed(("data", b"exit 0\r"))

    run_shell(kernel32, channel)

    assert kernel32.resizes == [(CONSOLE, 132, 50)]


def test_a_close_from_the_hub_terminates_the_shell_and_closes_its_job():
    kernel32 = FakeKernel32()
    channel = FakeChannel()
    outcome = {}

    def serve():
        outcome.update(run_shell(kernel32, channel))

    thread = threading.Thread(target=serve)
    thread.start()
    time.sleep(0.1)
    channel.close_from_hub()
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert ("TerminateProcess", PROCESS, 1) in kernel32.calls
    assert outcome == {"code": "", "params": {"exit_code": 1}}
    assert JOB in kernel32.closed
    assert kernel32.is_console_closed.is_set()


def test_powershell_starts_suspended_and_is_resumed_once_in_the_job():
    kernel32 = FakeKernel32()
    channel = FakeChannel()
    channel.feed(("data", b"exit 0\r"))

    run_shell(kernel32, channel)

    create = next(call for call in kernel32.calls if call[0] == "CreateProcessW")
    assert create[1] == "powershell.exe -NoLogo"
    assert create[2] & win32.EXTENDED_STARTUPINFO_PRESENT
    assert create[2] & win32.CREATE_SUSPENDED
    names = kernel32.names()
    assert names.index("CreateProcessW") < names.index("AssignProcessToJobObject")
    assert names.index("AssignProcessToJobObject") < names.index("ResumeThread")
    assert (
        "SetInformationJobObject",
        win32.JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
        win32.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    ) in kernel32.calls
    assert (
        "UpdateProcThreadAttribute",
        win32.PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE,
        CONSOLE,
    ) in kernel32.calls


def test_the_shell_starts_in_the_console_accounts_profile(tmp_path):
    kernel32 = FakeKernel32()
    channel = FakeChannel()
    channel.feed(("data", b"exit 0\r"))
    homes = {"alice": str(tmp_path)}
    platform = WindowsPlatform(
        seat=FakeSeat(["alice"]),
        powershell=lambda script, document: {
            "is_present": True,
            "home": homes[document["name"]],
        },
    )

    run_shell(kernel32, channel, platform=platform)

    assert kernel32.start_dir == str(tmp_path)


def test_with_nobody_signed_in_the_shell_starts_at_the_system_drives_root(
    monkeypatch,
):
    monkeypatch.setenv("SystemDrive", "D:")
    kernel32 = FakeKernel32()
    channel = FakeChannel()
    channel.feed(("data", b"exit 0\r"))
    platform = WindowsPlatform(seat=FakeSeat([]))

    run_shell(kernel32, channel, platform=platform)

    assert kernel32.start_dir == "D:\\"


def test_the_agents_standard_handles_are_set_aside_while_the_shell_is_made():
    kernel32 = FakeKernel32()
    channel = FakeChannel()
    channel.feed(("data", b"exit 0\r"))

    run_shell(kernel32, channel)

    assert set(kernel32.std_at_create.values()) == {None}
    assert kernel32.std == dict(zip(win32.STD_HANDLE_NAMES, STD_HANDLES))


def test_the_console_is_closed_and_every_handle_released_after_the_exit():
    kernel32 = FakeKernel32()
    channel = FakeChannel()
    channel.feed(("data", b"exit 0\r"))

    run_shell(kernel32, channel)

    assert kernel32.names().count("ClosePseudoConsole") == 1
    assert "DeleteProcThreadAttributeList" in kernel32.names()
    for handle in (JOB, PROCESS, THREAD):
        assert handle in kernel32.closed


def test_a_persistent_powershell_survives_its_stream_and_is_attached_again():
    kernel32 = FakeKernel32([b"PS C:\\> "])
    registry = ShellSessionRegistry()
    first = FakeChannel()
    outcome = {}

    def serve(channel, **args):
        stream = WindowsShellStream(
            channel,
            {"cols": 80, "rows": 24, "session_id": "tab-1", **args},
            kernel32=kernel32,
            sessions=registry,
            platform=FakePlatform(),
        )
        stream.open()
        outcome.clear()
        outcome.update(stream.run())

    thread = threading.Thread(target=serve, args=(first,))
    thread.start()
    time.sleep(0.1)
    registry.persist("tab-1", True)
    first.close_from_hub()
    thread.join(timeout=5)

    assert outcome == {"code": "", "params": {}}
    assert "TerminateProcess" not in kernel32.names()
    assert registry.describe()[0]["account"] == "SYSTEM"

    second = FakeChannel()
    second.feed(("data", b"exit 0\r"))
    serve(second, cols=100, rows=30, is_resumed=True)

    assert second.output() == b"PS C:\\> "
    assert kernel32.resizes == [(CONSOLE, 100, 31), (CONSOLE, 100, 30)]
    assert outcome == {"code": "", "params": {"exit_code": 0}}
    assert registry.describe() == []


def test_a_windows_without_a_pseudo_console_is_refused():
    stream = WindowsShellStream(FakeChannel(), {}, kernel32=NoConsoleKernel32())

    with pytest.raises(StreamRefused) as refused:
        stream.open()

    assert refused.value.code == "unsupported_platform"


def test_the_shell_kind_opens_powershell_on_windows(monkeypatch):
    monkeypatch.setattr(shell_module.sys, "platform", "win32")

    opened = shell_module.open_shell_stream(FakeChannel(), {"cols": 80, "rows": 24})

    assert type(opened) is WindowsShellStream


@pytest.mark.parametrize(
    "reported, command",
    [
        ("darwin", ["/bin/zsh", "-il"]),
        ("win32", ["powershell.exe", "-NoLogo"]),
    ],
)
def test_the_platform_names_its_own_shell(monkeypatch, reported, command):
    monkeypatch.setattr(shell_module.sys, "platform", reported)

    assert shell_module.shell_command() == command


def test_linux_runs_the_login_shell_interactively(monkeypatch):
    monkeypatch.setattr(shell_module.sys, "platform", "linux")

    assert shell_module.shell_command() == [shell_module.login_shell(), "-i"]


def terminal_settings(shell_path):
    from neutrino_agent.modules.terminal.config import TerminalConfig

    return lambda: TerminalConfig(shell_path=shell_path)


def test_the_terminal_modules_program_runs_as_system_in_place_of_powershell(
    tmp_path,
):
    program = tmp_path / "pwsh.exe"
    program.write_bytes(b"MZ")
    program.chmod(0o755)
    kernel32 = FakeKernel32()
    channel = FakeChannel()
    channel.feed(("data", b"exit 0\r"))
    stream = WindowsShellStream(
        channel,
        {"cols": 80, "rows": 24},
        kernel32=kernel32,
        platform=FakePlatform(),
        terminal=terminal_settings(str(program)),
    )

    stream.open()
    stream.run()

    create = next(call for call in kernel32.calls if call[0] == "CreateProcessW")
    assert str(program) in create[1]
    assert "powershell" not in create[1]
    assert stream._session.account == "SYSTEM"


def test_a_program_windows_cannot_run_refuses_the_open(tmp_path):
    stream = WindowsShellStream(
        FakeChannel(),
        {"cols": 80, "rows": 24},
        kernel32=FakeKernel32(),
        platform=FakePlatform(),
        terminal=terminal_settings(str(tmp_path / "gone.exe")),
    )

    with pytest.raises(StreamRefused) as refused:
        stream.open()

    assert (refused.value.code, refused.value.params) == (
        "shell_program_unusable",
        {"path": str(tmp_path / "gone.exe")},
    )


def test_an_exec_with_is_tty_runs_its_argv_on_the_console_headed_with_stdout():
    kernel32 = FakeKernel32([b"hi\r\n"])
    channel = FakeChannel()
    channel.feed(("eof",))
    channel.feed(("data", b"exit 4\r"))
    stream = WindowsShellStream(
        channel,
        {"cols": 100, "rows": 30},
        kernel32=kernel32,
        platform=FakePlatform(),
        terminal=terminal_settings("C:\\no\\such.exe"),
        argv=["sh", "-c", "echo hi"],
    )

    stream.open()
    closed = stream.run()

    create = next(call for call in kernel32.calls if call[0] == "CreateProcessW")
    assert create[1] == 'sh -c "echo hi"'
    assert ("CreatePseudoConsole", 100, 30) in kernel32.calls
    assert kernel32.start_dir == "C:\\Users\\alice"
    assert channel.sent == [b"\x01hi\r\n"]
    assert closed == {"code": "", "params": {"exit_code": 4}}
    assert stream._session.account == "SYSTEM"


def test_an_exec_whose_program_is_not_found_refuses_the_open():
    stream = WindowsShellStream(
        FakeChannel(),
        {"cols": 80, "rows": 24},
        kernel32=FakeKernel32(),
        platform=FakePlatform(),
        argv=["no-such-program-xyz"],
    )

    with pytest.raises(StreamRefused) as refused:
        stream.open()

    assert refused.value.params == {"path": "no-such-program-xyz"}
