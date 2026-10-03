"""The process controller of the hub's one service on macOS and Windows.

Inside the service each verb acts on a child, ``services.json`` records
what is enabled, and the service follows a change another process writes
there. In a ``nhub`` command, which runs no children, starting a child
records it; only a panel verb, or a child restart while the service runs,
acts on the service through the platform.
"""

import json
import threading
import time

import pytest

from neutrino_hub.platforms.constants import (
    PLATFORM_SERVICE_RUNNING,
    PLATFORM_SERVICE_STOPPED,
)
from neutrino_hub.system.child_supervisor import ChildProcessSupervisor, ChildStartLine
from neutrino_hub.system.constants import SYSTEM_RESTART_EXIT_STATUS
from neutrino_hub.system.process_control import SupervisedProcessController
from tests.conftest import FakeClock, FakePopen

XRAY = ChildStartLine(argv=["/app/bin/xray", "run"])
CLIPROXYAPI = ChildStartLine(argv=["/app/bin/cli-proxy-api"])


class FakeService:
    """The platform's one service, as the controller drives it."""

    def __init__(self, state: str = PLATFORM_SERVICE_STOPPED):
        self.state = state
        self.calls: list = []

    def service_state(self) -> str:
        return self.state

    def start_service(self) -> None:
        self.calls.append("start")
        self.state = PLATFORM_SERVICE_RUNNING

    def stop_service(self) -> None:
        self.calls.append("stop")
        self.state = PLATFORM_SERVICE_STOPPED

    def restart_service(self) -> None:
        self.calls.append("restart")
        self.state = PLATFORM_SERVICE_RUNNING


class Exits:
    """os._exit, recorded instead of taken."""

    def __init__(self):
        self.statuses: list = []
        self.happened = threading.Event()

    def __call__(self, status: int) -> None:
        self.statuses.append(status)
        self.happened.set()


@pytest.fixture
def popen():
    return FakePopen()


@pytest.fixture
def service():
    return FakeService()


@pytest.fixture
def exits():
    return Exits()


@pytest.fixture
def controller(tmp_path, popen, service, exits):
    supervisor = ChildProcessSupervisor(
        log_dir=tmp_path / "log",
        base_env={},
        start_process=popen,
        clock=FakeClock(),
        log=lambda line: None,
    )
    built = SupervisedProcessController(
        supervisor=supervisor,
        service=service,
        state_path=tmp_path / "state" / "services.json",
        log_dir=tmp_path / "log",
        exit=exits,
        restart_delay_s=0,
        reconcile_s=3600,
    )
    yield built
    built.shutdown()


def _command(tmp_path, service) -> SupervisedProcessController:
    """The controller a ``nhub`` command holds, on the same services.json."""
    return SupervisedProcessController(
        supervisor=ChildProcessSupervisor(log_dir=tmp_path / "log"),
        service=service,
        state_path=tmp_path / "state" / "services.json",
        log_dir=tmp_path / "log",
    )


def _state(tmp_path) -> dict:
    return json.loads((tmp_path / "state" / "services.json").read_text())


def test_enabling_writes_services_json_and_starts_the_child(
    controller, popen, tmp_path
):
    controller.supervise({"xray": XRAY})

    controller.enable("xray")

    assert _state(tmp_path)["enabled"] == ["xray"]
    assert [child.argv for child in popen.started] == [XRAY.argv]
    assert controller.is_active("xray")
    assert controller.is_enabled("xray")


def test_disabling_takes_it_out_and_stops_the_child(controller, popen, tmp_path):
    controller.supervise({"xray": XRAY})
    controller.enable("xray")

    controller.disable("xray")

    assert _state(tmp_path)["enabled"] == []
    assert popen.started[0].is_terminated
    assert not controller.is_active("xray")


def test_the_service_starts_every_enabled_child(tmp_path, controller, popen):
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "services.json").write_text(
        json.dumps({"enabled": ["cliproxyapi", "netbird"]})
    )

    controller.supervise({"xray": XRAY, "cliproxyapi": CLIPROXYAPI})

    assert [child.argv for child in popen.started] == [CLIPROXYAPI.argv]
    assert not controller.status("netbird").is_installed


def test_a_start_line_handed_over_is_kept_for_the_next_start(
    tmp_path, controller, popen
):
    controller.set_start_line(
        "easytier", ["/app/bin/easytier-core", "-c", "x.toml"], {"K": "v"}, "/w"
    )
    controller.enable("easytier")

    controller.supervise({"xray": XRAY})

    assert _state(tmp_path)["start_lines"]["easytier"]["argv"][0] == (
        "/app/bin/easytier-core"
    )
    (child,) = popen.started
    assert child.argv == ["/app/bin/easytier-core", "-c", "x.toml"]
    assert child.env == {"K": "v"}
    assert child.cwd == "/w"


def test_the_services_own_start_line_wins_over_a_kept_one(tmp_path, controller, popen):
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "services.json").write_text(
        json.dumps(
            {"enabled": ["xray"], "start_lines": {"xray": {"argv": ["/old/xray"]}}}
        )
    )

    controller.supervise({"xray": XRAY})

    assert popen.started[0].argv == XRAY.argv


def test_restarting_a_child_inside_the_service_restarts_that_child(controller, popen):
    controller.supervise({"xray": XRAY})
    controller.enable("xray")

    controller.restart("xray")

    assert popen.started[0].is_terminated
    assert len(popen.started) == 2


def test_restarting_the_panel_inside_the_service_exits_it(controller, popen, exits):
    controller.supervise({"xray": XRAY})
    controller.enable("xray")

    controller.restart("web")

    assert exits.happened.wait(timeout=5)
    assert exits.statuses == [SYSTEM_RESTART_EXIT_STATUS]
    assert popen.started[0].is_terminated


def test_the_journal_is_the_tail_of_the_log_file(tmp_path, controller):
    (tmp_path / "log").mkdir()
    (tmp_path / "log" / "netbird.log").write_text(
        "".join(f"line {n}\n" for n in range(10))
    )

    assert controller.journal("netbird", line_count=3) == "line 7\nline 8\nline 9\n"
    assert controller.journal("xray") == ""


def test_reload_does_nothing(controller, popen, service):
    controller.reload()

    assert popen.started == []
    assert service.calls == []


def test_a_name_the_service_does_not_run_is_refused(controller):
    for name in ("router", "dnsmasq", "samba"):
        with pytest.raises(KeyError):
            controller.status(name)


def test_an_action_outside_the_list_is_refused(controller):
    with pytest.raises(ValueError):
        controller.control("xray", "mask")


def test_every_name_the_service_runs_has_a_status(controller):
    names = [status.name for status in controller.status_all()]

    assert names == ["web", "xray", "cliproxyapi", "netbird", "easytier"]


def test_a_command_enables_into_services_json_alone(controller, popen, tmp_path):
    controller.enable("xray")

    assert _state(tmp_path)["enabled"] == ["xray"]
    assert popen.started == []


def test_a_command_restarting_the_panel_restarts_the_service(controller, service):
    service.state = PLATFORM_SERVICE_RUNNING

    controller.restart("web")

    assert service.calls == ["restart"]


@pytest.mark.parametrize("action", ["start", "restart", "enable"])
def test_a_command_records_a_child_while_the_service_is_stopped(
    controller, service, popen, tmp_path, action
):
    controller.control("cliproxyapi", action)

    assert _state(tmp_path)["enabled"] == ["cliproxyapi"]
    assert service.calls == []
    assert popen.started == []


def test_a_command_starting_a_child_leaves_the_running_service_alone(
    controller, service, tmp_path
):
    service.state = PLATFORM_SERVICE_RUNNING

    controller.start("xray")

    assert _state(tmp_path)["enabled"] == ["xray"]
    assert service.calls == []


def test_a_command_restarting_a_child_of_the_running_service_restarts_it(
    controller, service
):
    service.state = PLATFORM_SERVICE_RUNNING

    controller.restart("cliproxyapi")

    assert service.calls == ["restart"]


def test_the_service_starts_a_child_another_process_enabled(
    controller, service, popen, tmp_path
):
    controller.supervise({"xray": XRAY})

    _command(tmp_path, service).enable("xray")
    controller.reconcile()

    assert [child.argv for child in popen.started] == [XRAY.argv]
    assert controller.is_active("xray")


def test_the_service_stops_a_child_another_process_disabled(
    controller, service, popen, tmp_path
):
    controller.supervise({"xray": XRAY})
    controller.enable("xray")
    controller.reconcile()

    _command(tmp_path, service).disable("xray")
    controller.reconcile()

    assert popen.started[0].is_terminated
    assert not controller.is_active("xray")


def test_a_child_started_here_without_enabling_is_left_running(controller, popen):
    controller.supervise({"xray": XRAY})
    controller.start("xray")

    controller.reconcile()

    assert controller.is_active("xray")


def test_a_start_line_another_process_kept_is_held_and_started(
    controller, service, popen, tmp_path
):
    controller.supervise({"xray": XRAY})
    command = _command(tmp_path, service)

    command.set_start_line("easytier", ["/app/bin/easytier-core"], {}, None)
    command.enable("easytier")
    controller.reconcile()

    assert [child.argv for child in popen.started] == [["/app/bin/easytier-core"]]


def test_the_service_follows_services_json_on_its_timer(tmp_path, popen, service):
    supervisor = ChildProcessSupervisor(
        log_dir=tmp_path / "log", base_env={}, start_process=popen, log=print
    )
    controller = SupervisedProcessController(
        supervisor=supervisor,
        service=service,
        state_path=tmp_path / "state" / "services.json",
        log_dir=tmp_path / "log",
        reconcile_s=0.01,
    )
    controller.supervise({"xray": XRAY})
    try:
        _command(tmp_path, service).enable("xray")
        deadline = time.monotonic() + 5
        while not popen.started and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        controller.shutdown()

    assert [child.argv for child in popen.started] == [XRAY.argv]


def test_a_command_cannot_stop_one_child(controller, service):
    with pytest.raises(RuntimeError):
        controller.stop("xray")
    assert service.calls == []


def test_a_command_reads_the_panel_from_the_service(controller, service):
    assert not controller.status("web").is_active
    service.state = PLATFORM_SERVICE_RUNNING

    assert controller.status("web").is_active


def test_a_command_reads_an_enabled_child_as_running_with_the_service(
    controller, service
):
    controller.enable("netbird")
    service.state = PLATFORM_SERVICE_RUNNING

    status = controller.status("netbird")

    assert status.is_installed and status.is_enabled and status.is_active
    assert not controller.status("easytier").is_active
