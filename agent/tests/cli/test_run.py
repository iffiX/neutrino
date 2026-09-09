"""``nagent run``: the control socket serves before the loop does.

Run is what the systemd unit starts. It binds the socket first, so the
agent answers ``nagent`` from the moment the loop begins.
"""

import pytest

import neutrino_agent.cli.entry as entry
import neutrino_agent.cli.run as run_cli
from neutrino_agent.control import client
from neutrino_agent.control.server import ControlServer
from tests.conftest import FakeControlAgent, FakeControlPlatform


class FakeRunPlatform(FakeControlPlatform):
    """The machine ``nagent run`` serves on: one socket path in ``tmp_path``."""

    def __init__(self, socket_path: str):
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
    platform = FakeRunPlatform(str(tmp_path / "run" / "agent.sock"))
    agents = []
    servers = []

    def build_agent(*, platform):
        agent = FakeRunAgent(platform=platform)
        agents.append(agent)
        return agent

    def build_server(**kwargs):
        server = ControlServer(**kwargs)
        servers.append(server)
        return server

    monkeypatch.setattr(run_cli, "detect_platform", lambda: platform)
    monkeypatch.setattr(run_cli, "Agent", build_agent)
    monkeypatch.setattr(run_cli, "ControlServer", build_server)
    yield platform, agents, servers
    for server in servers:
        server.stop()


def test_run_serves_the_control_socket_before_the_loop(run_stack):
    platform, agents, servers = run_stack

    assert run_cli.main() == 0

    status, state = agents[0].answered
    assert status == 200
    assert state["version"]
    assert servers[0].socket_path == platform.control_socket_path()


def test_run_takes_no_flags(monkeypatch):
    passed = {}
    monkeypatch.setattr(entry.os, "geteuid", lambda: 0)
    monkeypatch.setattr(entry.sys, "argv", ["nagent", "run"])
    monkeypatch.setattr(entry.run, "main", lambda: passed.update(ran=True) or 0)

    assert entry.main() == 0
    assert passed == {"ran": True}
