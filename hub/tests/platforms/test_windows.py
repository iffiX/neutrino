"""The hub on Windows: its one service through a fake ``sc.exe``, the
elevation check, the file lock and the job its children run in."""

import subprocess
import sys
import types

import pytest

from neutrino_hub.platforms import windows
from neutrino_hub.platforms.windows import WindowsHubPlatform
from tests.conftest import FakePowerShell, FakeServiceControlManager


@pytest.fixture
def manager(monkeypatch):
    fake = FakeServiceControlManager()
    monkeypatch.setattr(windows.subprocess, "run", fake)
    return fake


def _platform(**keywords) -> WindowsHubPlatform:
    return WindowsHubPlatform(sleep=lambda seconds: None, **keywords)


def test_a_stopped_service_reads_stopped(manager):
    assert _platform().service_state() == "stopped"
    assert manager.calls == [["sc.exe", "query", "neutrino_hub"]]


def test_starting_asks_the_manager(manager):
    _platform().start_service()

    assert manager.calls == [["sc.exe", "start", "neutrino_hub"]]


def test_a_refused_start_is_raised(manager):
    manager.is_refusing = True

    with pytest.raises(subprocess.CalledProcessError):
        _platform().start_service()


def test_stopping_waits_out_the_pending_state(manager):
    manager.is_running = True

    _platform().stop_service()

    assert manager.calls == [
        ["sc.exe", "query", "neutrino_hub"],
        ["sc.exe", "stop", "neutrino_hub"],
        ["sc.exe", "query", "neutrino_hub"],
        ["sc.exe", "query", "neutrino_hub"],
    ]


def test_a_stop_that_sc_does_not_answer_in_time_is_waited_for_by_query(manager):
    manager.is_running = True
    manager.is_stop_slow = True

    _platform().stop_service()

    assert manager.calls[-1] == ["sc.exe", "query", "neutrino_hub"]
    assert not manager.is_running


def test_a_service_already_stopping_is_only_waited_for(monkeypatch):
    answers = iter(["STATE : 3  STOP_PENDING", "STATE : 1  STOPPED"])
    calls = []

    def stopping(command, **keywords):
        calls.append(list(command))
        return subprocess.CompletedProcess([], 0, stdout=next(answers))

    monkeypatch.setattr(windows.subprocess, "run", stopping)

    _platform().stop_service()

    assert calls == [["sc.exe", "query", "neutrino_hub"]] * 2


def test_a_service_that_never_stops_is_a_timeout(monkeypatch):
    def stuck(command, **keywords):
        return subprocess.CompletedProcess([], 0, stdout="STATE : 3  STOP_PENDING")

    monkeypatch.setattr(windows.subprocess, "run", stuck)

    with pytest.raises(TimeoutError):
        _platform().stop_service()


def test_restarting_stops_then_starts(manager):
    manager.is_running = True

    _platform().restart_service()

    assert manager.calls[1] == ["sc.exe", "stop", "neutrino_hub"]
    assert manager.calls[-1] == ["sc.exe", "start", "neutrino_hub"]


class _Shell32:
    def __init__(self, answer: int):
        self.answer = answer

    def IsUserAnAdmin(self) -> int:
        return self.answer


@pytest.mark.parametrize(("answer", "expected"), [(1, True), (0, False)])
def test_elevation_is_is_user_an_admin(answer, expected):
    libraries = types.SimpleNamespace(shell32=_Shell32(answer))

    assert _platform(libraries=libraries).is_elevated() is expected


def test_no_shell32_is_not_elevated():
    assert not _platform(libraries=types.SimpleNamespace()).is_elevated()


def test_the_hint_names_an_administrator_powershell():
    assert _platform().elevation_hint("setup") == (
        "nhub setup   (in an administrator PowerShell)"
    )


class _Msvcrt:
    LK_NBLCK = 2
    LK_UNLCK = 0

    def __init__(self):
        self.held = False
        self.calls = []

    def locking(self, descriptor, mode, size):
        self.calls.append((mode, size))
        if mode == self.LK_NBLCK:
            if self.held:
                raise OSError(36, "locked")
            self.held = True
        else:
            self.held = False


def test_the_file_lock_is_msvcrt_locking(monkeypatch, tmp_path):
    msvcrt = _Msvcrt()
    monkeypatch.setitem(sys.modules, "msvcrt", msvcrt)
    path = tmp_path / "router.lock"
    path.write_text("")
    import os

    descriptor = os.open(path, os.O_RDWR)
    try:
        platform = _platform()
        assert platform.try_lock(descriptor)
        assert not platform.try_lock(descriptor)
        platform.unlock(descriptor)
        assert platform.try_lock(descriptor)
    finally:
        os.close(descriptor)
    assert msvcrt.calls[0] == (2, 1)


class _Kernel32:
    def __init__(self):
        self.jobs = 0
        self.assigned = []

    def CreateJobObjectW(self, attributes, name):
        self.jobs += 1
        return 4242

    def SetInformationJobObject(self, job, kind, limits, size):
        return 1

    def AssignProcessToJobObject(self, job, process):
        self.assigned.append((job, process))
        return 1

    def CloseHandle(self, handle):
        return 1


def test_every_child_joins_one_kill_on_close_job():
    kernel32 = _Kernel32()
    platform = _platform(libraries=types.SimpleNamespace(kernel32=kernel32))

    platform.tie_to_service(types.SimpleNamespace(_handle=11))
    platform.tie_to_service(types.SimpleNamespace(_handle=12))

    assert kernel32.jobs == 1
    assert kernel32.assigned == [(4242, 11), (4242, 12)]


def test_the_agent_package_installs_quietly_with_msiexec():
    assert _platform().agent_install_command("C:\\cache\\agent.msi") == [
        "msiexec",
        "/i",
        "C:\\cache\\agent.msi",
        "/qn",
        "/norestart",
    ]


def test_netbird_answers_on_a_loopback_port_of_the_hubs_own():
    assert _platform().netbird_daemon_address() == "tcp://127.0.0.1:41732"


def test_children_start_with_no_console_window(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "neutrino_hub.system.constants.SYSTEM_CHILD_LOG_DIR", tmp_path, raising=True
    )
    controller = _platform().process_controller()

    assert controller._supervisor._creation_flags == 0x08000000


class _ElevatingShell32:
    """ShellExecuteExW, answering for a prompt the person accepts or declines."""

    def __init__(self, *, is_accepted: bool = True):
        self.is_accepted = is_accepted
        self.started = []

    def IsUserAnAdmin(self) -> int:
        return 0

    def ShellExecuteExW(self, pointer) -> int:
        info = pointer._obj
        self.started.append(
            (info.lpVerb, info.lpFile, info.lpParameters, info.nShow, info.fMask)
        )
        if not self.is_accepted:
            return 0
        info.hProcess = 77
        return 1


class _WaitingKernel32:
    def __init__(self, exit_code: int):
        self.exit_code = exit_code
        self.calls = []

    def WaitForSingleObject(self, handle, timeout):
        self.calls.append(("wait", handle, timeout))
        return 0

    def GetExitCodeProcess(self, handle, pointer):
        pointer._obj.value = self.exit_code
        return 1

    def CloseHandle(self, handle):
        self.calls.append(("close", handle))
        return 1


@pytest.mark.parametrize(("exit_code", "expected"), [(0, True), (1, False)])
def test_the_elevated_step_runs_behind_uac_and_is_waited_for(
    monkeypatch, exit_code, expected
):
    shell32 = _ElevatingShell32()
    kernel32 = _WaitingKernel32(exit_code)
    platform = _platform(
        libraries=types.SimpleNamespace(shell32=shell32, kernel32=kernel32)
    )
    monkeypatch.setattr(
        WindowsHubPlatform,
        "hub_command",
        lambda self, *arguments: [
            "C:\\Program Files\\Neutrino\\hub\\nhub.exe",
            *arguments,
        ],
    )

    assert platform.run_elevated(["open", "--output", "C:\\Temp\\a b"]) is expected
    ((verb, program, parameters, show, mask),) = shell32.started
    assert verb == "runas"
    assert program == "C:\\Program Files\\Neutrino\\hub\\nhub.exe"
    assert parameters == 'open --output "C:\\Temp\\a b"'
    assert show == windows.win32.SW_HIDE
    assert mask & windows.win32.SEE_MASK_NOCLOSEPROCESS
    assert kernel32.calls == [("wait", 77, windows.win32.INFINITE), ("close", 77)]


def test_a_declined_uac_prompt_is_not_a_run():
    shell32 = _ElevatingShell32(is_accepted=False)
    platform = _platform(
        libraries=types.SimpleNamespace(shell32=shell32, kernel32=_WaitingKernel32(0))
    )

    assert not platform.run_elevated(["open"])


def test_an_elevated_process_hands_the_page_to_the_shell(monkeypatch):
    started = []
    monkeypatch.setattr(windows.subprocess, "Popen", started.append)
    platform = _platform(libraries=types.SimpleNamespace(shell32=_Shell32(1)))

    assert platform.open_browser("http://127.0.0.1:8080/")
    assert started == [["explorer.exe", "http://127.0.0.1:8080/"]]


class _Loop:
    def __init__(self):
        self.passed = []
        self.handler = None

    def default_exception_handler(self, context):
        self.passed.append(context)

    def set_exception_handler(self, handler):
        self.handler = handler


def test_a_connection_the_browser_reset_is_not_logged():
    loop = _Loop()
    context = {
        "message": "Exception in callback "
        "_ProactorBasePipeTransport._call_connection_lost(None)",
        "exception": ConnectionResetError(10054, "reset by peer"),
        "handle": "<Handle _ProactorBasePipeTransport._call_connection_lost(None)>",
    }

    windows.drop_connection_reset(loop, context)

    assert loop.passed == []


@pytest.mark.parametrize(
    "context",
    [
        {"message": "elsewhere", "exception": ConnectionResetError(10054, "reset")},
        {
            "message": "_call_connection_lost",
            "exception": ValueError("a fault"),
        },
    ],
)
def test_every_other_loop_exception_reaches_the_default_handler(context):
    loop = _Loop()

    windows.drop_connection_reset(loop, context)

    assert loop.passed == [context]


@pytest.mark.parametrize(
    ("system", "is_installed"), [("win32", True), ("linux", False)]
)
def test_the_handler_is_installed_on_windows_alone(monkeypatch, system, is_installed):
    loop = _Loop()
    monkeypatch.setattr(sys, "platform", system)

    windows.quiet_connection_resets(loop)

    assert (loop.handler is windows.drop_connection_reset) is is_installed


def test_the_systems_resolvers_are_every_connected_adapters(monkeypatch):
    shell = FakePowerShell(
        {
            windows.PLATFORM_WINDOWS_RESOLVERS_SCRIPT: {
                "servers": [
                    "192.168.1.1",
                    "127.0.0.1",
                    "x",
                    "192.0.2.53",
                    "192.168.1.1",
                ]
            }
        }
    )
    monkeypatch.setattr(windows, "run_powershell", shell)

    assert WindowsHubPlatform().system_resolvers() == ["192.168.1.1", "192.0.2.53"]


def test_one_resolver_comes_back_bare_and_reads_the_same(monkeypatch):
    shell = FakePowerShell(
        {windows.PLATFORM_WINDOWS_RESOLVERS_SCRIPT: {"servers": "192.168.1.1"}}
    )
    monkeypatch.setattr(windows, "run_powershell", shell)

    assert WindowsHubPlatform().system_resolvers() == ["192.168.1.1"]


def test_powershell_that_does_not_answer_names_no_resolver(monkeypatch):
    monkeypatch.setattr(
        windows, "run_powershell", FakePowerShell(error=OSError("powershell exited 1"))
    )

    assert WindowsHubPlatform().system_resolvers() == []
