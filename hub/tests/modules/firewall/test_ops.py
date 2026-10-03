"""Which firewall a routing pass drives, and what it reads to drive it.

What these pin: Windows reads the panel's ports from its settings, the AI
gateway's port from its own, the SOCKS ports from the proxy and the overlays
from the network; every rule answers on the exposed interfaces the box has,
an interface the configuration does not name among them, and on the exposed
overlays' devices; macOS hands the programs of the enabled overlays and the
pf anchor to its applier, and loads the kept anchor again at start; a reset
takes everything away on both.
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
EXPOSURE = RouterNetworkConfig.from_dict(
    {
        "mode": "server",
        "interfaces": [
            {"name": "Ethernet Instance 0 2", "is_exposed": True},
            {"name": "Wi-Fi", "is_exposed": False},
        ],
        "overlays": [
            {"provider": "netbird", "is_enabled": True, "is_exposed": True},
            {"provider": "easytier", "is_enabled": True, "is_exposed": False},
        ],
    }
).with_overlay_devices({"netbird": ["wt0"], "easytier": ["et_2_zqdp"]})
PRESENT = {
    "Ethernet Instance 0 2": "10.0.0.7/24",
    "Wi-Fi": "192.168.1.20/24",
    "Ethernet 3": "172.16.0.2/24",
    "wt0": "100.88.38.71/16",
    "et_2_zqdp": "10.144.144.1/24",
}


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

    def load_anchor(self, rules):
        Recorder.handed.append(("load_anchor", rules))
        return []

    def reload_anchor(self):
        Recorder.handed.append(("reload_anchor",))

    def flush_anchor(self):
        Recorder.handed.append(("flush_anchor",))
        return ["flushed"]


class WindowsRecorder(Recorder):
    """The Windows applier, which answers its refusals beside its notes."""

    def apply(self, wanted):
        return super().apply(wanted), []


@pytest.fixture
def recorder(monkeypatch):
    Recorder.handed = []
    monkeypatch.setattr(ops, "FirewallWindowsApplier", WindowsRecorder)
    monkeypatch.setattr(ops, "FirewallDarwinApplier", Recorder)
    monkeypatch.setattr(ops, "device_addresses", lambda: dict(PRESENT))
    return Recorder


def test_windows_opens_the_ports_the_settings_name(on_windows, recorder, monkeypatch):
    stored = {
        "web/settings.json": {"listen_port": 9080, "https_listen_port": 9443},
        "cliproxyapi/cliproxyapi.json": {"listen_port": 9317},
    }
    monkeypatch.setattr(ops, "read_config", lambda name: stored[name])

    assert ops.converge_firewall(NETWORK, routing=ROUTING) == (["changed"], [])

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


def test_windows_answers_on_the_exposed_interfaces_and_overlays(
    on_windows, recorder, monkeypatch
):
    monkeypatch.setattr(ops, "read_config", lambda name: {})

    ops.converge_firewall(EXPOSURE, routing=ROUTING)

    ((_, rules),) = recorder.handed
    answering = ("Ethernet Instance 0 2", "Ethernet 3", "wt0")
    assert {rule.name: rule.interfaces for rule in rules} == {
        "neutrino_hub_panel_http": answering,
        "neutrino_hub_panel_https": answering,
        "neutrino_hub_agent": answering,
        "neutrino_hub_ai_gateway": answering,
        "neutrino_hub_socks_1080_tcp": answering,
        "neutrino_hub_socks_1080_udp": answering,
        "neutrino_hub_netbird_udp": answering,
        "neutrino_hub_easytier_tcp": (),
        "neutrino_hub_easytier_udp": (),
    }


def test_macos_blocks_the_ports_where_they_do_not_answer(
    on_darwin, recorder, monkeypatch
):
    monkeypatch.setattr(ops, "read_config", lambda name: {})

    ops.converge_firewall(EXPOSURE, routing={})

    _, (verb, anchor) = recorder.handed
    assert verb == "load_anchor"
    assert anchor.splitlines() == [
        "block drop in quick on { Wi-Fi et_2_zqdp } proto tcp from any to any port 8080",
        "block drop in quick on { Wi-Fi et_2_zqdp } proto tcp from any to any port 443",
        "block drop in quick on { Wi-Fi et_2_zqdp } proto tcp from any to any port 8443",
        "block drop in quick on { Wi-Fi et_2_zqdp } proto tcp from any to any port 8317",
        "block drop in quick on { Wi-Fi et_2_zqdp } proto udp from any to any port 51820",
        "block drop in quick on ! lo0 proto tcp from any to any port 11010",
        "block drop in quick on ! lo0 proto udp from any to any port 11010",
    ]


def test_the_kept_anchor_is_loaded_again_on_macos_only(elsewhere, recorder):
    ops.reload_firewall()

    if elsewhere == "darwin":
        assert recorder.handed == [("reload_anchor",)]
    else:
        assert recorder.handed == []


def test_macos_allows_the_programs_of_the_enabled_overlays(
    on_darwin, recorder, monkeypatch
):
    monkeypatch.setattr(ops, "read_config", lambda name: {})

    ops.converge_firewall(NETWORK, routing=ROUTING)

    (verb, programs), _ = recorder.handed
    assert programs[1:] == [
        ops.XRAY_BINARY,
        str(ops.CLIPROXYAPI_BINARY_PATH),
        str(ops.NETBIRD_BINARY_PATH),
    ]


def test_a_reset_takes_everything_away(elsewhere, recorder):
    notes = ops.hand_back_firewall()

    verb, *handed = recorder.handed[0]
    assert verb == "remove"
    if elsewhere == "darwin":
        assert notes == ["removed", "flushed"]
        assert recorder.handed[1] == ("flush_anchor",)
        assert handed[0][1:] == [
            ops.XRAY_BINARY,
            str(ops.CLIPROXYAPI_BINARY_PATH),
            str(ops.NETBIRD_BINARY_PATH),
            str(ops.EASYTIER_CORE_PATH),
        ]
    else:
        assert notes == ["removed"]
        assert handed == []
