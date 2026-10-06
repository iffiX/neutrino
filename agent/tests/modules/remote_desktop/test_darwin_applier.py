"""The agent's RustDesk on macOS: upstream's two job labels running the
agent's copy, what is moved aside, and what is never ended."""

import plistlib
import signal

import pytest

from neutrino_agent.modules.remote_desktop.darwin_applier import (
    RemoteDesktopDarwinApplier,
    service_job,
    session_job,
)
from neutrino_agent.modules.subprocess_run import CommandResult

APP = "/Library/Application Support/Neutrino/agent/app/rustdesk/RustDesk.app"
UPSTREAM = "/Applications/RustDesk.app"


class FakeMac:
    """launchctl, ps and lsof answering from a table."""

    def __init__(self):
        self.calls = []
        self.programs = {}
        self.arguments = {}
        self.listening = ""
        self.loaded = set()

    def __call__(self, command, *, is_checked=True, timeout_s=0, input_text=None):
        self.calls.append(list(command))
        out, code = "", 0
        if command[0].endswith("launchctl") and command[1] == "print":
            code = 0 if command[2] in self.loaded else 113
        elif command[0].endswith("launchctl") and command[1] == "bootout":
            self.loaded.discard(command[2])
        elif command[0].endswith("ps") and command[1] == "-axww":
            out = "".join(f"{pid} {path}\n" for pid, path in self.programs.items())
        elif command[0].endswith("ps"):
            out = " ".join(self.arguments.get(int(command[-1]), [])) + "\n"
        elif command[0].endswith("lsof"):
            out = self.listening
        return CommandResult(list(command), code, out, "")


@pytest.fixture()
def made(tmp_path):
    mac = FakeMac()
    killed = []

    def kill(pid, sent):
        if sent == 0:
            if pid not in mac.programs:
                raise ProcessLookupError(pid)
            return
        killed.append((pid, sent))
        mac.programs.pop(pid, None)

    applier = RemoteDesktopDarwinApplier(
        kept_dir=str(tmp_path / "kept"),
        run=mac,
        app=APP,
        service_plist=str(tmp_path / "LaunchDaemons" / "service.plist"),
        session_plist=str(tmp_path / "LaunchAgents" / "server.plist"),
        kill=kill,
        sleep=lambda seconds: None,
        seat_uid=lambda: 501,
    )
    applier.mac = mac
    applier.killed = killed
    applier.root = tmp_path
    return applier


def _write_job(path, job):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as stream:
        plistlib.dump(job, stream)


def _read_job(path):
    with open(path, "rb") as stream:
        return plistlib.load(stream)


def test_the_jobs_keep_upstreams_labels_and_run_the_copy():
    service = service_job(APP)
    session = session_job(APP)

    assert service["Label"] == "com.carriez.RustDesk_service"
    assert service["ProgramArguments"] == [APP + "/Contents/MacOS/service"]
    assert session["Label"] == "com.carriez.RustDesk_server"
    assert session["ProgramArguments"] == [APP + "/Contents/MacOS/RustDesk", "--server"]
    assert session["KeepAlive"] is True
    assert set(session["LimitLoadToSessionType"]) == {"Aqua", "LoginWindow"}


def test_somebody_elses_plists_are_moved_aside(made):
    _write_job(made.root / "LaunchDaemons" / "service.plist", service_job(UPSTREAM))
    _write_job(made.root / "LaunchAgents" / "server.plist", session_job(UPSTREAM))

    kept = made.keep_aside()

    assert kept == {"plists": ["service.plist", "server.plist"]}
    assert not (made.root / "LaunchDaemons" / "service.plist").exists()
    assert (made.root / "kept" / "server.plist").exists()


def test_the_agents_own_plists_are_not_kept(made):
    made.register()

    assert made.keep_aside() == {}
    assert made.is_registered() is True


def test_registering_writes_both_jobs_for_the_copy(made):
    made.register()

    service = _read_job(made.root / "LaunchDaemons" / "service.plist")
    session = _read_job(made.root / "LaunchAgents" / "server.plist")
    assert service["ProgramArguments"][0].startswith(APP + "/")
    assert session["ProgramArguments"][0].startswith(APP + "/")


def test_starting_bootstraps_the_service_then_the_seats_job(made):
    made.start(501)

    assert made.mac.calls == [
        [
            "/bin/launchctl",
            "bootstrap",
            "system",
            str(made.root / "LaunchDaemons" / "service.plist"),
        ],
        [
            "/bin/launchctl",
            "bootstrap",
            "gui/501",
            str(made.root / "LaunchAgents" / "server.plist"),
        ],
    ]


def test_with_nobody_seated_only_the_service_starts(made):
    made.start(None)

    assert [call[2] for call in made.mac.calls] == ["system"]


def test_stopping_boots_out_the_seats_job_before_the_service(made):
    made.stop_hosts()

    bootouts = [call[2] for call in made.mac.calls if call[1] == "bootout"]
    assert bootouts == [
        "gui/501/com.carriez.RustDesk_server",
        "system/com.carriez.RustDesk_service",
    ]


def test_every_host_is_ended_and_a_viewer_left_alone(made):
    made.mac.programs = {
        11: UPSTREAM + "/Contents/MacOS/RustDesk",
        12: UPSTREAM + "/Contents/MacOS/service",
        13: UPSTREAM + "/Contents/MacOS/RustDesk",
        14: "/usr/sbin/sshd",
    }
    made.mac.arguments = {
        11: [UPSTREAM + "/Contents/MacOS/RustDesk", "--server"],
        12: [UPSTREAM + "/Contents/MacOS/service"],
        13: [UPSTREAM + "/Contents/MacOS/RustDesk", "--connect", "10.0.0.2"],
    }

    made.stop_hosts()

    assert sorted(pid for pid, _ in made.killed) == [11, 12]
    assert all(sent == signal.SIGTERM for _, sent in made.killed)


def test_unregistering_deletes_only_the_agents_plists(made):
    made.register()
    made.mac.programs = {21: APP + "/Contents/MacOS/RustDesk"}
    made.mac.arguments = {21: [APP + "/Contents/MacOS/RustDesk", "--server"]}

    made.unregister()

    assert not (made.root / "LaunchDaemons" / "service.plist").exists()
    assert not (made.root / "LaunchAgents" / "server.plist").exists()
    assert [pid for pid, _ in made.killed] == [21]


def test_kept_plists_are_moved_back_and_bootstrapped(made):
    _write_job(made.root / "LaunchDaemons" / "service.plist", service_job(UPSTREAM))
    _write_job(made.root / "LaunchAgents" / "server.plist", session_job(UPSTREAM))
    made.keep_aside()
    made.register()
    made.unregister()
    made.mac.calls.clear()

    made.restore()

    restored = _read_job(made.root / "LaunchDaemons" / "service.plist")
    assert restored["ProgramArguments"][0].startswith(UPSTREAM)
    assert [call[1:3] for call in made.mac.calls] == [
        ["bootstrap", "system"],
        ["bootstrap", "gui/501"],
    ]


def test_the_listener_is_read_from_the_socket_table(made):
    made.mac.programs = {31: APP + "/Contents/MacOS/RustDesk"}
    made.mac.listening = "p31\n"

    assert made.listening_programs(21118) == [APP + "/Contents/MacOS/RustDesk"]
    assert made.mac.calls[0][:2] == ["/usr/sbin/lsof", "-nP"]


def test_the_copys_processes_are_told_from_anybody_elses(made):
    made.mac.programs = {
        41: APP + "/Contents/MacOS/service",
        42: UPSTREAM + "/Contents/MacOS/service",
    }

    assert made.copy_pids() == [41]


@pytest.mark.parametrize(
    "printed, seconds",
    [("00:05", 5), ("01:02:03", 3723), ("2-00:00:01", 172801), ("", None), ("x", None)],
)
def test_the_elapsed_time_ps_prints_is_read(printed, seconds):
    from neutrino_agent.modules.remote_desktop.darwin_applier import elapsed_seconds

    assert elapsed_seconds(printed) == seconds


def test_a_copy_process_older_than_the_copy_on_disk_is_stale(tmp_path):
    app = tmp_path / "RustDesk.app"
    binary = app / "Contents" / "MacOS" / "RustDesk"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"new")
    mac = FakeMac()
    mac.programs = {51: str(binary), 52: str(binary)}
    ages = {"51": "10:00", "52": "00:00"}

    def run(command, **kwargs):
        if command[1:3] == ["-o", "etime="]:
            return CommandResult(list(command), 0, ages[command[-1]] + "\n", "")
        return mac(command, **kwargs)

    applier = RemoteDesktopDarwinApplier(
        kept_dir=str(tmp_path / "kept"), run=run, app=str(app), seat_uid=lambda: None
    )

    assert applier.stale_pids() == [51]
