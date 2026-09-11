"""What the browser is asked against is what the terminal is asked against.

Two wizards drifting apart is the failure this guards: a mode offered in one
and not the other, or a default that differs, is a machine set up two ways
depending on where somebody happened to answer.
"""

from neutrino_hub.cli import wizard
from neutrino_hub.exceptions import WizardAborted


def test_the_context_offers_the_modes_the_screens_offer(monkeypatch):
    monkeypatch.setattr(wizard, "RouterLinkStatus", _one_wired_port)

    context = wizard.context()

    assert [mode["key"] for mode in context["modes"]] == [
        mode.key for mode in wizard.modes_for(1, 1)
    ]


def test_the_context_names_what_each_port_is_doing(monkeypatch):
    """Which port to offer is decided from these, so they travel with it."""
    monkeypatch.setattr(wizard, "RouterLinkStatus", _one_wired_port)
    port = wizard.context()["interfaces"][0]

    assert port == {
        "name": "eth0",
        "is_wired": True,
        "ipv4_address": "192.168.1.5/24",
        "has_route": True,
        "upstream_gateway": "192.168.1.1",
    }


def test_a_machine_with_no_port_is_refused_the_same_way(monkeypatch):
    monkeypatch.setattr(wizard, "RouterLinkStatus", _no_ports)

    try:
        wizard.context()
    except WizardAborted as error:
        assert "no network interface" in str(error)
    else:
        raise AssertionError("a machine with no port cannot be a gateway")


class _one_wired_port:
    def all_links(self):
        return [_Link(name="eth0"), _Link(name="lo", ipv4_address="127.0.0.1/8")]

    def gateway_for(self, name):
        return "192.168.1.1" if name == "eth0" else None


class _no_ports:
    def all_links(self):
        return []

    def gateway_for(self, name):
        return None


class _Link:
    def __init__(self, *, name, ipv4_address="192.168.1.5/24"):
        self.name = name
        self.is_wifi = False
        self.is_up = True
        self.ipv4_address = ipv4_address
