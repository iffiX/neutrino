"""``nagent status``: what the operator reads must never lie about the box.

The matrix is walked as the person types it: privileged and ordinary, the
service alive and dead, bound and unbound. The running service is asked
first over its socket; the binding file answers only when nothing does, and
a binding this account may not read is said to be that, never read as no
binding at all.
"""

import pytest

from neutrino_agent import AGENT_VERSION
from neutrino_agent.cli import entry
from neutrino_agent.cli import status as status_cli
from neutrino_agent.control import client
from neutrino_agent.control.server import ControlServer
from tests.conftest import (
    ALICE,
    ROOT,
    FakeControlAgent,
    FakeControlPlatform,
    bind,
    discard,
)

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


def refuse_the_binding(*args, **kwargs):
    """The kernel refusing an ordinary account the root-owned binding."""
    raise PermissionError(13, "Permission denied")


class FakeStatusPlatform(FakeControlPlatform):
    """The machine status asks: one socket path, one unit state."""

    def __init__(self, socket_path: str, *, unit_state: str = "running"):
        super().__init__()
        self._socket_path = socket_path
        self._unit_state = unit_state

    def control_socket_path(self) -> str:
        return self._socket_path

    def read_agent_service_state(self) -> str:
        return self._unit_state


@pytest.fixture(scope="module")
def service_stack(tmp_path_factory):
    """One running service for the whole module, on its own socket."""
    platform = FakeStatusPlatform(str(tmp_path_factory.mktemp("status") / "agent.sock"))
    server = ControlServer(
        agent=FakeControlAgent(),
        platform=platform,
        log=discard,
        socket_path=platform.control_socket_path(),
        is_page_served=False,
    )
    server.start()
    assert server.socket_path
    yield server, platform
    server.stop()


@pytest.fixture
def running_service(service_stack, monkeypatch):
    """The agent's own service, answering this test as root by default."""
    server, platform = service_stack
    platform.peer = dict(ROOT)
    platform.peer_error = None
    monkeypatch.setattr(status_cli, "detect_platform", lambda: platform)
    return server, platform


def test_status_reads_the_running_service_for_a_privileged_caller(
    running_service, config_path, capsys
):
    bind(config_path, url=GATEWAY_URL)

    assert status_cli.main() == 0

    out = capsys.readouterr().out
    assert f"neutrino-agent {AGENT_VERSION}" in out
    assert f"hub        {GATEWAY_URL}   connected" in out
    assert "service    running" in out
    assert "heartbeat  ok — the service reports every few seconds" in out


def test_status_falls_back_to_the_binding_file_and_beats_once(
    tmp_path, config_path, monkeypatch, capsys
):
    bind(config_path, url=GATEWAY_URL)
    serve_nothing(monkeypatch, tmp_path)
    beats = []

    class ProbingAgent:
        def __init__(self, *, log):
            del log

        def run_once(self) -> int:
            beats.append("beat")
            return 5

        def last_error(self):
            return None

    monkeypatch.setattr(status_cli, "Agent", ProbingAgent)

    assert status_cli.main() == 0

    out = capsys.readouterr().out
    assert beats == ["beat"]
    assert f"hub        {GATEWAY_URL}   connected" in out
    assert "service    inactive — the machine beats only while status runs" in out
    assert "sudo systemctl enable --now neutrino_agent.service" in out
    assert "heartbeat  ok," in out
    assert "next report in 5s" in out


def test_status_says_a_privileged_caller_has_joined_nothing(
    tmp_path, monkeypatch, capsys
):
    serve_nothing(monkeypatch, tmp_path)

    assert status_cli.main() == 1

    out = capsys.readouterr().out
    assert "hub        this machine has joined no gateway" in out
    assert "service    inactive" in out
    assert "heartbeat" not in out


def test_status_answers_an_ordinary_caller_in_its_own_scope(
    running_service, config_path, capsys
):
    bind(config_path, url=GATEWAY_URL)
    server, platform = running_service
    platform.peer = dict(ALICE)

    assert status_cli.main() == 0

    out = capsys.readouterr().out
    assert f"hub        {GATEWAY_URL}   connected" in out
    assert "service    running" in out
    status, state = client.request(
        socket_path=server.socket_path, method="GET", path="/api/state"
    )
    assert status == 200
    assert state["accounts"] == ["alice"]
    assert state["caller"]["is_privileged"] is False


def test_status_keeps_the_unit_state_true_when_the_socket_refuses_the_caller(
    running_service, config_path, monkeypatch, capsys
):
    bind(config_path, url=GATEWAY_URL)
    _server, platform = running_service
    platform.peer_error = KeyError("uid 1000 names no account")
    monkeypatch.setattr(status_cli, "open", refuse_the_binding, raising=False)

    assert status_cli.main() == 1

    out = capsys.readouterr().out
    assert "hub        the binding is root's to read: sudo nagent status" in out
    assert "service    running" in out
    assert "joined no gateway" not in out


def test_status_names_sudo_and_the_units_real_state(tmp_path, monkeypatch, capsys):
    serve_nothing(monkeypatch, tmp_path)
    monkeypatch.setattr(status_cli, "open", refuse_the_binding, raising=False)

    assert status_cli.main() == 1

    out = capsys.readouterr().out
    assert "hub        the binding is root's to read: sudo nagent status" in out
    assert "service    inactive" in out
    assert "joined no gateway" not in out


def test_status_says_an_ordinary_callers_machine_has_joined_nothing(
    running_service, capsys
):
    _server, platform = running_service
    platform.peer = dict(ALICE)

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

        def run_once(self) -> int:
            return 5

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

        def run_once(self) -> int:
            return 5

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


def test_the_version_answers_any_caller(monkeypatch, capsys):
    monkeypatch.setattr(entry.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(entry.sys, "argv", ["nagent", "--version"])

    with pytest.raises(SystemExit) as refusal:
        entry.main()

    assert refusal.value.code == 0
    assert AGENT_VERSION in capsys.readouterr().out
