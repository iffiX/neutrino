"""``nagent disconnect``: leaving a hub, refused plainly without root.

Leaving tells the hub first, but a hub that cannot be reached does not hold
the machine: the binding goes either way, and the words say so.
"""

import neutrino_agent.cli.disconnect as disconnect_cli
import neutrino_agent.cli.entry as entry
import neutrino_agent.core.channel as channel
import neutrino_agent.core.enrollment as enrollment
from neutrino_agent.core.channel import GatewayUnreachable
from tests.conftest import bind

LEAVE_WORDS = "left the hub; this machine keeps the agent and can join again"


def test_a_bound_machine_leaves_and_says_so(monkeypatch, config_path, capsys):
    bind(config_path, url="https://hub.lan:8443")
    posted = []

    def post(self, path, payload):
        posted.append(path)
        return {}

    monkeypatch.setattr(channel.GatewayHttpChannel, "post", post)

    assert disconnect_cli.main() == 0

    assert posted == ["/api/agent/leave"]
    assert LEAVE_WORDS in capsys.readouterr().out
    assert "gateway_url" not in enrollment.load_config()


def test_an_unreachable_hub_does_not_hold_the_machine(monkeypatch, config_path, capsys):
    bind(config_path, url="https://hub.lan:8443")

    def refuse(self, path, payload):
        raise GatewayUnreachable("cannot reach gateway")

    monkeypatch.setattr(channel.GatewayHttpChannel, "post", refuse)

    assert disconnect_cli.main() == 0

    assert LEAVE_WORDS in capsys.readouterr().out
    assert "gateway_url" not in enrollment.load_config()


def test_an_unbound_machine_is_told_it_joined_nothing(capsys):
    assert disconnect_cli.main() == 1

    out = capsys.readouterr().out
    assert "this machine has joined no gateway" in out
    assert LEAVE_WORDS not in out


def test_an_unprivileged_disconnect_is_refused_with_the_command(monkeypatch, capsys):
    monkeypatch.setattr(entry.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(entry.sys, "argv", ["nagent", "disconnect"])

    assert entry.main() == 2

    err = capsys.readouterr().err
    assert "nagent disconnect needs root — it removes the binding" in err
    assert "sudo nagent disconnect" in err
