"""``nagent service run``: the dispatcher first, the agent once running.

The service control manager fails a process that has not called the
dispatcher within 30 seconds, so nothing is built before it is handed the
process; the agent and its control channel are built in the start callback.
The stop callback only asks the agent's loop to end, and the channel closes
once the loop has. A process the manager did not start is told so. The log
is ``agent.log`` under the data root.
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
            self.is_stop_asked = False
            built.append(("agent", self))

        def run_forever(self):
            self.is_running = True

        def stop(self):
            self.is_stop_asked = True

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


def test_starting_builds_the_agent_and_its_channel_and_closes_it_once_the_loop_ends(
    service_stack,
):
    service_cli.main_run()
    dispatcher = FakeDispatcher.instances[0]

    dispatcher.on_start()

    kinds = dict(service_stack)
    assert kinds["agent"].is_running
    assert kinds["control"].is_started
    assert kinds["control"].is_stopped


def test_a_stop_only_asks_the_agent_to_end(service_stack, monkeypatch):
    service_cli.main_run()
    dispatcher = FakeDispatcher.instances[0]
    held = {}

    def run_until_stopped(agent):
        held["agent"] = agent
        dispatcher.on_stop()

    monkeypatch.setattr(service_cli.Agent, "run_forever", run_until_stopped)

    dispatcher.on_start()

    kinds = dict(service_stack)
    assert held["agent"].is_stop_asked
    assert kinds["control"].is_stopped


def test_a_stop_before_the_agent_is_built_keeps_the_loop_from_running(
    service_stack,
):
    service_cli.main_run()
    dispatcher = FakeDispatcher.instances[0]

    dispatcher.on_stop()
    dispatcher.on_start()

    kinds = dict(service_stack)
    assert not kinds["agent"].is_running
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


class RemovalPlatform(FakeControlPlatform):
    """Records what ``nagent service uninstall`` asks of the system."""

    def __init__(self, *, capabilities=frozenset({"removal"}), error=None):
        self.capabilities = capabilities
        self.calls = []
        self._error = error

    def stop_agent_service(self):
        self.calls.append("stop")

    def remove_added(self):
        self.calls.append("remove_added")
        if self._error is not None:
            raise self._error
        return ["neutrino_vscode@ann.service"]

    def remove_agent_program(self):
        self.calls.append("remove_agent_program")
        return ["com.neutrino.agent"]


def test_uninstall_stops_the_agent_before_taking_what_its_modules_added(
    monkeypatch, capsys
):
    platform = RemovalPlatform()
    monkeypatch.setattr(service_cli, "detect_platform", lambda: platform)

    assert service_cli.main_uninstall(is_forced=True) == 0

    assert platform.calls == ["stop", "remove_added"]
    assert "removed    neutrino_vscode@ann.service" in capsys.readouterr().out


def test_uninstall_on_a_mac_removes_the_agent_itself_as_well(monkeypatch, capsys):
    platform = RemovalPlatform(capabilities=frozenset({"removal", "self_removal"}))
    monkeypatch.setattr(service_cli, "detect_platform", lambda: platform)

    assert service_cli.main_uninstall(is_forced=True) == 0

    assert platform.calls == ["stop", "remove_added", "remove_agent_program"]
    assert "removed    com.neutrino.agent" in capsys.readouterr().out


def test_uninstall_asks_first_and_a_no_changes_nothing(monkeypatch, capsys):
    platform = RemovalPlatform()
    monkeypatch.setattr(service_cli, "detect_platform", lambda: platform)
    monkeypatch.setattr("builtins.input", lambda question: "n")

    assert service_cli.main_uninstall(is_forced=False) == 1

    assert platform.calls == []
    assert "nothing changed" in capsys.readouterr().out


def test_uninstall_says_why_when_the_removal_stops(monkeypatch, capsys):
    platform = RemovalPlatform(error=OSError("powershell did not answer"))
    monkeypatch.setattr(service_cli, "detect_platform", lambda: platform)

    assert service_cli.main_uninstall(is_forced=True) == 1

    assert "powershell did not answer" in capsys.readouterr().err


def test_uninstall_on_a_platform_with_nothing_to_remove_exits_1(monkeypatch, capsys):
    monkeypatch.setattr(service_cli, "detect_platform", lambda: FakeControlPlatform())

    assert service_cli.main_uninstall(is_forced=True) == 1
    assert "error:" in capsys.readouterr().err
