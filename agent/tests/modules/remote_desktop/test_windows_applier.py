"""The agent's RustDesk on Windows: the ``RustDesk`` service running the
agent's copy, what is kept of one found before, and what is never ended."""

import json

import pytest

from neutrino_agent.modules.remote_desktop import windows_applier
from neutrino_agent.modules.remote_desktop.windows_applier import (
    RemoteDesktopWindowsApplier,
    image_path,
    is_viewer_command,
    listening_pids,
)
from neutrino_agent.modules.subprocess_run import CommandResult

COPY = "C:\\Program Files\\Neutrino\\agent\\rustdesk\\rustdesk.exe"
UPSTREAM = "C:\\Program Files\\RustDesk\\rustdesk.exe"


class FakeWindows:
    """sc.exe, netstat and PowerShell answering from a table."""

    def __init__(self):
        self.calls = []
        self.service = {"is_present": False}
        self.processes = []
        self.netstat = ""

    def run(self, command, *, is_checked=True, timeout_s=0, input_text=None):
        self.calls.append(list(command))
        if command[:2] == ["sc.exe", "query"]:
            return CommandResult(list(command), 0, "STATE : 1  STOPPED\n", "")
        if command[:2] == ["sc.exe", "delete"]:
            self.service = {"is_present": False}
        if command[0] == "netstat":
            out = self.netstat if command[-1] == "TCP" else ""
            return CommandResult(list(command), 0, out, "")
        return CommandResult(list(command), 0, "", "")

    def powershell(self, script, document):
        if script is windows_applier.READ_SERVICE_SCRIPT:
            return dict(self.service)
        return {"processes": list(self.processes)}


@pytest.fixture()
def made(tmp_path):
    windows = FakeWindows()
    applier = RemoteDesktopWindowsApplier(
        kept_dir=str(tmp_path / "kept"),
        run=windows.run,
        powershell=windows.powershell,
        program=COPY,
        program_of=lambda pid: {7: COPY, 8: UPSTREAM}.get(pid, ""),
        sleep=lambda seconds: None,
    )
    applier.windows = windows
    applier.root = tmp_path
    return applier


def test_the_service_command_line_quotes_the_copy():
    assert image_path(COPY) == f'"{COPY}" --service'


def test_a_service_found_before_is_kept_as_it_was(made):
    made.windows.service = {
        "is_present": True,
        "image_path": f'"{UPSTREAM}" --service',
        "start_mode": "Auto",
        "state": "Running",
        "display_name": "RustDesk Service",
    }

    kept = made.keep_aside()

    assert kept == {
        "image_path": f'"{UPSTREAM}" --service',
        "start_mode": "Auto",
        "is_running": True,
        "display_name": "RustDesk Service",
    }
    assert json.loads((made.root / "kept" / "service.json").read_text()) == kept


def test_the_agents_own_service_is_not_kept(made):
    made.windows.service = {"is_present": True, "image_path": image_path(COPY)}

    assert made.keep_aside() == {}
    assert made.is_registered() is True


def test_no_service_keeps_nothing(made):
    assert made.keep_aside() == {}


def test_registering_creates_the_service_when_there_is_none(made):
    made.register()

    assert made.windows.calls == [
        [
            "sc.exe",
            "create",
            "RustDesk",
            "binPath=",
            image_path(COPY),
            "start=",
            "auto",
            "obj=",
            "LocalSystem",
            "DisplayName=",
            "RustDesk Service",
        ]
    ]


def test_registering_points_a_service_found_before_at_the_copy(made):
    made.windows.service = {"is_present": True, "image_path": image_path(UPSTREAM)}

    made.register()

    assert made.windows.calls[0][:3] == ["sc.exe", "config", "RustDesk"]


def test_stopping_waits_for_the_service_and_ends_hosts_but_not_viewers(made):
    made.windows.processes = [
        {"pid": 1, "program": UPSTREAM, "command": f'"{UPSTREAM}" --service'},
        {"pid": 2, "program": UPSTREAM, "command": f'"{UPSTREAM}" --tray'},
        {"pid": 3, "program": UPSTREAM, "command": f'"{UPSTREAM}" --connect 1.2.3.4'},
    ]

    made.stop_hosts()

    assert made.windows.calls[0] == ["sc.exe", "stop", "RustDesk"]
    assert made.windows.calls[1] == ["sc.exe", "query", "RustDesk"]
    assert made.windows.calls[-1] == ["taskkill.exe", "/F", "/PID", "1", "/PID", "2"]


def test_unregistering_deletes_a_service_the_agent_created(made):
    made.windows.service = {"is_present": True, "image_path": image_path(COPY)}

    made.unregister()

    assert ["sc.exe", "delete", "RustDesk"] in made.windows.calls


def test_unregistering_leaves_a_service_to_be_given_back(made):
    made.windows.service = {
        "is_present": True,
        "image_path": image_path(UPSTREAM),
        "start_mode": "Manual",
        "state": "Stopped",
    }
    made.keep_aside()
    made.windows.service = {"is_present": True, "image_path": image_path(COPY)}

    made.unregister()

    assert ["sc.exe", "delete", "RustDesk"] not in made.windows.calls


def test_a_kept_service_is_given_back_and_started_when_it_ran(made):
    made.windows.service = {
        "is_present": True,
        "image_path": image_path(UPSTREAM),
        "start_mode": "Auto",
        "state": "Running",
        "display_name": "RustDesk Service",
    }
    made.keep_aside()
    made.windows.calls.clear()

    made.restore()

    assert made.windows.calls == [
        [
            "sc.exe",
            "config",
            "RustDesk",
            "binPath=",
            image_path(UPSTREAM),
            "start=",
            "auto",
            "DisplayName=",
            "RustDesk Service",
        ],
        ["sc.exe", "start", "RustDesk"],
    ]
    assert not (made.root / "kept" / "service.json").exists()


def test_a_service_that_was_stopped_and_manual_stays_so(made):
    made.windows.service = {
        "is_present": True,
        "image_path": image_path(UPSTREAM),
        "start_mode": "Manual",
        "state": "Stopped",
    }
    made.keep_aside()
    made.windows.calls.clear()

    made.restore()

    assert made.windows.calls[0][5:7] == ["start=", "demand"]
    assert ["sc.exe", "start", "RustDesk"] not in made.windows.calls


def test_the_listeners_are_read_from_netstat():
    printed = (
        "  TCP    0.0.0.0:21118          0.0.0.0:0              LISTENING       7\n"
        "  TCP    [::]:21118             [::]:0                 LISTENING       7\n"
        "  TCP    10.0.0.5:21118         10.0.0.9:5000          ESTABLISHED     7\n"
        "  TCP    0.0.0.0:445            0.0.0.0:0              LISTENING       4\n"
    )

    assert listening_pids(printed, 21118) == [7, 7]


def test_the_listening_programs_are_named_once_each(made):
    made.windows.netstat = (
        "  TCP    0.0.0.0:21118   0.0.0.0:0   LISTENING   7\n"
        "  TCP    0.0.0.0:21118   0.0.0.0:0   LISTENING   8\n"
    )

    assert made.listening_programs(21118) == [COPY, UPSTREAM]


@pytest.mark.parametrize(
    "command, expected",
    [
        ('"C:\\x\\rustdesk.exe" --connect 1.2.3.4', True),
        ('"C:\\x\\rustdesk.exe" --service', False),
        ('"C:\\x\\rustdesk.exe" --server', False),
        ('"C:\\x\\rustdesk.exe"', False),
    ],
)
def test_which_rustdesk_is_a_viewer(command, expected):
    assert is_viewer_command(command) is expected


def test_the_copys_processes_are_told_by_their_program(made):
    made.windows.processes = [
        {"pid": 5, "program": COPY.upper(), "command": "x"},
        {"pid": 6, "program": UPSTREAM, "command": "x"},
    ]

    assert made.copy_pids() == [5]


def test_off_windows_no_program_is_read_by_pid():
    assert windows_applier.process_program(1) == ""


def test_a_host_whose_real_image_was_parked_by_the_installer_is_stale(tmp_path):
    """As T21t measured on nmxwin: the msi gives the new rustdesk.exe the
    build's own time, so every tray started after it, and Win32_Process
    still names the Program Files path; only QueryFullProcessImageName shows
    the image moved into Config.Msi."""
    copy = tmp_path / "rustdesk.exe"
    copy.write_bytes(b"new")
    other = tmp_path / "RustDesk" / "rustdesk.exe"
    other.parent.mkdir()
    other.write_bytes(b"theirs")
    parked = str(tmp_path / "Config.Msi" / "3b2a1.rbf")
    images = {61: str(copy), 62: parked, 63: str(other), 64: parked, 65: ""}
    windows = FakeWindows()
    windows.processes = [
        {"pid": 61, "program": str(copy), "command": "--service", "started": 9e9},
        {"pid": 62, "program": str(copy), "command": "--tray", "started": 9e9},
        {"pid": 63, "program": str(other), "command": "--tray", "started": 1},
        {"pid": 64, "program": str(copy), "command": "--connect a", "started": 9e9},
        {"pid": 65, "program": str(copy), "command": "--server", "started": 9e9},
    ]
    applier = RemoteDesktopWindowsApplier(
        kept_dir=str(tmp_path / "kept"),
        run=windows.run,
        powershell=windows.powershell,
        program=str(copy),
        program_of=images.get,
    )

    # 61 runs the copy; 63 is a person's own; 64 is a viewer; 65's image
    # cannot be read and WMI names the copy.
    assert applier.stale_pids() == [62]


def test_an_image_in_config_msi_or_gone_is_replaced(tmp_path):
    present = tmp_path / "rustdesk.exe"
    present.write_bytes(b"x")

    assert windows_applier.is_replaced_image("C:\\Config.Msi\\3b2a1.rbf")
    assert windows_applier.is_replaced_image(str(tmp_path / "gone.exe"))
    assert not windows_applier.is_replaced_image(str(present))


def test_a_tray_left_running_on_a_moved_aside_executable_is_stale_and_ended(
    tmp_path,
):
    """The msi's Restart Manager restarts the service itself, but the tray in
    the signed-in session keeps the old program, moved into Config.Msi."""
    import os

    copy = tmp_path / "rustdesk.exe"
    copy.write_bytes(b"new")
    written = int(max(os.stat(copy).st_mtime, os.stat(copy).st_ctime))
    parked = str(tmp_path / "Config.Msi" / "3b2a1.rbf")
    windows = FakeWindows()
    windows.processes = [
        {
            "pid": 71,
            "program": str(copy),
            "command": f'"{copy}" --service',
            "started": written + 3,
        },
        {
            "pid": 72,
            "program": str(copy),
            "command": f'"{copy}" --server',
            "started": written + 4,
        },
        {
            "pid": 73,
            "program": parked,
            "command": f'"{copy}" --tray',
            "started": written - 900,
        },
        {
            "pid": 74,
            "program": parked,
            "command": f'"{copy}" --connect 1.2.3.4',
            "started": written - 900,
        },
    ]
    applier = RemoteDesktopWindowsApplier(
        kept_dir=str(tmp_path / "kept"),
        run=windows.run,
        powershell=windows.powershell,
        program=str(copy),
        program_of={71: str(copy), 72: str(copy), 73: parked, 74: parked}.get,
        sleep=lambda seconds: None,
    )

    assert applier.stale_pids() == [73]

    applier.stop_hosts()

    assert windows.calls[-1] == [
        "taskkill.exe",
        "/F",
        "/PID",
        "71",
        "/PID",
        "72",
        "/PID",
        "73",
    ]


def test_the_service_runs_while_rustdesk_runs_the_copy(made):
    answers = {
        "qc": f"BINARY_PATH_NAME   : {image_path(COPY)}\n",
        "query": "STATE              : 4  RUNNING\n",
    }

    def run(command, **kwargs):
        made.windows.calls.append(list(command))
        return CommandResult(list(command), 0, answers.get(command[1], ""), "")

    made._run = run
    assert made.is_service_running() is True

    answers["query"] = "STATE              : 1  STOPPED\n"
    assert made.is_service_running() is False

    answers["qc"] = f"BINARY_PATH_NAME   : {image_path(UPSTREAM)}\n"
    answers["query"] = "STATE              : 4  RUNNING\n"
    assert made.is_service_running() is False
