"""``nagent run``: the control socket serves before the loop does.

Run is what the systemd unit starts. It binds the socket first, so the
agent answers ``nagent`` from the moment the loop begins, and closes it once
the loop has ended.
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
    assert servers[0].socket_path == ""


def test_on_macos_sigterm_asks_the_loop_to_end_with_a_deadline(run_stack, monkeypatch):
    handlers = {}
    timers = []

    class Timer:
        def __init__(self, seconds, function, args=()):
            timers.append((seconds, function, args))
            self.daemon = False

        def start(self):
            pass

    monkeypatch.setattr(run_cli.sys, "platform", "darwin")
    monkeypatch.setattr(
        run_cli.signal,
        "signal",
        lambda number, handler: handlers.update({number: handler}),
    )
    monkeypatch.setattr(run_cli.threading, "Timer", Timer)
    stopped = []
    monkeypatch.setattr(
        FakeRunAgent, "stop", lambda self: stopped.append(self), raising=False
    )

    assert run_cli.main() == 0
    handlers[run_cli.signal.SIGTERM](run_cli.signal.SIGTERM, None)

    platform, agents, servers = run_stack
    assert stopped == agents
    assert timers == [(run_cli.AGENT_SERVICE_STOP_WAIT_S, run_cli.os._exit, (0,))]
    assert servers[0].socket_path == ""


def test_run_takes_no_flags(monkeypatch):
    passed = {}
    monkeypatch.setattr(entry.os, "geteuid", lambda: 0)
    monkeypatch.setattr(entry.sys, "argv", ["nagent", "run"])
    monkeypatch.setattr(entry.run, "main", lambda: passed.update(ran=True) or 0)

    assert entry.main() == 0
    assert passed == {"ran": True}
