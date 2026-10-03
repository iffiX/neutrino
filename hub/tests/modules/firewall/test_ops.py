"""Which firewall a routing pass drives, and what it reads to drive it.

What these pin: Windows reads the panel's ports from its settings, the AI
gateway's port from its own, the SOCKS ports from the proxy and the overlays
from the network; macOS hands the
programs of the enabled overlays to its applier; a reset takes everything
away on both.
"""

import pytest

from neutrino_hub.modules.firewall import ops
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig

NETWORK = RouterNetworkConfig.from_dict(
    {
        "mode": "server",
        "interfaces": [],
        "overlays": [{"provider": "netbird", "is_enabled": True}],
    }
)
ROUTING = {"socks_ports": [{"port": 1080, "is_proxied": True}, {"note": "none"}]}


class Recorder:
    """An applier that records what it was handed."""

    handed: list = []

    def __init__(self, **keywords):
        pass

    def apply(self, wanted):
        Recorder.handed.append(("apply", wanted))
        return ["changed"]

    def remove(self, *programs):
        Recorder.handed.append(("remove", *programs))
        return ["removed"]


@pytest.fixture
def recorder(monkeypatch):
    Recorder.handed = []
    monkeypatch.setattr(ops, "FirewallWindowsApplier", Recorder)
    monkeypatch.setattr(ops, "FirewallDarwinApplier", Recorder)
    return Recorder


def test_windows_opens_the_ports_the_settings_name(on_windows, recorder, monkeypatch):
    stored = {
        "web/settings.json": {"listen_port": 9080, "https_listen_port": 9443},
        "cliproxyapi/cliproxyapi.json": {"listen_port": 9317},
    }
    monkeypatch.setattr(ops, "read_config", lambda name: stored[name])

    assert ops.converge_firewall(NETWORK, routing=ROUTING) == ["changed"]

    ((verb, rules),) = recorder.handed
    assert [(rule.name, rule.port) for rule in rules] == [
        ("neutrino_hub_panel_http", 9080),
        ("neutrino_hub_panel_https", 9443),
        ("neutrino_hub_agent", 8443),
        ("neutrino_hub_ai_gateway", 9317),
        ("neutrino_hub_socks_1080_tcp", 1080),
        ("neutrino_hub_socks_1080_udp", 1080),
        ("neutrino_hub_netbird_udp", 51820),
    ]


def test_windows_before_setup_opens_the_default_ports(
    on_windows, recorder, monkeypatch
):
    def missing(name):
        raise FileNotFoundError(name)

    monkeypatch.setattr(ops, "read_config", missing)

    ops.converge_firewall(NETWORK, routing={})

    ((_, rules),) = recorder.handed
    assert [rule.port for rule in rules[:4]] == [8080, 443, 8443, 8317]


def test_macos_allows_the_programs_of_the_enabled_overlays(on_darwin, recorder):
    ops.converge_firewall(NETWORK, routing=ROUTING)

    ((verb, programs),) = recorder.handed
    assert programs[1:] == [
        ops.XRAY_BINARY,
        str(ops.CLIPROXYAPI_BINARY_PATH),
        str(ops.NETBIRD_BINARY_PATH),
    ]


def test_a_reset_takes_everything_away(elsewhere, recorder):
    assert ops.hand_back_firewall() == ["removed"]

    ((verb, *handed),) = recorder.handed
    assert verb == "remove"
    if elsewhere == "darwin":
        assert handed[0][1:] == [
            ops.XRAY_BINARY,
            str(ops.CLIPROXYAPI_BINARY_PATH),
            str(ops.NETBIRD_BINARY_PATH),
            str(ops.EASYTIER_CORE_PATH),
        ]
    else:
        assert handed == []
