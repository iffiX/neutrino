"""``nagent status``: what the operator reads must never lie about the box.

Three things break independently, and a device missing from the panel looks
the same for all three: the machine never joined, the service is not
running, or the hub cannot be reached. The running service is asked first
over its socket; the binding file answers only when nothing does, and then
status connects once itself to see whether the hub welcomes this machine.
"""

import pytest

from neutrino_agent import AGENT_VERSION
from neutrino_agent.cli import status as status_cli
from neutrino_agent.control.server import ControlServer
from tests.conftest import FakeControlAgent, FakeControlPlatform, bind, discard

GATEWAY_URL = "https://hub.lan:8443"


def serve_nothing(monkeypatch, tmp_path, *, unit_state="inactive"):
    """No service on the socket, and the unit state the platform reports.

    Args:
        monkeypatch: The test's patcher.
        tmp_path: Where the absent socket would be.
        unit_state: What the platform says about the agent's own service.

    Returns:
        The platform ``nagent status`` will ask.
    """
    platform = FakeStatusPlatform(str(tmp_path / "missing.sock"), unit_state=unit_state)
    monkeypatch.setattr(status_cli, "detect_platform", lambda: platform)
    return platform


class FakeStatusPlatform(FakeControlPlatform):
    """The machine status asks: one socket path, one unit state."""

    def __init__(self, socket_path: str, *, unit_state: str = "running"):
        self._socket_path = socket_path
        self._unit_state = unit_state

    def control_socket_path(self) -> str:
        return self._socket_path

    def read_agent_service_state(self) -> str:
        return self._unit_state


@pytest.fixture(scope="module")
def service_stack(tmp_path_factory):
    """One running service for the whole module, on its own socket."""
    root = tmp_path_factory.mktemp("status")
    platform = FakeStatusPlatform(str(root / "run" / "agent.sock"))
    server = ControlServer(
        agent=FakeControlAgent(),
        platform=platform,
        log=discard,
        socket_path=platform.control_socket_path(),
    )
    server.start()
    assert server.socket_path
    yield server, platform
    server.stop()


@pytest.fixture
def running_service(service_stack, monkeypatch):
    """The agent's own service, on the socket status will ask."""
    server, platform = service_stack
    monkeypatch.setattr(status_cli, "detect_platform", lambda: platform)
    return server, platform


def test_status_reads_the_running_service_for_a_privileged_caller(
    running_service, config_path, capsys
):
    server, _ = running_service
    bind(config_path, url=GATEWAY_URL)
    server._agent.is_socket_open = True

    assert status_cli.main() == 0

    out = capsys.readouterr().out
    assert f"neutrino-agent {AGENT_VERSION}" in out
    assert f"hub        {GATEWAY_URL}   connected" in out
    assert "service    running" in out
    assert "heartbeat  ok. The service holds its socket to the hub" in out


def test_status_says_when_the_running_service_is_still_connecting(
    running_service, config_path, capsys
):
    server, _ = running_service
    bind(config_path, url=GATEWAY_URL)
    server._agent.is_socket_open = False

    assert status_cli.main() == 1

    out = capsys.readouterr().out
    assert "heartbeat  connecting. The service is reaching the hub" in out


def test_status_falls_back_to_the_binding_file_and_connects_once(
    tmp_path, config_path, monkeypatch, capsys
):
    bind(config_path, url=GATEWAY_URL)
    serve_nothing(monkeypatch, tmp_path)
    probes = []

    class ProbingAgent:
        def __init__(self, *, log):
            del log

        def probe(self) -> None:
            probes.append("probe")

        def last_error(self):
            return None

    monkeypatch.setattr(status_cli, "Agent", ProbingAgent)

    assert status_cli.main() == 0

    out = capsys.readouterr().out
    assert probes == ["probe"]
    assert f"hub        {GATEWAY_URL}   connected" in out
    assert "service    inactive. The machine reports only while it runs" in out
    assert "sudo systemctl enable --now neutrino_agent.service" in out
    assert "heartbeat  ok," in out
    assert "The hub answered this machine's hello" in out


def test_status_says_a_privileged_caller_has_joined_nothing(
    tmp_path, monkeypatch, capsys
):
    serve_nothing(monkeypatch, tmp_path)

    assert status_cli.main() == 1

    out = capsys.readouterr().out
    assert "hub        this machine has joined no gateway" in out
    assert "service    inactive" in out
    assert "heartbeat" not in out


def test_status_says_a_running_service_has_joined_nothing(running_service, capsys):
    assert status_cli.main() == 1

    out = capsys.readouterr().out
    assert "hub        this machine has joined no gateway" in out
    assert "service    running" in out


@pytest.mark.parametrize(
    "error, sentence",
    [
        (
            {"code": "hub_refused", "params": {}},
            "the hub refused this machine's token",
        ),
        (
            {"code": "hub_untrusted", "params": {}},
            "what answers is not the hub this machine pinned",
        ),
        (
            {
                "code": "agent_newer_than_hub",
                "params": {"hub_version": "0.1.0", "agent_version": "0.2.0"},
            },
            "this agent (0.2.0) is newer than the hub (0.1.0); update the hub first",
        ),
        (
            {
                "code": "agent_wire_stale",
                "params": {"hub_wire": 3, "agent_wire": 2},
            },
            "this agent's build does not match the hub; it reinstalls itself "
            "from the hub's package",
        ),
    ],
)
def test_status_words_every_heartbeat_refusal(
    error, sentence, tmp_path, config_path, monkeypatch, capsys
):
    bind(config_path, url=GATEWAY_URL)
    serve_nothing(monkeypatch, tmp_path, unit_state="running")

    class RefusedAgent:
        def __init__(self, *, log):
            del log

        def probe(self) -> None:
            return None

        def last_error(self):
            return error

    monkeypatch.setattr(status_cli, "Agent", RefusedAgent)

    assert status_cli.main() == 1

    out = capsys.readouterr().out
    assert f"heartbeat  {sentence}" in out
    assert error["code"] not in out


def test_status_words_a_version_refusal_distinctly(
    tmp_path, config_path, monkeypatch, capsys
):
    bind(config_path)
    serve_nothing(monkeypatch, tmp_path, unit_state="running")

    class StuckAgent:
        def __init__(self, *, log):
            del log

        def probe(self) -> None:
            return None

        def last_error(self):
            return {
                "code": "agent_newer_than_hub",
                "params": {"hub_version": "0.1.0", "agent_version": "0.2.0"},
            }

    monkeypatch.setattr(status_cli, "Agent", StuckAgent)

    assert status_cli.main() == 1

    out = capsys.readouterr().out
    assert "newer than the hub" in out
    assert "unbinds by itself" in out
    assert "fresh link" in out
