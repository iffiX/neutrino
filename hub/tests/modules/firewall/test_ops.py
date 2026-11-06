"""Which firewall a routing pass drives, and what it reads to drive it.

What these pin: the panel's ports come from its settings, the overlays from
the network and the segments from the addresses the box holds now, an
interface the configuration does not name among them; Windows gets one rule
per purpose naming the exposed segments as remote addresses, macOS the
programs of the enabled overlays and the pf anchor, takes xray off an earlier
build's list, and loads the kept anchor again at start; a pass records the
networks it wrote the rules for, and a network that moved, not an address
that rotated inside one, runs the pass again; on Linux firewalld gets the
rules in the zones of the exposed interfaces while it runs, the pass
records what it wrote, and a runtime that lost them runs the pass again; a
reset takes everything away on every system. Before setup the wizard's port
opens to every sender in firewalld and on Windows, and nothing opens on
macOS; the first pass after setup and a reset take it out.
"""

import json

import pytest

from neutrino_hub.modules.firewall import ops
from neutrino_hub.modules.firewall.firewalld_applier import FirewallFirewalldApplier
from neutrino_hub.modules.firewall.renderer import FirewallPortRule, firewalld_rule
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig

from tests.conftest import FakeFirewalld

NETWORK = RouterNetworkConfig.from_dict(
    {
        "mode": "server",
        "interfaces": [],
        "overlays": [{"provider": "netbird", "is_enabled": True}],
    }
)
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
    "Ethernet Instance 0 2": ["10.0.0.7/24", "2001:db8:7::7/64", "fe80::7/64"],
    "Wi-Fi": ["192.168.1.20/24"],
    "Ethernet 3": ["172.16.0.2/24"],
    "wt0": ["100.88.38.71/16"],
    "et_2_zqdp": ["10.144.144.1/24"],
}
SEGMENTS = (
    "10.0.0.0/24",
    "172.16.0.0/24",
    "100.88.0.0/16",
    "2001:db8:7::/64",
)


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
    monkeypatch.setattr(ops, "device_held_addresses", lambda: dict(PRESENT))
    return Recorder


@pytest.mark.feature("proxy")
def test_windows_opens_the_ports_the_settings_name(on_windows, recorder, monkeypatch):
    stored = {"web/settings.json": {"listen_port": 9080, "https_listen_port": 9443}}
    monkeypatch.setattr(ops, "read_config", lambda name: stored[name])

    assert ops.converge_firewall(NETWORK) == (["changed"], [])

    ((verb, rules),) = recorder.handed
    assert [(rule.name, rule.port) for rule in rules] == [
        ("neutrino_hub_panel_http", 9080),
        ("neutrino_hub_panel_http_link", 9080),
        ("neutrino_hub_panel_https", 9443),
        ("neutrino_hub_panel_https_link", 9443),
        ("neutrino_hub_agent", 8443),
        ("neutrino_hub_agent_link", 8443),
        ("neutrino_hub_netbird_udp", 51820),
    ]


def test_windows_before_setup_opens_the_default_ports(
    on_windows, recorder, monkeypatch
):
    def missing(name):
        raise FileNotFoundError(name)

    monkeypatch.setattr(ops, "read_config", missing)

    ops.converge_firewall(NETWORK)

    ((_, rules),) = recorder.handed
    assert [rule.port for rule in rules[:6:2]] == [8080, 443, 8443]


@pytest.mark.feature("proxy")
def test_windows_answers_the_exposed_segments_and_overlays_by_remote_address(
    on_windows, recorder, monkeypatch
):
    monkeypatch.setattr(ops, "read_config", lambda name: {})

    ops.converge_firewall(EXPOSURE)

    ((_, rules),) = recorder.handed
    by_name = {rule.name: rule for rule in rules}
    assert by_name["neutrino_hub_agent"].remote_addresses == SEGMENTS
    assert by_name["neutrino_hub_agent"].interfaces == ()
    assert by_name["neutrino_hub_agent_link"].interfaces == ("Ethernet Instance 0 2",)
    assert by_name["neutrino_hub_netbird_udp"].remote_addresses == ()
    assert by_name["neutrino_hub_easytier_tcp"].remote_addresses == ()
    assert not any("192.168.1" in str(rule) for rule in rules)
    assert not any("10.144" in str(rule) for rule in rules)


def test_macos_passes_the_hub_ports_from_the_segments_and_blocks_the_rest(
    on_darwin, recorder, monkeypatch
):
    monkeypatch.setattr(ops, "read_config", lambda name: {})

    ops.converge_firewall(EXPOSURE)

    _, _, (verb, anchor) = recorder.handed
    assert verb == "load_anchor"
    lines = anchor.splitlines()
    assert lines[0] == (
        "table <neutrino_hub_ipv4> const { 10.0.0.0/24, 172.16.0.0/24, 100.88.0.0/16 }"
    )
    assert lines[1] == "table <neutrino_hub_ipv6> const { 2001:db8:7::/64 }"
    assert lines[-1] == (
        "block drop in quick proto tcp from any to any port { 8080, 443, 8443 }"
    )


def test_the_kept_anchor_is_loaded_again_on_macos_only(elsewhere, recorder):
    ops.reload_firewall()

    if elsewhere == "darwin":
        assert recorder.handed == [("reload_anchor",)]
    else:
        assert recorder.handed == []


@pytest.mark.feature("proxy")
def test_macos_allows_the_programs_of_the_enabled_overlays(
    on_darwin, recorder, monkeypatch
):
    from neutrino_hub.modules.netbird.constants import NETBIRD_BINARY_PATH
    from neutrino_hub.modules.xray.constants import XRAY_BINARY

    monkeypatch.setattr(ops, "read_config", lambda name: {})

    ops.converge_firewall(NETWORK)

    (verb, programs), (gone, former), _ = recorder.handed
    assert verb == "apply"
    assert programs[1:] == [str(NETBIRD_BINARY_PATH)]
    assert gone == "remove"
    assert former == [XRAY_BINARY]


def test_a_pass_records_the_networks_it_wrote_the_rules_for(
    elsewhere, recorder, monkeypatch
):
    """After the TUN was rebuilt the rules kept a dead adapter and lost
    EasyTier's for forty minutes: the pass that follows the overlay devices
    asks this, and a moved set runs the firewall again."""
    monkeypatch.setattr(ops, "read_config", lambda name: {})
    assert ops.is_network_set_moved() is True

    ops.converge_firewall(EXPOSURE)

    assert ops.is_network_set_moved() is False
    renamed = {**PRESENT, "et_3_abcd": PRESENT["et_2_zqdp"]}
    del renamed["et_2_zqdp"]
    monkeypatch.setattr(ops, "device_held_addresses", lambda: dict(renamed))
    assert ops.is_network_set_moved() is True


def test_a_new_ipv6_prefix_moves_the_set_and_a_rotated_address_does_not(
    elsewhere, recorder, monkeypatch
):
    monkeypatch.setattr(ops, "read_config", lambda name: {})
    ops.converge_firewall(EXPOSURE)
    ethernet = "Ethernet Instance 0 2"

    rotated = {**PRESENT, ethernet: [*PRESENT[ethernet], "2001:db8:7::9a3/64"]}
    monkeypatch.setattr(ops, "device_held_addresses", lambda: dict(rotated))
    assert ops.is_network_set_moved() is False

    moved = {**PRESENT, ethernet: ["10.0.0.7/24", "2001:db8:8::7/64"]}
    monkeypatch.setattr(ops, "device_held_addresses", lambda: dict(moved))
    assert ops.is_network_set_moved() is True


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
            str(NETBIRD_BINARY_PATH),
            str(ops.EASYTIER_CORE_PATH),
            XRAY_BINARY,
        ]
    else:
        assert notes == ["removed"]
        assert handed == []


def test_a_reset_drops_the_networks_record_so_a_reinstall_writes_the_rules(
    elsewhere, recorder, monkeypatch
):
    """A Windows hub removed and installed again over its kept state found
    the record unchanged and wrote no rule: the panel answered no other
    machine."""
    monkeypatch.setattr(ops, "read_config", lambda name: {})
    ops.converge_firewall(EXPOSURE)
    assert ops.is_network_set_moved() is False

    ops.hand_back_firewall()

    assert ops.is_network_set_moved() is True


# --- Direct ---


@pytest.mark.feature("proxy")
def test_direct_opens_the_agent_port_alone_on_windows_enabled_interfaces(
    on_windows, recorder, monkeypatch
):
    monkeypatch.setattr(ops, "read_config", lambda name: {})
    monkeypatch.setattr(ops, "direct_agent_port", lambda: 8443)

    ops.converge_firewall(EXPOSURE)

    ((_, rules),) = recorder.handed
    by_name = {rule.name: rule for rule in rules}
    direct = by_name["neutrino_hub_agent_direct"]
    assert direct.remote_addresses == ()
    assert direct.interfaces == ("Ethernet Instance 0 2", "Wi-Fi", "Ethernet 3")
    assert by_name["neutrino_hub_panel_https"].remote_addresses == SEGMENTS


def test_direct_passes_the_agent_port_from_any_address_on_macos(
    on_darwin, recorder, monkeypatch
):
    monkeypatch.setattr(ops, "read_config", lambda name: {})
    monkeypatch.setattr(ops, "direct_agent_port", lambda: 8443)

    ops.converge_firewall(EXPOSURE)

    _, _, (_, anchor) = recorder.handed
    assert (
        "pass in quick on { Ethernet Instance 0 2 Wi-Fi Ethernet 3 } "
        "proto tcp from any to any port 8443"
    ) in anchor.splitlines()


# --- firewalld on Linux ---


def linux_exposure():
    network = RouterNetworkConfig.from_dict(
        {
            "mode": "server",
            "interfaces": [
                {"name": "eth0", "is_exposed": True},
                {"name": "eth1", "is_exposed": False},
            ],
            "overlays": [],
        }
    )
    return ops.firewall_exposure(
        network,
        held={"eth0": ["192.168.1.20/24"], "eth1": ["10.1.0.2/24"]},
    )


@pytest.fixture
def firewalld(monkeypatch):
    fake = FakeFirewalld(
        zones={
            "public": {"interfaces": ["eth0", "eth1"]},
            "trusted": {"interfaces": ["wt0"]},
        }
    )
    monkeypatch.setattr(ops, "read_config", lambda name: {})
    monkeypatch.setattr(
        ops, "FirewallFirewalldApplier", lambda: FirewallFirewalldApplier(run=fake)
    )
    return fake


def test_firewalld_running_gets_the_hub_ports_from_the_exposed_segment(firewalld):
    notes = ops.converge_firewalld(linux_exposure())

    rules = firewalld.zones["public"]["runtime"]
    assert notes == ["firewalld zone public: 3 rules added, 0 removed"]
    assert rules == [
        firewalld_rule(
            family="ipv4", source="192.168.1.0/24", port=port, protocol="TCP"
        )
        for port in (443, 8080, 8443)
    ]
    assert firewalld.zones["public"]["permanent"] == rules
    assert json.loads(ops.FIREWALL_FIREWALLD_RECORD_PATH.read_text()) == {
        "public": rules
    }


def test_firewalld_stopped_is_left_alone_and_recorded_as_stopped(firewalld):
    firewalld.is_running = False

    assert ops.converge_firewalld(linux_exposure()) == []
    assert json.loads(ops.FIREWALL_FIREWALLD_RECORD_PATH.read_text()) is None
    assert firewalld.zones["public"]["permanent"] == []


def test_the_half_minute_check_runs_the_pass_again_when_firewalld_lost_the_rules(
    firewalld,
):
    """firewalld started at a later boot, or reloaded, holds none of the
    hub's runtime rules."""
    firewalld.is_running = False
    ops.converge_firewalld(linux_exposure())
    assert ops.is_firewalld_moved() is False

    firewalld.is_running = True
    assert ops.is_firewalld_moved() is True

    ops.converge_firewalld(linux_exposure())
    assert ops.is_firewalld_moved() is False

    firewalld.zones["public"]["runtime"] = []
    assert ops.is_firewalld_moved() is True


def test_a_reset_on_linux_takes_the_hubs_rules_out_of_firewalld(firewalld):
    ops.converge_firewalld(linux_exposure())

    notes = ops.hand_back_firewall()

    assert notes == ["firewalld zone public: 0 rules added, 3 removed"]
    assert firewalld.zones["public"]["runtime"] == []
    assert firewalld.zones["public"]["permanent"] == []
    assert not ops.FIREWALL_FIREWALLD_RECORD_PATH.exists()


def test_the_next_pass_takes_an_earlier_builds_listener_out_of_firewalld(firewalld):
    former = firewalld_rule(
        family="ipv4", source="192.168.1.0/24", port=1080, protocol="TCP"
    )
    firewalld.zones["public"]["runtime"] = [former]
    firewalld.zones["public"]["permanent"] = [former]

    ops.converge_firewalld(linux_exposure())

    assert former not in firewalld.zones["public"]["runtime"]
    assert former not in firewalld.zones["public"]["permanent"]
    assert firewalld.zones["public"]["runtime"]


# --- the setup wizard's port ---


def test_before_setup_firewalld_opens_the_wizards_port_in_every_zone(firewalld):
    notes = ops.open_setup_port(8080)

    rule = firewalld_rule(port=8080, protocol="TCP")
    assert notes == [
        "firewalld zone public: 1 rules added, 0 removed",
        "firewalld zone trusted: 1 rules added, 0 removed",
    ]
    for zone in ("public", "trusted"):
        assert firewalld.zones[zone]["runtime"] == [rule]
        assert firewalld.zones[zone]["permanent"] == [rule]


def test_a_wizard_on_another_port_moves_its_rule(firewalld):
    ops.open_setup_port(8080)

    ops.open_setup_port(39211)

    rule = firewalld_rule(port=39211, protocol="TCP")
    assert firewalld.zones["public"]["runtime"] == [rule]
    assert firewalld.zones["public"]["permanent"] == [rule]


def test_the_first_pass_after_setup_takes_the_wizards_port_out(firewalld):
    ops.open_setup_port(8080)

    ops.converge_firewalld(linux_exposure())

    assert firewalld.zones["trusted"]["runtime"] == []
    assert firewalld.zones["trusted"]["permanent"] == []
    assert firewalld.zones["public"]["runtime"] == [
        firewalld_rule(
            family="ipv4", source="192.168.1.0/24", port=port, protocol="TCP"
        )
        for port in (443, 8080, 8443)
    ]


def test_a_reset_before_setup_takes_the_wizards_port_out(firewalld):
    ops.open_setup_port(8080)

    ops.hand_back_firewall()

    for zone in ("public", "trusted"):
        assert firewalld.zones[zone]["runtime"] == []
        assert firewalld.zones[zone]["permanent"] == []


def test_firewalld_stopped_opens_nothing_for_the_wizard(firewalld):
    firewalld.is_running = False

    assert ops.open_setup_port(8080) == []
    assert firewalld.zones["public"]["permanent"] == []


def test_windows_opens_the_wizards_port_to_every_sender(on_windows, recorder):
    assert ops.open_setup_port(8080) == ["changed"]

    assert recorder.handed == [
        (
            "apply",
            [FirewallPortRule(name="neutrino_hub_setup", protocol="TCP", port=8080)],
        )
    ]


def test_macos_opens_nothing_for_the_wizard(on_darwin, recorder):
    assert ops.open_setup_port(8080) == []
    assert recorder.handed == []
