"""``nagent sync``: ask the running service to fetch the hub's state now.

The service holds the socket, so the verb goes through the control channel;
what the operator reads is whether the ask went up, and why not otherwise.
"""

import pytest

from neutrino_agent.cli import sync as sync_cli
from neutrino_agent.control.server import ControlServer
from tests.conftest import FakeControlAgent, FakeSocketPlatform, bind, discard


@pytest.fixture(scope="module")
def service_stack(tmp_path_factory):
    """One running service for the whole module, on its own socket."""
    root = tmp_path_factory.mktemp("sync")
    platform = FakeSocketPlatform(str(root / "run" / "agent.sock"))
    agent = FakeControlAgent()
    server = ControlServer(
        agent=agent,
        platform=platform,
        log=discard,
        socket_path=platform.control_socket_path(),
    )
    server.start()
    assert server.socket_path
    yield server, agent, platform
    server.stop()


@pytest.fixture
def running_service(service_stack, monkeypatch):
    server, agent, platform = service_stack
    FakeControlAgent.__init__(agent)
    monkeypatch.setattr(sync_cli, "detect_platform", lambda: platform)
    return server, agent


def test_sync_asks_the_running_service(running_service, config_path, capsys):
    _, agent = running_service
    bind(config_path)

    assert sync_cli.main() == 0

    assert agent.syncs == 1
    assert "asked the hub for this machine's state" in capsys.readouterr().out


def test_sync_says_the_machine_has_joined_nothing(running_service, capsys):
    _, agent = running_service

    assert sync_cli.main() == 1

    assert agent.syncs == 1
    assert "this machine has joined no gateway" in capsys.readouterr().out


def test_sync_words_a_refusal(running_service, config_path, capsys):
    _, agent = running_service
    bind(config_path)
    agent.sync_reply = {"code": "hub_unreachable", "params": {}}

    assert sync_cli.main() == 1

    out = capsys.readouterr().out
    assert "the hub cannot be reached" in out
    assert "hub_unreachable" not in out


def test_sync_with_no_service_says_so(tmp_path, monkeypatch, capsys):
    platform = FakeSocketPlatform(str(tmp_path / "missing.sock"))
    monkeypatch.setattr(sync_cli, "detect_platform", lambda: platform)

    assert sync_cli.main() == 1

    assert "the agent service is not running" in capsys.readouterr().out
