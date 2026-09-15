"""``nagent leave``: leaving a hub, refused plainly without root.

Leaving posts the binding back, but a hub that cannot be reached does not
hold the machine: the binding goes either way, and the words say so.
"""

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

    assert leave_cli.main() == 0

    assert posted == [("https://hub.lan:8443", BINDING_ID, BINDING_TOKEN)]
    assert LEAVE_WORDS in capsys.readouterr().out
    assert not config_path.exists()
    assert not enrollment.is_bound()


def test_an_unreachable_hub_does_not_hold_the_machine(monkeypatch, config_path, capsys):
    bind(config_path, url="https://hub.lan:8443")

    def refuse(self, binding_id, token):
        raise GatewayUnreachable("cannot reach hub")

    monkeypatch.setattr(channel.BindingHttpClient, "leave", refuse)

    assert leave_cli.main() == 0

    out = capsys.readouterr().out
    assert "could not tell the hub we are leaving: hub_unreachable" in out
    assert LEAVE_WORDS in out
    assert not config_path.exists()


def test_an_unbound_machine_is_told_it_joined_nothing(capsys):
    assert leave_cli.main() == 1

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
