"""``nhub service run``: the dispatcher first, the hub once running.

The service control manager fails a process that has not called the
dispatcher within 30 seconds, so nothing of the hub is built before it.
"""

import pytest

from neutrino_hub.cli import service as service_cli


class FakeDispatcher:
    """The dispatcher, calling the service's start and stop as the manager would."""

    instances: list = []
    is_from_manager = True

    def __init__(self, name, on_start, on_stop):
        self.name = name
        self.on_start = on_start
        self.on_stop = on_stop
        FakeDispatcher.instances.append(self)

    def run(self):
        if not FakeDispatcher.is_from_manager:
            raise OSError(1063, "not started by the manager")
        self.on_start()
        self.on_stop()


@pytest.fixture
def service_stack(monkeypatch, tmp_path):
    FakeDispatcher.instances = []
    FakeDispatcher.is_from_manager = True
    ran: list = []
    monkeypatch.setattr(service_cli.sys, "platform", "win32")
    monkeypatch.setattr(service_cli, "ServiceControlDispatcher", FakeDispatcher)
    monkeypatch.setattr(service_cli, "UTILS_LOG_ROOT", tmp_path)
    monkeypatch.setattr(service_cli.run_command, "main", lambda: ran.append("run") or 0)
    monkeypatch.setattr(
        service_cli.run_command, "stop_serving", lambda: ran.append("stop_serving")
    )
    monkeypatch.setattr(service_cli.sys, "argv", ["nhub service", "run"])
    saved = (service_cli.sys.stdout, service_cli.sys.stderr)
    yield ran
    service_cli.sys.stdout, service_cli.sys.stderr = saved


def test_the_service_runs_the_hub_as_nhub_run_does(service_stack, tmp_path):
    assert service_cli.main() == 0

    assert FakeDispatcher.instances[0].name == "neutrino_hub"
    assert service_stack == ["run", "stop_serving"]


def test_a_stop_only_asks_the_panel_to_end(service_stack):
    service_cli.main()

    FakeDispatcher.instances[0].on_stop()

    assert service_stack == ["run", "stop_serving", "stop_serving"]


def test_the_services_output_goes_to_the_panels_log(service_stack, tmp_path):
    service_cli.main()

    assert (tmp_path / "web.log").exists()


def test_a_big_log_is_kept_once_before_the_service_writes(
    service_stack, tmp_path, monkeypatch
):
    monkeypatch.setattr(service_cli, "SYSTEM_CHILD_LOG_MAX_BYTES", 4)
    (tmp_path / "web.log").write_text("older lines")

    service_cli.main()

    assert (tmp_path / "web.log.1").read_text() == "older lines"


def test_a_process_the_manager_did_not_start_is_refused(service_stack, capsys):
    FakeDispatcher.is_from_manager = False

    assert service_cli.main() == 1
    assert "service control manager" in capsys.readouterr().err
    assert service_stack == []


def test_off_windows_it_points_at_nhub_run(service_stack, monkeypatch, capsys):
    monkeypatch.setattr(service_cli.sys, "platform", "darwin")

    assert service_cli.main() == 2
    assert "nhub run" in capsys.readouterr().err
    assert FakeDispatcher.instances == []
