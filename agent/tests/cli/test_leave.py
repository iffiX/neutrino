"""``nagent leave``: leaving a hub, asked about first, refused plainly
without root.

Leaving sends ``leave`` through a transport of the command's own, but a hub
that cannot be reached does not hold the machine: the binding goes either
way, and the words say so. The question comes before anything is sent;
``--yes`` skips it, and with no terminal and no ``--yes`` nothing is asked
and nothing changes.
"""

import io

import pytest

import neutrino_agent.cli.entry as entry
import neutrino_agent.cli.leave as leave_cli
import neutrino_agent.core.enrollment as enrollment
import neutrino_agent.core.loop as loop_module
from neutrino_agent.modules.remote_desktop.rdp.host import RdpShareHost
from tests.conftest import HUB_KEY, bind
from tests.transport.fake_transport import FakeTransport, one_shot_for

LEAVE_WORDS = "left the hub; this machine keeps the agent and can join again"


@pytest.fixture(autouse=True)
def _desktop_left(monkeypatch):
    """The desktop host's leave does nothing. No test reaches this machine's
    RustDesk."""
    monkeypatch.setattr(RdpShareHost, "leave_hub", lambda self: None)


@pytest.fixture
def fake(monkeypatch):
    """The transport ``nagent leave`` starts in its own process, played here."""
    transport = FakeTransport()
    opener = one_shot_for(transport)
    monkeypatch.setattr(
        loop_module,
        "one_shot_transport",
        lambda platform, log=None, **keywords: opener(**keywords),
    )
    yield transport
    transport.close()


def leaves(fake) -> list:
    return [line for line in fake.commands if line["command"] == "leave"]


def test_a_bound_machine_leaves_and_says_so(fake, config_path, capsys):
    bind(config_path, url="tcp://192.0.2.5:8443")

    assert leave_cli.main(is_forced=True) == 0

    (leave,) = leaves(fake)
    assert leave["hub_key"] == HUB_KEY
    assert leave["addresses"] == [
        "tcp://hub.neutrino.internal:8443",
        "tcp://192.0.2.5:8443",
    ]
    assert LEAVE_WORDS in capsys.readouterr().out
    assert not config_path.exists()
    assert not enrollment.is_bound()


def test_an_unreachable_hub_does_not_hold_the_machine(fake, config_path, capsys):
    bind(config_path, url="tcp://192.0.2.5:8443")
    fake.answers["leave"] = {"code": "hub_unreachable", "params": {"detail": "x"}}

    assert leave_cli.main(is_forced=True) == 0

    out = capsys.readouterr().out
    assert "could not tell the hub we are leaving: hub_unreachable" in out
    assert LEAVE_WORDS in out
    assert not config_path.exists()


def test_an_unbound_machine_is_told_it_joined_nothing(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", refuse_to_ask)

    assert leave_cli.main(is_forced=False) == 1

    out = capsys.readouterr().out
    assert "this machine has joined no hub" in out
    assert LEAVE_WORDS not in out


def test_an_unprivileged_leave_is_refused_with_the_command(monkeypatch, capsys):
    monkeypatch.setattr(entry.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(entry.sys, "argv", ["nagent", "leave"])

    assert entry.main() == 2

    err = capsys.readouterr().err
    assert "nagent leave needs root (it removes the binding)" in err
    assert "sudo nagent leave" in err


def refuse_to_ask(prompt):
    raise AssertionError("asked")


def posted_leaves(fake) -> list:
    return fake.commands


def test_it_asks_first_and_a_yes_leaves(
    terminal, monkeypatch, config_path, capsys, fake
):
    bind(config_path, url="tcp://192.0.2.5:8443")
    posted = posted_leaves(fake)
    asked = []
    monkeypatch.setattr("builtins.input", lambda prompt: asked.append(prompt) or "y")

    assert leave_cli.main(is_forced=False) == 0

    assert asked == [leave_cli.LEAVE_QUESTION]
    assert "the agent and its service stay [y/N] " in asked[0]
    assert [line["command"] for line in posted] == ["leave"]
    assert not enrollment.is_bound()


def test_a_no_changes_nothing(terminal, monkeypatch, config_path, capsys, fake):
    bind(config_path, url="tcp://192.0.2.5:8443")
    posted = posted_leaves(fake)
    monkeypatch.setattr("builtins.input", lambda prompt: "")

    assert leave_cli.main(is_forced=False) == 1

    assert posted == []
    assert enrollment.is_bound()
    assert "nothing changed" in capsys.readouterr().out


def test_with_no_terminal_it_names_yes_and_changes_nothing(
    monkeypatch, config_path, capsys, fake
):
    bind(config_path, url="tcp://192.0.2.5:8443")
    posted = posted_leaves(fake)
    monkeypatch.setattr("sys.stdin", io.StringIO("y\n"))
    monkeypatch.setattr("builtins.input", refuse_to_ask)

    assert leave_cli.main(is_forced=False) == 1

    assert posted == []
    assert enrollment.is_bound()
    printed = capsys.readouterr()
    assert printed.err.strip().count("\n") == 0
    assert "--yes" in printed.err


def test_yes_on_the_command_line_leaves_without_asking(
    monkeypatch, config_path, capsys, fake
):
    bind(config_path, url="tcp://192.0.2.5:8443")
    posted = posted_leaves(fake)
    monkeypatch.setattr("builtins.input", refuse_to_ask)
    monkeypatch.setattr(entry, "_is_privileged", lambda: True, raising=False)
    monkeypatch.setattr(entry.sys, "argv", ["nagent", "leave", "--yes"])

    assert entry.main() == 0

    assert [line["command"] for line in posted] == ["leave"]
    assert not enrollment.is_bound()


def test_a_leave_says_each_account_it_switched_back(
    monkeypatch, config_path, capsys, fake
):
    bind(config_path, url="tcp://192.0.2.5:8443")
    monkeypatch.setattr(
        loop_module.AiToolsApplier,
        "switch_back_all",
        lambda self: [
            {"account": "alice", "state": "switched_back", "code": "", "params": {}},
            {
                "account": "lab",
                "state": "failed",
                "code": "switch_failed",
                "params": {},
            },
        ],
    )

    assert leave_cli.main(is_forced=True) == 0

    out = capsys.readouterr().out
    assert "ai tools   alice: switched_back\n" in out
    assert "ai tools   lab: failed switch_failed\n" in out
    assert out.index("ai tools   alice") < out.index(LEAVE_WORDS)


@pytest.mark.parametrize("is_told", [True, False])
def test_the_agents_own_log_stays_out_of_the_terminal(
    monkeypatch, config_path, capsys, is_told
):
    bind(config_path, url="tcp://192.0.2.5:8443")
    transport = FakeTransport()
    opener = one_shot_for(transport)
    if not is_told:
        transport.answers["leave"] = {
            "code": "hub_unreachable",
            "params": {"detail": "x"},
        }

    def logging_one_shot(platform, log=print, **keywords):
        log("transport: hub transport started")
        log("transport: control_connected")
        return opener(**keywords)

    monkeypatch.setattr(loop_module, "one_shot_transport", logging_one_shot)
    try:
        assert leave_cli.main(is_forced=True) == 0
    finally:
        transport.close()

    told = [] if is_told else ["could not tell the hub we are leaving: hub_unreachable"]
    assert capsys.readouterr().out.splitlines() == told + [LEAVE_WORDS]
