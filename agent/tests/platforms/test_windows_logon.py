"""An account logged on with its password, and processes started under it, through fakes.

What these pin: the logon tries an interactive logon and then a batch one,
a wrong password is ``credential_invalid`` with no second try, the profile
is loaded and the environment made under the token, a process starts with
``CreateProcessAsUserW`` on a window station of its own logon session with
the account's environment, and closing releases the environment, the
profile and the token. A command on three pipes: each pipe's own end alone
stays out of the process's reach, the process is handed exactly its three
ends, starts suspended and is resumed once in a kill-on-close job, its
exit code is read on its end, and ending it closes its job.
"""

import ctypes
import os

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.platforms import win32
from neutrino_agent.platforms.windows_logon import (
    WindowsAccountLogon,
    WindowsAccountPipeProcess,
)

TOKEN_BASE = 0x700
PROFILE = 0x800
ENVIRONMENT = 0x900
PROCESS = 0x60
THREAD = 0x61
JOB = 0x70


def win_error(number: int) -> OSError:
    error = OSError(number, "fake")
    error.winerror = number
    return error


class FakeAdvapi32:
    def __init__(self, refused=None):
        self.refused = dict(refused or {})
        self.calls: list = []
        self.error = None

    def LogonUserW(self, account, domain, password, kind, provider, token):
        self.calls.append(("logon", account, domain, password, kind))
        if kind in self.refused:
            self.error = win_error(self.refused[kind])
            return 0
        token._obj.value = TOKEN_BASE + kind
        return 1

    def CreateProcessAsUserW(self, token, application, command_line, *rest):
        _, _, inherit, flags, environment, start_dir, startup, process = rest
        record = startup._obj
        record = record.StartupInfo if hasattr(record, "StartupInfo") else record
        self.calls.append(
            (
                "create",
                token.value,
                command_line,
                bool(inherit),
                flags,
                environment.value,
                start_dir,
                record.lpDesktop,
            )
        )
        process._obj.hProcess = PROCESS
        process._obj.hThread = THREAD
        return 1


class FakeUserenv:
    def __init__(self):
        self.calls: list = []

    def LoadUserProfileW(self, token, profile):
        self.calls.append(
            ("load", token.value, profile._obj.lpUserName, profile._obj.dwFlags)
        )
        profile._obj.hProfile = PROFILE
        return 1

    def CreateEnvironmentBlock(self, environment, token, is_inheriting):
        self.calls.append(("environment", token.value, bool(is_inheriting)))
        environment._obj.value = ENVIRONMENT
        return 1

    def DestroyEnvironmentBlock(self, environment):
        self.calls.append(("destroy", environment.value))
        return 1

    def UnloadUserProfile(self, token, profile):
        self.calls.append(("unload", token.value, profile))
        return 1


class FakeKernel32:
    def __init__(self, exit_code=0):
        self.calls: list = []
        self.closed: list = []
        self.next_handle = 0x100
        self.exit_code = exit_code
        self.handed: list = []

    def CloseHandle(self, handle):
        self.closed.append(getattr(handle, "value", handle))
        return 1

    def CreatePipe(self, read, write, attributes, size):
        assert attributes._obj.bInheritHandle
        self.next_handle += 2
        read._obj.value = self.next_handle
        write._obj.value = self.next_handle + 1
        return 1

    def SetHandleInformation(self, handle, mask, flags):
        self.calls.append(("not_inherited", handle.value, mask, flags))
        return 1

    def InitializeProcThreadAttributeList(self, attributes, count, flags, size):
        size._obj.value = 48
        return 1

    def UpdateProcThreadAttribute(self, attributes, flags, name, value, size, *rest):
        handles = ctypes.cast(value, ctypes.POINTER(ctypes.c_void_p * 3)).contents
        self.handed = [handle for handle in handles]
        self.calls.append(("handle_list", name, size))
        return 1

    def DeleteProcThreadAttributeList(self, attributes):
        self.calls.append(("delete_list",))

    def CreateJobObjectW(self, attributes, name):
        return JOB

    def SetInformationJobObject(self, job, information_class, limits, size):
        flags = limits._obj.BasicLimitInformation.LimitFlags
        self.calls.append(("job_limits", flags))
        return 1

    def AssignProcessToJobObject(self, job, process):
        self.calls.append(("assign", job, process))
        return 1

    def ResumeThread(self, thread):
        self.calls.append(("resume", thread))
        return 1

    def WaitForSingleObject(self, handle, milliseconds):
        return win32.WAIT_OBJECT_0

    def GetExitCodeProcess(self, handle, code):
        code._obj.value = self.exit_code
        return 1

    def TerminateProcess(self, handle, code):
        self.calls.append(("terminate", handle, code))
        return 1


def logon_of(advapi32=None, userenv=None, kernel32=None):
    return WindowsAccountLogon(
        "ann",
        "pw",
        advapi32=advapi32 or FakeAdvapi32(),
        kernel32=kernel32 or FakeKernel32(),
        userenv=userenv or FakeUserenv(),
    )


def test_an_interactive_logon_loads_the_profile_and_the_environment():
    advapi32, userenv = FakeAdvapi32(), FakeUserenv()
    logon = logon_of(advapi32, userenv)

    logon.open()

    token = TOKEN_BASE + win32.LOGON32_LOGON_INTERACTIVE
    assert advapi32.calls == [
        ("logon", "ann", ".", "pw", win32.LOGON32_LOGON_INTERACTIVE)
    ]
    assert userenv.calls == [
        ("load", token, "ann", win32.PI_NOUI),
        ("environment", token, False),
    ]


def test_a_batch_logon_is_tried_when_an_interactive_one_is_not_granted(monkeypatch):
    advapi32 = FakeAdvapi32({win32.LOGON32_LOGON_INTERACTIVE: 1385})
    monkeypatch.setattr(win32, "last_error", lambda: advapi32.error)
    logon = logon_of(advapi32)

    logon.open()

    assert [call[-1] for call in advapi32.calls] == [
        win32.LOGON32_LOGON_INTERACTIVE,
        win32.LOGON32_LOGON_BATCH,
    ]


def test_a_wrong_password_is_credential_invalid_with_no_second_try(monkeypatch):
    advapi32 = FakeAdvapi32({win32.LOGON32_LOGON_INTERACTIVE: 1326})
    monkeypatch.setattr(win32, "last_error", lambda: advapi32.error)

    with pytest.raises(ModuleApplyError) as refused:
        logon_of(advapi32).open()

    assert (refused.value.code, refused.value.params) == (
        "credential_invalid",
        {"account": "ann"},
    )
    assert len(advapi32.calls) == 1


def test_a_process_starts_as_the_account_on_its_own_window_station():
    advapi32 = FakeAdvapi32()
    logon = logon_of(advapi32)
    logon.open()
    startup = win32.StartupInfoEx()

    process = logon.start(
        "powershell.exe -NoLogo",
        start_dir="C:\\Users\\ann",
        startup=startup,
        flags=win32.CREATE_SUSPENDED,
    )

    assert (process.hProcess, process.hThread) == (PROCESS, THREAD)
    assert advapi32.calls[-1] == (
        "create",
        TOKEN_BASE + win32.LOGON32_LOGON_INTERACTIVE,
        "powershell.exe -NoLogo",
        False,
        win32.CREATE_SUSPENDED | win32.CREATE_UNICODE_ENVIRONMENT,
        ENVIRONMENT,
        "C:\\Users\\ann",
        "",
    )


def test_closing_releases_the_environment_the_profile_and_the_token():
    userenv, kernel32 = FakeUserenv(), FakeKernel32()
    logon = logon_of(userenv=userenv, kernel32=kernel32)
    logon.open()

    logon.close()
    logon.close()

    token = TOKEN_BASE + win32.LOGON32_LOGON_INTERACTIVE
    assert userenv.calls[2:] == [("destroy", ENVIRONMENT), ("unload", token, PROFILE)]
    assert kernel32.closed == [token]


def test_a_command_runs_on_three_pipes_handed_to_it_alone_in_a_job(tmp_path):
    kernel32 = FakeKernel32(exit_code=7)
    advapi32 = FakeAdvapi32()
    logon = logon_of(advapi32=advapi32, kernel32=kernel32)
    logon.open()
    files = []

    def open_handle(handle, flags):
        path = tmp_path / f"h{handle}"
        path.write_bytes(b"")
        files.append(handle)
        return os.open(path, os.O_RDWR)

    process = WindowsAccountPipeProcess(
        logon,
        ["cmd.exe", "/c", "echo hi"],
        start_dir="C:\\Users\\ann",
        kernel32=kernel32,
        open_handle=open_handle,
    )

    create = advapi32.calls[-1]
    assert create[2] == 'cmd.exe /c "echo hi"'
    assert create[3] is True
    assert create[4] & win32.EXTENDED_STARTUPINFO_PRESENT
    assert create[4] & win32.CREATE_SUSPENDED
    assert create[4] & win32.CREATE_NO_WINDOW
    parents = [0x102 + 1, 0x104, 0x106]
    children = [0x102, 0x104 + 1, 0x106 + 1]
    assert files == parents
    assert kernel32.handed == children
    assert [call[1] for call in kernel32.calls if call[0] == "not_inherited"] == parents
    assert all(child in kernel32.closed for child in children)
    names = [call[0] for call in kernel32.calls]
    assert names.index("assign") < names.index("resume")
    assert ("job_limits", win32.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE) in kernel32.calls
    assert process.poll() == 7
    assert process.end() == 7
    assert JOB in kernel32.closed and PROCESS in kernel32.closed
    for stream in (process.stdin, process.stdout, process.stderr):
        stream.close()
