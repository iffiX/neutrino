"""``nagent service run``: the dispatcher first, the agent once running.

The service control manager fails a process that has not called the
dispatcher within 30 seconds, so nothing is built before it is handed the
process; the agent and its control channel are built in the start callback
and the stop callback closes the channel. A process the manager did not
start is told so. The log is ``agent.log`` under the data root.
"""

import pytest

import neutrino_agent.cli.service as service_cli
from tests.conftest import FakeControlPlatform


class FakeDispatcher:
    """Records the callbacks, and runs them when told to."""

    instances: list = []

    def __init__(self, name, on_start, on_stop):
        self.name = name
        self.on_start = on_start
        self.on_stop = on_stop
        self.error = None
        FakeDispatcher.instances.append(self)

    def run(self):
        if self.error is not None:
            raise self.error


class LogPlatform(FakeControlPlatform):
    def __init__(self, log_path):
        self._log_path = log_path

    def agent_log_path(self):
        return self._log_path


@pytest.fixture
def service_stack(tmp_path, monkeypatch):
    FakeDispatcher.instances = []
    built = []

    class FakeAgent:
        def __init__(self, *, log, platform):
            self.is_running = False
            built.append(("agent", self))

        def run_forever(self):
            self.is_running = True

    class FakeServer:
        def __init__(self, *, agent, platform, log):
            self.is_started = False
            self.is_stopped = False
            built.append(("control", self))

        def start(self):
            self.is_started = True

        def stop(self):
            self.is_stopped = True

    monkeypatch.setattr(
        service_cli, "detect_platform", lambda: LogPlatform(str(tmp_path / "agent.log"))
    )
    monkeypatch.setattr(service_cli, "ServiceControlDispatcher", FakeDispatcher)
    monkeypatch.setattr(service_cli, "Agent", FakeAgent)
    monkeypatch.setattr(service_cli, "ControlServer", FakeServer)
    yield built


def test_the_dispatcher_is_handed_the_process_before_anything_is_built(
    service_stack,
):
    assert service_cli.main_run() == 0

    dispatcher = FakeDispatcher.instances[0]
    assert dispatcher.name == "neutrino_agent"
    assert service_stack == []


def test_starting_builds_the_agent_and_its_channel_and_stopping_closes_it(
    service_stack,
):
    service_cli.main_run()
    dispatcher = FakeDispatcher.instances[0]

    dispatcher.on_start()
    dispatcher.on_stop()

    kinds = dict(service_stack)
    assert kinds["agent"].is_running
    assert kinds["control"].is_started
    assert kinds["control"].is_stopped


def test_a_process_the_manager_did_not_start_is_told_so(
    service_stack, monkeypatch, capsys
):
    original = FakeDispatcher.__init__

    def refusing(self, *args, **kwargs):
        original(self, *args, **kwargs)
        self.error = OSError(1063, "the service process could not connect")

    monkeypatch.setattr(FakeDispatcher, "__init__", refusing)

    assert service_cli.main_run() == 1
    assert "started by the service control manager" in capsys.readouterr().err


def test_the_service_log_makes_its_directory_and_writes_the_file(tmp_path):
    log = service_cli.service_log(str(tmp_path / "log" / "agent.log"))

    log("service stopping")

    text = (tmp_path / "log" / "agent.log").read_text(encoding="utf-8")
    assert "service stopping" in text
