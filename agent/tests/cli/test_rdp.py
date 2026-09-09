"""``nagent rdp``: the operator's walk through sharing this desktop.

The password is asked at the terminal and travels only in the one request
that sends it. Which desktop is shared is the seat's: with no account named,
the one that invoked sudo, else the one account at the screen.
"""

import pytest

import neutrino_agent.cli.rdp as rdp_cli
import neutrino_agent.cli.wording as wording
from neutrino_agent.control.server import ControlServer
from tests.conftest import FakeControlAgent, FakeControlPlatform, discard


class FakeRdpPlatform(FakeControlPlatform):
    """The machine the command asks: one control socket path."""

    def __init__(self, socket_path: str):
        self._socket_path = socket_path

    def control_socket_path(self) -> str:
        return self._socket_path


@pytest.fixture
def running_agent(tmp_path, monkeypatch):
    """A live control server, and the agent behind it."""
    platform = FakeRdpPlatform(str(tmp_path / "run" / "agent.sock"))
    agent = FakeControlAgent()
    server = ControlServer(
        agent=agent,
        platform=platform,
        log=discard,
        socket_path=platform.control_socket_path(),
    )
    server.start()
    monkeypatch.setattr(wording, "detect_platform", lambda: platform)
    monkeypatch.delenv("SUDO_USER", raising=False)
    yield agent
    server.stop()


# --- whose desktop, when nobody says ---


def test_the_sudo_invoker_is_the_default_seat(running_agent, monkeypatch, capsys):
    monkeypatch.setenv("SUDO_USER", "alice")

    assert rdp_cli.main_start() == 0

    assert running_agent.rdp_calls == ["alice"]
    assert capsys.readouterr().out.strip() == "not shared"


def test_the_one_account_at_the_screen_is_the_next_default(running_agent, monkeypatch):
    monkeypatch.setattr(rdp_cli, "graphical_accounts", lambda: ["sam"])

    assert rdp_cli.main_start() == 0

    assert running_agent.rdp_calls == ["sam"]


def test_a_named_account_wins_over_both(running_agent, monkeypatch):
    monkeypatch.setenv("SUDO_USER", "alice")
    monkeypatch.setattr(rdp_cli, "graphical_accounts", lambda: ["sam"])

    assert rdp_cli.main_start(user="pat") == 0

    assert running_agent.rdp_calls == ["pat"]


@pytest.mark.parametrize("seated", [[], ["sam", "pat"], None])
def test_no_seat_it_can_name_is_the_typed_refusal(
    running_agent, monkeypatch, capsys, seated
):
    monkeypatch.setattr(rdp_cli, "graphical_accounts", lambda: seated)

    assert rdp_cli.main_start() == 2

    assert running_agent.rdp_calls == []
    assert wording.word_code("rdp_no_seat") in capsys.readouterr().err


# --- the password nobody at this machine types ---


def test_starting_a_share_asks_for_no_password_at_all(running_agent, monkeypatch):
    """The seat password is the hub's; the terminal never sees one."""

    def refuse(prompt):
        raise AssertionError("the seat password is not typed here")

    monkeypatch.setenv("SUDO_USER", "alice")
    monkeypatch.setattr(wording, "ask_secret", refuse)

    assert rdp_cli.main_start() == 0

    assert running_agent.rdp_calls == ["alice"]


# --- the share line ---


def test_a_share_prints_where_a_peer_reaches_it(running_agent, monkeypatch, capsys):
    monkeypatch.setenv("SUDO_USER", "alice")
    running_agent.share.update(
        {"is_shared": True, "state": "sharing", "account": "alice"}
    )

    assert rdp_cli.main_start() == 0

    out = capsys.readouterr().out
    assert ":21118 — shared" in out
    assert "RustDesk ID 123456789" in out
    assert "hunter2" not in out


def test_a_refusal_is_worded_and_nothing_is_printed_as_a_share(
    running_agent, monkeypatch, capsys
):
    monkeypatch.setenv("SUDO_USER", "alice")
    running_agent.rdp_reply = {
        "code": "rdp_wrong_seat",
        "params": {"account": "alice"},
    }

    assert rdp_cli.main_start() == 1

    captured = capsys.readouterr()
    assert "alice is not signed in at this machine's screen" in captured.err
    assert captured.out == ""


# --- stopping ---


def test_stopping_a_machine_that_shares_nothing_asks_nothing(running_agent, capsys):
    assert rdp_cli.main_stop() == 0

    assert running_agent.is_unshared is False
    assert capsys.readouterr().out.strip() == rdp_cli.RDP_NOT_SHARED


def test_stopping_a_share_rides_through(running_agent, capsys):
    running_agent.share.update({"is_shared": True, "state": "sharing"})

    assert rdp_cli.main_stop() == 0

    assert running_agent.is_unshared is True
    assert capsys.readouterr().out.strip() == rdp_cli.RDP_NOT_SHARED


# --- nothing answering ---


def test_no_agent_running_is_the_honest_line(tmp_path, monkeypatch, capsys):
    platform = FakeRdpPlatform(str(tmp_path / "absent.sock"))
    monkeypatch.setattr(wording, "detect_platform", lambda: platform)
    monkeypatch.setenv("SUDO_USER", "alice")

    assert rdp_cli.main_start() == 1
    assert rdp_cli.main_stop() == 1

    assert wording.AGENT_NOT_RUNNING in capsys.readouterr().err
