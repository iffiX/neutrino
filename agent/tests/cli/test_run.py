"""``nagent run`` and the root gate over every machine-changing command.

The control socket always serves, so ``--no-ui`` withholds only the loopback
page; a page that cannot bind leaves a working agent behind. The gate over
the machine-changing commands is asserted as a whole list.
"""

import socket

import pytest

import neutrino_agent.cli.entry as entry
import neutrino_agent.cli.run as run_cli
from neutrino_agent.control import client
from neutrino_agent.control.server import ControlServer
from tests.conftest import FakeControlAgent, FakeControlPlatform


def record_servers(monkeypatch, servers, *, page_port=None):
    """Keep every control server ``nagent run`` starts.

    Args:
        monkeypatch: The test's patcher.
        servers: The list started servers land in.
        page_port: Forced page port, for a port somebody else holds.
    """

    def build(**kwargs):
        if page_port is not None:
            kwargs["page_port"] = page_port
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


@pytest.fixture
def squatted_port():
    """A loopback port another local process already holds."""
    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    yield holder.getsockname()[1]
    holder.close()


def test_no_ui_still_serves_the_control_socket(run_stack, monkeypatch):
    platform, agents, servers = run_stack
    record_servers(monkeypatch, servers)

    assert run_cli.main(is_ui_served=False) == 0

    status, state = agents[0].answered
    assert status == 200
    assert state["caller"]["account"] == "root"
    assert servers[0].socket_path == platform.control_socket_path()
    assert servers[0].page_port == 0


def test_a_page_that_cannot_bind_leaves_the_agent_running(
    run_stack, monkeypatch, squatted_port
):
    _platform, agents, servers = run_stack
    record_servers(monkeypatch, servers, page_port=squatted_port)

    assert run_cli.main(is_ui_served=True) == 0

    status, _state = agents[0].answered
    assert status == 200
    assert servers[0].page_port == 0
    assert servers[0].socket_path


def test_an_unprivileged_run_is_refused_with_the_command(monkeypatch, capsys):
    monkeypatch.setattr(entry.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(entry.sys, "argv", ["nagent", "run", "--no-ui"])

    assert entry.main() == 2

    err = capsys.readouterr().err
    assert "nagent run needs root — the agent manages this machine" in err
    assert "sudo nagent run --no-ui" in err


def test_the_gate_covers_exactly_what_changes_the_machine():
    assert sorted(entry.ROOT_COMMANDS) == ["connect", "disconnect", "run"]


def test_status_is_never_gated():
    assert "status" not in entry.ROOT_COMMANDS
