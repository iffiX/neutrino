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


@pytest.mark.feature("proxy")
@pytest.mark.feature("netbird")
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


@pytest.mark.feature("proxy")
@pytest.mark.feature("netbird")
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


@pytest.mark.feature("proxy")
@pytest.mark.feature("netbird")
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


@pytest.mark.feature("netbird")
@pytest.mark.feature("proxy")
def test_macos_allows_the_programs_of_the_enabled_overlays(
    on_darwin, recorder, monkeypatch
):
    from neutrino_hub.modules.netbird.constants import NETBIRD_BINARY_PATH
    from neutrino_hub.modules.xray.constants import XRAY_BINARY

    monkeypatch.setattr(ops, "read_config", lambda name: {})

    ops.converge_firewall(NETWORK, routing=ROUTING)

    (verb, programs), _ = recorder.handed
    assert programs[1:] == [
        XRAY_BINARY,
        str(ops.CLIPROXYAPI_BINARY_PATH),
        str(NETBIRD_BINARY_PATH),
    ]


def test_a_pass_records_the_interfaces_it_scoped_the_rules_to(
    elsewhere, recorder, monkeypatch
):
    """After the TUN was rebuilt the rules kept a dead adapter and lost
    EasyTier's for forty minutes: the pass that follows the overlay devices
    asks this, and a moved set runs the firewall again."""
    monkeypatch.setattr(ops, "read_config", lambda name: {})
    assert ops.is_interface_set_moved() is True

    ops.converge_firewall(EXPOSURE, routing=ROUTING)

    assert ops.is_interface_set_moved() is False
    renamed = {**PRESENT, "et_3_abcd": PRESENT["et_2_zqdp"]}
    del renamed["et_2_zqdp"]
    monkeypatch.setattr(ops, "device_addresses", lambda: dict(renamed))
    assert ops.is_interface_set_moved() is True


@pytest.mark.feature("netbird")
@pytest.mark.feature("proxy")
def test_a_reset_takes_everything_away(elsewhere, recorder):
    from neutrino_hub.modules.netbird.constants import NETBIRD_BINARY_PATH
    from neutrino_hub.modules.xray.constants import XRAY_BINARY

    notes = ops.hand_back_firewall()

    verb, *handed = recorder.handed[0]
    assert verb == "remove"
    if elsewhere == "darwin":
        assert notes == ["removed", "flushed"]
        assert recorder.handed[1] == ("flush_anchor",)
        assert handed[0][1:] == [
            XRAY_BINARY,
            str(ops.CLIPROXYAPI_BINARY_PATH),
            str(NETBIRD_BINARY_PATH),
            str(ops.EASYTIER_CORE_PATH),
        ]
    else:
        assert notes == ["removed"]
        assert handed == []


# --- Direct ---


@pytest.mark.feature("proxy")
@pytest.mark.feature("netbird")
def test_direct_opens_the_agent_port_alone_on_windows_enabled_interfaces(
    on_windows, recorder, monkeypatch
):
    monkeypatch.setattr(ops, "read_config", lambda name: {})
    monkeypatch.setattr(ops, "direct_agent_port", lambda: 8443)

    ops.converge_firewall(EXPOSURE, routing=ROUTING)

    ((_, rules),) = recorder.handed
    by_name = {rule.name: rule.interfaces for rule in rules}
    assert by_name["neutrino_hub_agent"] == (
        "Ethernet Instance 0 2",
        "Ethernet 3",
        "wt0",
        "Wi-Fi",
    )
    assert by_name["neutrino_hub_panel_https"] == (
        "Ethernet Instance 0 2",
        "Ethernet 3",
        "wt0",
    )


@pytest.mark.feature("netbird")
def test_direct_lifts_the_agent_ports_block_on_macos_interfaces_alone(
    on_darwin, recorder, monkeypatch
):
    monkeypatch.setattr(ops, "read_config", lambda name: {})
    monkeypatch.setattr(ops, "direct_agent_port", lambda: 8443)

    ops.converge_firewall(EXPOSURE, routing={})

    _, (_, anchor) = recorder.handed
    lines = anchor.splitlines()
    assert (
        "block drop in quick on { et_2_zqdp } proto tcp from any to any port 8443"
        in lines
    )
    assert (
        "block drop in quick on { Wi-Fi et_2_zqdp } proto tcp from any to any port 443"
        in lines
    )


def test_the_enabled_devices_leave_out_overlays_and_disabled_interfaces():
    network = RouterNetworkConfig.from_dict(
        {
            "mode": "router",
            "interfaces": [
                {"name": "enp1s0", "role": "lan"},
                {"name": "enp2s0", "role": "disabled"},
            ],
            "overlays": [{"provider": "netbird", "is_enabled": True}],
        }
    ).with_overlay_devices({"netbird": ["wt0"]})

    assert ops.enabled_devices(network, ["enp1s0", "enp2s0", "wt0", "enp9s0"]) == [
        "enp1s0"
    ]
