"""A shell on a pseudo console as an enabled account, served through fakes.

The fake kernel32 plays the console and the shell: the output it was
scripted with is what ReadFile hands back, the bytes written to the
console's input are recorded, and the shell exits when it is told ``exit``
or terminated. A fake logon stands in for the account's: it records the
password it was opened with and the process it starts. What these pin: the
console's output arrives as bytes and the exit code closes the stream, the
hub's bytes reach the console, a resize resizes the console, a close from
the hub terminates the shell and closes its job, the shell starts suspended
under the account's logon with the agent's standard handles set aside and
is resumed only once it is in the job, it starts in the account's profile
directory, the logon is closed once the shell has ended, and a Windows
without a pseudo console is refused. The account: the open's or the first
enabled one, PowerShell or the row's program, and every refusal
(``terminal_account_missing``, ``account_not_enabled``,
``account_unknown``, ``credential_missing``, ``credential_invalid``,
``shell_program_unusable``) with nothing started. A container's shell runs
``exec -it`` through the Podman machine's read command on the console as
the agent, never kept, with its own mark and the sweep run through the same
command once it exits, and a container the machine does not list is
refused before anything starts.
"""

import ctypes
import subprocess
import threading
import time
import types

import pytest

from neutrino_agent.exceptions import ModuleApplyError, StreamRefused
from neutrino_agent.modules.terminal.config import TerminalAccount, TerminalConfig
from neutrino_agent.platforms import win32
from neutrino_agent.streams import shell as shell_module
from neutrino_agent.streams import windows_shell
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


class FakeLogon:
    """An account's logon: records how it was opened and what it started."""

    made: list = []
    refusal = None

    def __init__(self, account, password, *, kernel32=None):
        self.account = account
        self.password = password
        self.kernel32 = kernel32
        self.is_closed = False
        FakeLogon.made.append(self)

    def open(self):
        if FakeLogon.refusal is not None:
            raise FakeLogon.refusal

    def start(self, command_line, *, start_dir, startup, flags):
        kernel32 = self.kernel32
        kernel32.std_at_create = dict(kernel32.std)
        kernel32.start_dir = start_dir
        kernel32.calls.append(("CreateProcessAsUserW", command_line, flags))
        process = win32.ProcessInformation()
        process.hProcess = PROCESS
        process.hThread = THREAD
        return process

    def close(self):
        self.is_closed = True


@pytest.fixture(autouse=True)
def windows_accounts(monkeypatch):
    """Every account but ``ghost`` exists, and no logon is refused."""

    def account_sid(account):
        if account == "ghost":
            raise KeyError(account)
        return "S-1-5-21-1"

    monkeypatch.setattr(windows_shell, "account_sid", account_sid)
    FakeLogon.made = []
    FakeLogon.refusal = None


class FakePlatform:
    """A platform that names each account's profile and the drive's root."""

    def account_home(self, account):
        return f"C:\\Users\\{account}"

    def shell_start_dir(self):
        return "C:\\"


def enabled(*accounts) -> TerminalConfig:
    """The Terminal module's settings with these accounts enabled."""
    return TerminalConfig(
        accounts=[
            (
                each
                if isinstance(each, TerminalAccount)
                else TerminalAccount(each, password="pw")
            )
            for each in accounts
        ]
    )


def account_stream(kernel32, channel, *, settings=None, sessions=None, **args):
    return WindowsShellStream(
        channel,
        {"cols": 80, "rows": 24, **args},
        kernel32=kernel32,
        platform=FakePlatform(),
        terminal=lambda: settings if settings is not None else enabled("alice"),
        sessions=sessions,
        logon_class=lambda account, password: FakeLogon(
            account, password, kernel32=kernel32
        ),
    )


def run_shell(kernel32, channel, **args):
    stream = account_stream(kernel32, channel, **args)
    stream.open()
    return stream.run()


def created(kernel32):
    return next(call for call in kernel32.calls if call[0] == "CreateProcessAsUserW")


def test_the_consoles_output_arrives_as_bytes_and_the_exit_code_closes():
    kernel32 = FakeKernel32([b"PS C:\\> ", b"hello\r\n"])
    channel = FakeChannel()
    channel.feed(("data", b"exit 3\r"))

    closed = run_shell(kernel32, channel)

    assert channel.output() == b"PS C:\\> hello\r\n"
    assert closed == {"code": "", "params": {"exit_code": 3}}


def test_the_first_size_is_the_consoles():
    kernel32 = FakeKernel32()
    channel = FakeChannel()
    channel.feed(("data", b"exit 0\r"))

    run_shell(kernel32, channel, cols=132, rows=50)

    assert ("CreatePseudoConsole", 132, 50) in kernel32.calls


def test_the_hubs_bytes_reach_the_console():
    kernel32 = FakeKernel32()
    channel = FakeChannel()
    channel.feed(("data", b"Get-Date\r"))
    channel.feed(("data", b"exit 0\r"))

    run_shell(kernel32, channel)

    assert kernel32.written == [b"Get-Date\r", b"exit 0\r"]


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


def test_powershell_starts_suspended_under_the_logon_and_is_resumed_once_in_the_job():
    kernel32 = FakeKernel32()
    channel = FakeChannel()
    channel.feed(("data", b"exit 0\r"))

    run_shell(kernel32, channel)

    create = created(kernel32)
    assert create[1] == "powershell.exe -NoLogo"
    assert create[2] & win32.EXTENDED_STARTUPINFO_PRESENT
    assert create[2] & win32.CREATE_SUSPENDED
    assert "CreateProcessW" not in kernel32.names()
    names = kernel32.names()
    assert names.index("CreateProcessAsUserW") < names.index("AssignProcessToJobObject")
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


def test_the_shell_runs_as_the_first_enabled_account_in_its_profile():
    kernel32 = FakeKernel32()
    channel = FakeChannel()
    channel.feed(("data", b"exit 0\r"))
    stream = account_stream(
        kernel32,
        channel,
        settings=enabled(TerminalAccount("alice", password="a-pw"), "bob"),
    )

    stream.open()
    stream.run()

    (logon,) = FakeLogon.made
    assert (logon.account, logon.password) == ("alice", "a-pw")
    assert kernel32.start_dir == "C:\\Users\\alice"
    assert stream._session.account == "alice"
    assert logon.is_closed


def test_the_shell_runs_as_the_account_the_open_names():
    kernel32 = FakeKernel32()
    channel = FakeChannel()
    channel.feed(("data", b"exit 0\r"))
    stream = account_stream(
        kernel32, channel, settings=enabled("alice", "bob"), account="bob"
    )

    stream.open()
    stream.run()

    assert [logon.account for logon in FakeLogon.made] == ["bob"]
    assert kernel32.start_dir == "C:\\Users\\bob"


@pytest.mark.parametrize(
    "settings, account, code, params",
    [
        (enabled(), "", "terminal_account_missing", {}),
        (enabled("alice"), "bob", "account_not_enabled", {"account": "bob"}),
        (enabled("ghost"), "", "account_unknown", {"account": "ghost"}),
        (
            enabled(TerminalAccount("alice")),
            "",
            "credential_missing",
            {"account": "alice"},
        ),
    ],
)
def test_an_account_that_cannot_run_a_shell_is_refused_with_nothing_started(
    settings, account, code, params
):
    kernel32 = FakeKernel32()
    stream = account_stream(kernel32, FakeChannel(), settings=settings, account=account)

    with pytest.raises(StreamRefused) as refused:
        stream.open()

    assert (refused.value.code, refused.value.params) == (code, params)
    assert FakeLogon.made == []
    assert "CreatePseudoConsole" not in kernel32.names()


def test_a_password_windows_refuses_is_credential_invalid():
    FakeLogon.refusal = ModuleApplyError("credential_invalid", {"account": "alice"})
    kernel32 = FakeKernel32()
    stream = account_stream(kernel32, FakeChannel())

    with pytest.raises(StreamRefused) as refused:
        stream.open()

    assert (refused.value.code, refused.value.params) == (
        "credential_invalid",
        {"account": "alice"},
    )
    assert "CreatePseudoConsole" not in kernel32.names()


def test_a_logon_windows_does_not_grant_closes_as_a_failed_shell():
    FakeLogon.refusal = OSError("logon type not granted")
    stream = account_stream(FakeKernel32(), FakeChannel())

    with pytest.raises(StreamRefused) as refused:
        stream.open()

    assert refused.value.code == "shell_failed"


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
    assert all(logon.is_closed for logon in FakeLogon.made)


def test_a_persistent_shell_survives_its_stream_and_is_attached_again():
    kernel32 = FakeKernel32([b"PS C:\\> "])
    registry = ShellSessionRegistry()
    first = FakeChannel()
    outcome = {}

    def serve(channel, **args):
        stream = account_stream(
            kernel32, channel, sessions=registry, session_id="tab-1", **args
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
    assert registry.describe()[0]["account"] == "alice"

    second = FakeChannel()
    second.feed(("data", b"exit 0\r"))
    serve(second, cols=100, rows=30, is_resumed=True)

    assert second.output() == b"PS C:\\> "
    assert kernel32.resizes == [(CONSOLE, 100, 31), (CONSOLE, 100, 30)]
    assert outcome == {"code": "", "params": {"exit_code": 0}}
    assert registry.describe() == []
    assert len(FakeLogon.made) == 1


def test_a_windows_without_a_pseudo_console_is_refused():
    stream = WindowsShellStream(FakeChannel(), {}, kernel32=NoConsoleKernel32())

    with pytest.raises(StreamRefused) as refused:
        stream.open()

    assert refused.value.code == "unsupported_platform"


def test_the_shell_kind_opens_a_console_shell_on_windows(monkeypatch):
    monkeypatch.setattr(shell_module.sys, "platform", "win32")

    opened = shell_module.open_shell_stream(FakeChannel(), {"cols": 80, "rows": 24})

    assert type(opened) is WindowsShellStream


def test_the_accounts_own_program_runs_in_place_of_powershell(tmp_path):
    program = tmp_path / "pwsh.exe"
    program.write_bytes(b"MZ")
    kernel32 = FakeKernel32()
    channel = FakeChannel()
    channel.feed(("data", b"exit 0\r"))
    stream = account_stream(
        kernel32,
        channel,
        settings=enabled(TerminalAccount("alice", str(program), "pw")),
    )

    stream.open()
    stream.run()

    assert str(program) in created(kernel32)[1]
    assert "powershell" not in created(kernel32)[1]
    assert stream._session.account == "alice"


def test_a_program_windows_cannot_run_refuses_the_open(tmp_path):
    kernel32 = FakeKernel32()
    stream = account_stream(
        kernel32,
        FakeChannel(),
        settings=enabled(TerminalAccount("alice", str(tmp_path / "gone.exe"), "pw")),
    )

    with pytest.raises(StreamRefused) as refused:
        stream.open()

    assert (refused.value.code, refused.value.params) == (
        "shell_program_unusable",
        {"path": str(tmp_path / "gone.exe")},
    )
    assert FakeLogon.made == []


def test_an_exec_with_is_tty_runs_its_argv_on_the_console_as_the_account():
    kernel32 = FakeKernel32([b"hi\r\n"])
    channel = FakeChannel()
    channel.feed(("eof",))
    channel.feed(("data", b"exit 4\r"))
    stream = WindowsShellStream(
        channel,
        {"cols": 100, "rows": 30},
        kernel32=kernel32,
        platform=FakePlatform(),
        terminal=lambda: enabled(TerminalAccount("alice", "C:\\no\\such.exe", "pw")),
        argv=["sh", "-c", "echo hi"],
        logon_class=lambda account, password: FakeLogon(
            account, password, kernel32=kernel32
        ),
    )

    stream.open()
    closed = stream.run()

    assert created(kernel32)[1] == 'sh -c "echo hi"'
    assert ("CreatePseudoConsole", 100, 30) in kernel32.calls
    assert kernel32.start_dir == "C:\\Users\\alice"
    assert channel.sent == [b"hi\r\n"]
    assert closed == {"code": "", "params": {"exit_code": 4}}
    assert stream._session.account == "alice"


def test_an_exec_whose_program_is_not_found_refuses_the_open():
    stream = WindowsShellStream(
        FakeChannel(),
        {"cols": 80, "rows": 24},
        kernel32=FakeKernel32(),
        platform=FakePlatform(),
        terminal=lambda: enabled("alice"),
        argv=["no-such-program-xyz"],
        logon_class=FakeLogon,
    )

    with pytest.raises(StreamRefused) as refused:
        stream.open()

    assert refused.value.params == {"path": "no-such-program-xyz"}
    assert FakeLogon.made == []


# What reaches root's Podman in the account's WSL machine.
MACHINE_URL = "ssh://root@127.0.0.1:50743/run/podman/podman.sock"
MACHINE_KEY = "C:\\Users\\lab\\.local\\share\\containers\\podman\\machine\\machine"


def containers_on_windows(monkeypatch, tmp_path, kernel32, listed):
    """The ``shell`` entry as Windows takes it, its podman a file in ``tmp_path``.

    Returns:
        The machine's read command, and the commands the listing was given.
    """
    program = tmp_path / "podman.exe"
    program.write_bytes(b"MZ")
    program.chmod(0o755)
    asked = []

    def listing(podman):
        asked.append(podman)
        return list(listed)

    monkeypatch.setattr(shell_module, "sys", types.SimpleNamespace(platform="win32"))
    monkeypatch.setattr(shell_module, "listed_containers", listing)
    monkeypatch.setattr(
        win32, "libraries", lambda: types.SimpleNamespace(kernel32=kernel32)
    )
    return (str(program), "--url", MACHINE_URL, "--identity", MACHINE_KEY), asked


def test_a_containers_shell_runs_exec_on_the_console_as_the_agent(
    monkeypatch, tmp_path
):
    kernel32 = FakeKernel32([b"/ # "])
    read, asked = containers_on_windows(monkeypatch, tmp_path, kernel32, ["probe"])
    swept = threading.Event()
    sweeps = []

    def sweep(command, **options):
        sweeps.append((command, options))
        swept.set()

    monkeypatch.setattr(shell_module, "run", sweep)
    registry = ShellSessionRegistry()
    channel = FakeChannel()
    channel.feed(("data", b"exit 0\r"))

    stream = shell_module.open_shell_stream(
        channel,
        {
            "module": "podman",
            "container": "probe",
            "cols": 100,
            "rows": 30,
            "session_id": "tab-1",
        },
        sessions=registry,
        platform=FakePlatform(),
        container_podman=lambda: read,
    )
    stream.open()
    closed = stream.run()

    create = next(call for call in kernel32.calls if call[0] == "CreateProcessW")
    mark = stream._argv[len(read) + 3]
    assert type(stream) is WindowsShellStream
    assert asked == [read]
    assert mark.startswith(f"{shell_module.CONTAINER_SHELL_MARK}=")
    assert create[1] == subprocess.list2cmdline(
        [
            *read,
            "exec",
            "-it",
            "-e",
            mark,
            "probe",
            "sh",
            "-c",
            shell_module.CONTAINER_SHELL_COMMAND,
        ]
    )
    assert ("CreatePseudoConsole", 100, 30) in kernel32.calls
    assert channel.sent == [b"/ # "]
    assert closed == {"code": "", "params": {"exit_code": 0}}
    assert stream._session.account == "SYSTEM"
    assert registry.describe() == []
    assert swept.wait(timeout=5)
    assert sweeps[0][0] == [
        *read,
        "exec",
        "probe",
        "sh",
        "-c",
        shell_module.CONTAINER_SHELL_SWEEP,
        "sh",
        mark,
    ]


def test_a_container_the_machine_does_not_list_is_refused_on_windows(
    monkeypatch, tmp_path
):
    kernel32 = FakeKernel32()
    read, _asked = containers_on_windows(monkeypatch, tmp_path, kernel32, ["web"])

    with pytest.raises(StreamRefused) as refused:
        shell_module.open_shell_stream(
            FakeChannel(),
            {"module": "podman", "container": "probe"},
            platform=FakePlatform(),
            container_podman=lambda: read,
        )

    assert (refused.value.code, refused.value.params) == (
        "container_unknown",
        {"name": "probe"},
    )
    assert "CreateProcessW" not in kernel32.names()
