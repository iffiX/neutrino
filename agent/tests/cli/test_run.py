"""``nagent run``: the control socket serves before the loop does.

Run is what the systemd unit starts. It binds the socket first, so the
agent answers ``nagent`` from the moment the loop begins, and closes it once
the loop has ended. SIGTERM asks the agent to stop rather than ending the
process, so the relays' firewall rules go with the agent.
"""

import signal
import sys
import threading

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
        self.stops = 0

    def stop(self) -> None:
        self.stops += 1

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

    def build_agent(*, platform, log=None):
        agent = FakeRunAgent(platform=platform)
        agent.log = log
        agents.append(agent)
        return agent

    def build_server(**kwargs):
        server = ControlServer(**kwargs)
        servers.append(server)
        return server

    monkeypatch.setattr(run_cli, "detect_platform", lambda: platform)
    monkeypatch.setattr(run_cli, "Agent", build_agent)
    monkeypatch.setattr(run_cli, "ControlServer", build_server)
    handlers = {}
    monkeypatch.setattr(
        run_cli.signal,
        "signal",
        lambda signum, handler: handlers.__setitem__(signum, handler),
    )
    platform.handlers = handlers
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


def test_sigterm_asks_the_agent_to_stop(run_stack):
    platform, agents, _ = run_stack

    run_cli.main()
    platform.handlers[signal.SIGTERM](signal.SIGTERM, None)

    assert agents[0].stops == 1


def test_run_takes_no_flags(monkeypatch):
    passed = {}
    monkeypatch.setattr(entry.os, "geteuid", lambda: 0)
    monkeypatch.setattr(entry.sys, "argv", ["nagent", "run"])
    monkeypatch.setattr(entry.run, "main", lambda: passed.update(ran=True) or 0)

    assert entry.main() == 0
    assert passed == {"ran": True}


class InterleavingStdout:
    """A stdout whose first write of text with no newline waits for another thread's write."""

    def __init__(self):
        self.text = ""
        self.flushes = 0
        self.entered = threading.Event()
        self._other_wrote = threading.Event()
        self._lock = threading.Lock()
        self._first = None

    def write(self, text: str) -> int:
        with self._lock:
            self.text += text
            if self._first is None:
                self._first = threading.current_thread()
            is_first = self._first is threading.current_thread()
        if not is_first:
            self._other_wrote.set()
        elif not text.endswith("\n") and not self.entered.is_set():
            self.entered.set()
            self._other_wrote.wait(timeout=2.0)
        self.entered.set()
        return len(text)

    def flush(self) -> None:
        self.flushes += 1


def test_the_log_prints_whole_flushed_lines_where_a_journal_reads_the_output(
    run_stack, monkeypatch
):
    platform, _, _ = run_stack
    stdout = InterleavingStdout()
    monkeypatch.setattr(sys, "stdout", stdout)
    sink = run_cli.log_sink(platform)

    first = threading.Thread(target=sink, args=("ayakaleaf: answers on port 8900",))
    first.start()
    assert stdout.entered.wait(timeout=2.0)
    second = threading.Thread(target=sink, args=("ayakaleaf: running",))
    second.start()
    first.join(timeout=5.0)
    second.join(timeout=5.0)

    assert stdout.text.splitlines() == [
        "ayakaleaf: answers on port 8900",
        "ayakaleaf: running",
    ]
    assert stdout.flushes == 2


def test_the_log_is_the_agent_log_file_on_macos(run_stack, monkeypatch, tmp_path):
    platform, _, _ = run_stack
    monkeypatch.setattr(platform, "os_name", "darwin", raising=False)
    monkeypatch.setattr(
        platform, "agent_log_path", lambda: str(tmp_path / "agent.log"), raising=False
    )
    sink = run_cli.log_sink(platform)
    sink("hello from the daemon")
    assert "hello from the daemon" in (tmp_path / "agent.log").read_text()
