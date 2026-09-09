"""``nclient disconnect``: leaving a hub.

Leaving tells the hub first, but a hub that cannot be reached does not hold
the person: the binding goes either way, and a running resident adopts the
change on its next poll.
"""

import neutrino_client.cli.disconnect as disconnect_cli
import neutrino_client.core.channel as channel
import neutrino_client.core.enrollment as enrollment
from neutrino_client.cli import wording
from neutrino_client.core.channel import GatewayUnreachable
from tests.conftest import bind


def test_a_bound_person_leaves_and_says_so(monkeypatch, config_path, capsys):
    bind(config_path, url="https://hub.lan:8443")
    posted = []

    def post(self, path, payload):
        posted.append(path)
        return {}

    monkeypatch.setattr(channel.GatewayHttpChannel, "post", post)

    assert disconnect_cli.main() == 0

    assert posted == ["/api/client/leave"]
    assert disconnect_cli.LEAVE_WORDS in capsys.readouterr().out
    assert "gateway_url" not in enrollment.load_config()


def test_an_unreachable_hub_does_not_hold_the_person(monkeypatch, config_path, capsys):
    bind(config_path, url="https://hub.lan:8443")

    def refuse(self, path, payload):
        raise GatewayUnreachable("cannot reach hub")

    monkeypatch.setattr(channel.GatewayHttpChannel, "post", refuse)

    assert disconnect_cli.main() == 0

    assert disconnect_cli.LEAVE_WORDS in capsys.readouterr().out
    assert "gateway_url" not in enrollment.load_config()


def test_an_unbound_person_is_told_they_joined_nothing(capsys):
    assert disconnect_cli.main() == 1

    out = capsys.readouterr().out
    assert wording.NOT_JOINED in out
    assert disconnect_cli.LEAVE_WORDS not in out
