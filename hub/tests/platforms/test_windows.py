"""The hub on Windows: its one service through a fake ``sc.exe``, the
elevation check, the file lock and the job its children run in."""

import subprocess
import sys
import types

import pytest

from neutrino_hub.platforms import windows
from neutrino_hub.platforms.windows import WindowsHubPlatform
from tests.conftest import FakeServiceControlManager


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
