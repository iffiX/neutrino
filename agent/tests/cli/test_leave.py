"""``nagent leave``: leaving a hub, asked about first, refused plainly
without root.

Leaving posts the binding back, but a hub that cannot be reached does not
hold the machine: the binding goes either way, and the words say so. The
question comes before anything is posted; ``--yes`` skips it, and with no
terminal and no ``--yes`` nothing is asked and nothing changes.
"""

import io

import neutrino_agent.cli.entry as entry
import neutrino_agent.cli.leave as leave_cli
import neutrino_agent.core.channel as channel
import neutrino_agent.core.enrollment as enrollment
from neutrino_agent.exceptions import GatewayUnreachable
from tests.conftest import BINDING_ID, BINDING_TOKEN, bind

LEAVE_WORDS = "left the hub; this machine keeps the agent and can join again"


def test_a_bound_machine_leaves_and_says_so(monkeypatch, config_path, capsys):
    bind(config_path, url="https://hub.lan:8443")
    posted = []

    def leave(self, binding_id, token):
        posted.append((self._gateway_url, binding_id, token))

    monkeypatch.setattr(channel.BindingHttpClient, "leave", leave)

    assert leave_cli.main(is_forced=True) == 0

    assert posted == [("https://hub.lan:8443", BINDING_ID, BINDING_TOKEN)]
    assert LEAVE_WORDS in capsys.readouterr().out
    assert not config_path.exists()
    assert not enrollment.is_bound()


def test_an_unreachable_hub_does_not_hold_the_machine(monkeypatch, config_path, capsys):
    bind(config_path, url="https://hub.lan:8443")

    def refuse(self, binding_id, token):
        raise GatewayUnreachable("cannot reach hub")

    monkeypatch.setattr(channel.BindingHttpClient, "leave", refuse)

    assert leave_cli.main(is_forced=True) == 0

    out = capsys.readouterr().out
    assert "could not tell the hub we are leaving: hub_unreachable" in out
    assert LEAVE_WORDS in out
    assert not config_path.exists()


def test_an_unbound_machine_is_told_it_joined_nothing(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", refuse_to_ask)

    assert leave_cli.main(is_forced=False) == 1

    out = capsys.readouterr().out
    assert "this machine has joined no gateway" in out
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


def posted_leaves(monkeypatch) -> list:
    posted: list = []
    monkeypatch.setattr(
        channel.BindingHttpClient,
        "leave",
        lambda self, binding_id, token: posted.append(binding_id),
    )
    return posted


def test_it_asks_first_and_a_yes_leaves(terminal, monkeypatch, config_path, capsys):
    bind(config_path, url="https://hub.lan:8443")
    posted = posted_leaves(monkeypatch)
    asked = []
    monkeypatch.setattr("builtins.input", lambda prompt: asked.append(prompt) or "y")

    assert leave_cli.main(is_forced=False) == 0

    assert asked == [leave_cli.LEAVE_QUESTION]
    assert "the agent and its service stay [y/N] " in asked[0]
    assert posted == [BINDING_ID]
    assert not enrollment.is_bound()


def test_a_no_changes_nothing(terminal, monkeypatch, config_path, capsys):
    bind(config_path, url="https://hub.lan:8443")
    posted = posted_leaves(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda prompt: "")

    assert leave_cli.main(is_forced=False) == 1

    assert posted == []
    assert enrollment.is_bound()
    assert "nothing changed" in capsys.readouterr().out


def test_with_no_terminal_it_names_yes_and_changes_nothing(
    monkeypatch, config_path, capsys
):
    bind(config_path, url="https://hub.lan:8443")
    posted = posted_leaves(monkeypatch)
    monkeypatch.setattr("sys.stdin", io.StringIO("y\n"))
    monkeypatch.setattr("builtins.input", refuse_to_ask)

    assert leave_cli.main(is_forced=False) == 1

    assert posted == []
    assert enrollment.is_bound()
    printed = capsys.readouterr()
    assert printed.err.strip().count("\n") == 0
    assert "--yes" in printed.err


def test_yes_on_the_command_line_leaves_without_asking(
    monkeypatch, config_path, capsys
):
    bind(config_path, url="https://hub.lan:8443")
    posted = posted_leaves(monkeypatch)
    monkeypatch.setattr("builtins.input", refuse_to_ask)
    monkeypatch.setattr(entry, "_is_privileged", lambda: True, raising=False)
    monkeypatch.setattr(entry.sys, "argv", ["nagent", "leave", "--yes"])

    assert entry.main() == 0

    assert posted == [BINDING_ID]
    assert not enrollment.is_bound()


def test_a_leave_says_each_account_it_switched_back(monkeypatch, config_path, capsys):
    import neutrino_agent.core.loop as loop

    bind(config_path, url="https://hub.lan:8443")
    monkeypatch.setattr(
        channel.BindingHttpClient, "leave", lambda self, binding_id, token: None
    )
    monkeypatch.setattr(
        loop.AiToolsApplier,
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
