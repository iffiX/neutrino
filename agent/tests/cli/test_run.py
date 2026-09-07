"""``nagent run`` and the root gate over every machine-changing command.

Run serves the control socket and then the agent's own loop; on Windows the
service control manager starts the same command behind its handshake. The
gate over the machine-changing commands is asserted as a whole list.
"""

import pytest

import neutrino_agent.cli.entry as entry
import neutrino_agent.cli.run as run_cli
from neutrino_agent.constants import AGENT_SERVICE_NAME_WINDOWS
from neutrino_agent.control import client
from neutrino_agent.control.server import ControlServer
from neutrino_agent.platforms import windows_service
from tests.conftest import FakeControlAgent, FakeControlPlatform


def record_servers(monkeypatch, servers):
    """Keep every control server ``nagent run`` starts.

    Args:
        monkeypatch: The test's patcher.
        servers: The list started servers land in.
    """

    def build(**kwargs):
        server = ControlServer(**kwargs)
        servers.append(server)
        return server

    monkeypatch.setattr(run_cli, "ControlServer", build)


class FakeRunPlatform(FakeControlPlatform):
    """The machine ``nagent run`` serves on: one socket path in ``tmp_path``."""

    def __init__(self, socket_path: str):
        super().__init__()
        self._socket_path = socket_path

    def control_socket_path(self) -> str:
        return self._socket_path


class FakeRunAgent(FakeControlAgent):
    """The agent run drives: its foreground loop asks its own socket once."""

    def __init__(self, *, platform):
        super().__init__()
        self._platform = platform
        self.answered = None

    def run_forever(self) -> None:
        self.answered = client.request(
            socket_path=self._platform.control_socket_path(),
            method="GET",
            path="/api/state",
        )


@pytest.fixture
def run_stack(tmp_path, monkeypatch):
    """The platform, the agents run built, and the servers to stop after."""
    platform = FakeRunPlatform(str(tmp_path / "agent.sock"))
    agents = []
    servers = []

    def build_agent(*, platform):
        agent = FakeRunAgent(platform=platform)
        agents.append(agent)
        return agent

    monkeypatch.setattr(run_cli, "detect_platform", lambda: platform)
    monkeypatch.setattr(run_cli, "Agent", build_agent)
    yield platform, agents, servers
    for server in servers:
        server.stop()


def test_run_serves_the_control_socket_before_the_loop(run_stack, monkeypatch):
    platform, agents, servers = run_stack
    record_servers(monkeypatch, servers)

    assert run_cli.main() == 0

    status, state = agents[0].answered
    assert status == 200
    assert state["caller"]["account"] == "root"
    assert servers[0].socket_path == platform.control_socket_path()


def test_the_windows_service_hosts_the_same_loop_behind_the_handshake(
    run_stack, monkeypatch
):
    """What the service control manager starts is this command with one flag:
    the same socket, the same loop, wrapped in the handshake a service owes."""
    platform, agents, servers = run_stack
    record_servers(monkeypatch, servers)
    hosted = {}

    def host_service(*, name, run):
        hosted["name"] = name
        run()

    monkeypatch.setattr(windows_service, "host_service", host_service)

    assert run_cli.main(is_windows_service=True) == 0

    assert hosted["name"] == AGENT_SERVICE_NAME_WINDOWS
    status, state = agents[0].answered
    assert status == 200
    assert servers[0].socket_path == platform.control_socket_path()


def test_the_handshake_is_the_manager_s_alone(monkeypatch):
    """Typed by a person, run is the foreground loop: nothing answers a
    manager that did not start this process."""
    passed = {}
    monkeypatch.setattr(entry.os, "geteuid", lambda: 0)
    monkeypatch.setattr(entry.sys, "argv", ["nagent", "run"])
    monkeypatch.setattr(entry.run, "main", lambda **kwargs: passed.update(kwargs) or 0)

    assert entry.main() == 0
    assert passed == {"is_windows_service": False}


def test_an_unprivileged_run_is_refused_with_the_command(monkeypatch, capsys):
    monkeypatch.setattr(entry.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(entry.sys, "argv", ["nagent", "run"])

    assert entry.main() == 2

    err = capsys.readouterr().err
    assert "nagent run needs root (the agent manages this machine)" in err
    assert "sudo nagent run" in err


def test_the_gate_covers_exactly_what_changes_the_machine():
    assert sorted(entry.ROOT_COMMANDS) == ["connect", "disconnect", "run"]


def test_status_is_never_gated():
    assert "status" not in entry.ROOT_COMMANDS
