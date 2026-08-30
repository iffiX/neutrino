"""Parsing ``config/router/network.json``, including the older shapes of it.

The migrations matter more than they look. This file is the only description of
how the box is wired, it is gitignored so it is never replaced wholesale by a
pull, and a box that fails to parse it has no LAN, no firewall and no way back
in but a keyboard.
"""

from neutrino_hub.modules.router.interfaces import RouterNetworkConfig

from tests.conftest import lan_entry, network_config, wan_entry

LEGACY_FLAT_CONFIG = {
    "wan_interface": "enp2s0",
    "lan_interface": "enp1s0",
    "lan_address": "192.168.100.1",
    "lan_prefix_len": 24,
    "dhcp_range_start": "192.168.100.100",
    "dhcp_range_end": "192.168.100.200",
    "dhcp_lease_time": "12h",
    "is_wifi_fallback_enabled": True,
    "wifi_interface": "wlp3s0",
    "is_ssh_from_wan_allowed": True,
    "wan_cloned_mac": "aa:bb:cc:dd:ee:ff",
}


# --- The pre-roles shape ----------------------------------------------------


def test_flat_config_becomes_roles():
    config = RouterNetworkConfig.from_dict(LEGACY_FLAT_CONFIG)

    assert config.wan_names == ["enp2s0", "wlp3s0"]
    assert config.lan_names == ["enp1s0"]
    assert config.interface("enp2s0").wan.cloned_mac == "aa:bb:cc:dd:ee:ff"
    assert config.interface("enp1s0").lan.address == "192.168.100.1"
    assert config.interface("enp1s0").lan.dhcp_range_end == "192.168.100.200"


def test_wifi_fallback_becomes_a_backup_uplink():
    """The old flag meant "use Wi-Fi when the wire is down", which is a backup."""
    config = RouterNetworkConfig.from_dict(LEGACY_FLAT_CONFIG)

    wifi = config.interface("wlp3s0")
    assert wifi.is_wan
    assert wifi.wan.is_backup_only


def test_wifi_without_the_fallback_flag_is_left_unused():
    config = RouterNetworkConfig.from_dict(
        {**LEGACY_FLAT_CONFIG, "is_wifi_fallback_enabled": False}
    )

    assert config.interface("wlp3s0").is_disabled


def test_migration_round_trips():
    """Writing the migrated shape back and reading it again changes nothing."""
    migrated = RouterNetworkConfig.from_dict(LEGACY_FLAT_CONFIG)

    assert RouterNetworkConfig.from_dict(migrated.to_dict()).to_dict() == (
        migrated.to_dict()
    )


# --- The pre-planner shape --------------------------------------------------


def test_old_backup_mode_becomes_the_backup_only_intent():
    """``backup`` said the one thing still worth saying, so it carries over."""
    config = network_config({"name": "usb0", "role": "wan", "wan": {"mode": "backup"}})

    assert config.interface("usb0").wan.is_backup_only


def test_old_balance_mode_becomes_automatic():
    """``balance`` was a statement about ordering, which is now inferred."""
    config = network_config(
        {"name": "enp2s0", "role": "wan", "wan": {"mode": "balance"}}
    )

    assert config.interface("enp2s0").wan.intent == "auto"


def test_an_explicit_intent_wins_over_a_leftover_mode():
    config = network_config(
        {
            "name": "enp2s0",
            "role": "wan",
            "wan": {"mode": "backup", "intent": "primary"},
        }
    )

    assert config.interface("enp2s0").wan.is_pinned_primary


# --- Hand-edited files that are wrong ---------------------------------------


def test_an_unknown_role_reads_as_disabled():
    """The safe direction to fail: do not route through what you cannot parse."""
    config = network_config({"name": "enp2s0", "role": "gateway"})

    assert config.interface("enp2s0").is_disabled


def test_unknown_enums_fall_back_rather_than_raising():
    config = RouterNetworkConfig.from_dict(
        {
            "interfaces": [
                {
                    "name": "enp2s0",
                    "role": "wan",
                    "wan": {"intent": "fastest", "method": "pppoe"},
                }
            ],
            "uplink_policy": "round_robin",
        }
    )

    uplink = config.interface("enp2s0").wan
    assert uplink.intent == "auto"
    assert uplink.method == "dhcp"
    assert config.uplink_policy == "failover"


def test_entries_without_a_name_are_dropped():
    config = RouterNetworkConfig.from_dict(
        {"interfaces": [{"role": "wan"}, {"name": "enp1s0", "role": "lan"}]}
    )

    assert [interface.name for interface in config.interfaces] == ["enp1s0"]


# --- Accessors the rest of the layer relies on ------------------------------


def test_primary_lan_address_falls_back_to_loopback():
    """A service bound nowhere beats one bound to every interface, WAN included."""
    config = network_config(wan_entry("enp2s0"))

    assert config.primary_lan_address == "127.0.0.1"


def test_primary_lan_is_the_first_served_network():
    config = network_config(
        lan_entry("enp1s0", address="192.168.100.1"),
        lan_entry("wlp3s0", address="192.168.101.1"),
    )

    assert config.primary_lan_address == "192.168.100.1"
    assert config.lan_names == ["enp1s0", "wlp3s0"]


def test_replace_overwrites_by_name_and_appends_otherwise():
    config = network_config(lan_entry("enp1s0", address="192.168.100.1"))

    updated = RouterNetworkConfig.from_dict(
        {"interfaces": [lan_entry("enp1s0", address="192.168.5.1")]}
    ).interfaces[0]
    config.replace(updated)
    config.replace(
        RouterNetworkConfig.from_dict({"interfaces": [wan_entry("enp2s0")]}).interfaces[
            0
        ]
    )

    assert len(config.interfaces) == 2
    assert config.interface("enp1s0").lan.address == "192.168.5.1"
    assert config.interface("enp2s0").is_wan


def test_all_three_settings_blocks_survive_a_role_change():
    """Switching a port between roles must not lose what was typed for the other."""
    config = network_config(
        {
            "name": "wlp3s0",
            "role": "wan",
            "lan": {"address": "192.168.101.1", "prefix_len": 24},
            "wifi": {"ap_ssid": "neutrino", "ap_passphrase": "hunter2hunter2"},
        }
    )

    interface = config.interface("wlp3s0")
    assert interface.is_wan
    assert interface.lan.address == "192.168.101.1"
    assert interface.wifi.ap_ssid == "neutrino"
    assert (
        RouterNetworkConfig.from_dict(config.to_dict())
        .interface("wlp3s0")
        .wifi.ap_passphrase
        == "hunter2hunter2"
    )


def test_pinning_one_uplink_primary_demotes_the_other():
    """Two uplinks cannot both be first, and the newer choice wins.

    Pinning a different uplink is a change of mind rather than a mistake, so
    the older pin quietly goes back to being placed automatically instead of
    the save being refused.
    """
    config = network_config(
        wan_entry("enp2s0", intent="primary"),
        wan_entry("enp3s0", intent="primary"),
        wan_entry("usb0", intent="backup_only"),
    )

    demoted = config.keep_single_primary("enp3s0")

    assert demoted == ["enp2s0"]
    assert config.interface("enp2s0").wan.intent == "auto"
    assert config.interface("enp3s0").wan.is_pinned_primary
    assert config.interface("usb0").wan.is_backup_only


# --- VLANs and the split role -----------------------------------------------


def test_a_vlan_interface_round_trips():
    config = network_config(
        {"name": "enp1s0", "role": "split"},
        {
            **lan_entry("enp1s0.10", address="192.168.110.1"),
            "vlan": {"parent": "enp1s0", "id": 10},
        },
    )

    reread = RouterNetworkConfig.from_dict(config.to_dict())
    child = reread.interface("enp1s0.10")
    assert reread.interface("enp1s0").is_split
    assert child.is_vlan
    assert child.vlan.parent == "enp1s0"
    assert child.vlan.id == 10
    assert child.is_lan
    assert reread.lan_names == ["enp1s0.10"]


def test_a_physical_interface_carries_no_vlan_block():
    config = network_config(lan_entry("enp1s0", address="192.168.100.1"))

    assert not config.interface("enp1s0").is_vlan
    assert config.to_dict()["interfaces"][0]["vlan"] is None


def test_vlan_children_belong_to_their_own_trunk():
    config = network_config(
        {"name": "enp1s0", "role": "split"},
        {"name": "enp3s0", "role": "split"},
        {
            **lan_entry("enp1s0.10", address="192.168.110.1"),
            "vlan": {"parent": "enp1s0", "id": 10},
        },
        {
            **wan_entry("enp1s0.20"),
            "vlan": {"parent": "enp1s0", "id": 20},
        },
        {
            **lan_entry("enp3s0.10", address="192.168.120.1"),
            "vlan": {"parent": "enp3s0", "id": 10},
        },
    )

    names = [child.name for child in config.vlan_children("enp1s0")]
    assert names == ["enp1s0.10", "enp1s0.20"]


def test_remove_drops_exactly_the_named_interface():
    config = network_config(
        {"name": "enp1s0", "role": "split"},
        {
            **lan_entry("enp1s0.10", address="192.168.110.1"),
            "vlan": {"parent": "enp1s0", "id": 10},
        },
    )

    assert config.remove("enp1s0.10")
    assert not config.remove("enp1s0.10")
    assert config.interface("enp1s0.10") is None
    assert config.interface("enp1s0") is not None


def test_inter_lan_traffic_is_allowed_unless_switched_off():
    assert network_config().is_inter_lan_allowed
    fenced = RouterNetworkConfig.from_dict(
        {"interfaces": [], "is_inter_lan_allowed": False}
    )
    assert not fenced.is_inter_lan_allowed
    assert not RouterNetworkConfig.from_dict(fenced.to_dict()).is_inter_lan_allowed


def test_the_untagged_main_configures_the_trunk_port():
    config = network_config(
        {"name": "enp2s0", "role": "split"},
        {
            **wan_entry("enp2s0.main"),
            "vlan": {"parent": "enp2s0", "id": None},
        },
        {
            **lan_entry("enp2s0.20", address="192.168.104.1"),
            "vlan": {"parent": "enp2s0", "id": 20},
        },
    )

    main = config.untagged_child("enp2s0")
    assert main is not None and main.is_untagged
    assert main.device_name == "enp2s0"
    assert config.interface("enp2s0.20").device_name == "enp2s0.20"
    assert config.wan_device_names == ["enp2s0"]
    assert config.lan_device_names == ["enp2s0.20"]
    reread = RouterNetworkConfig.from_dict(config.to_dict())
    assert reread.untagged_child("enp2s0").vlan.id is None


def test_a_side_gateway_lan_round_trips():
    config = network_config(
        {
            **lan_entry("enp1s0", address="192.168.1.2", is_dhcp_enabled=False),
        }
    )
    config.interface("enp1s0").lan.upstream_gateway = "192.168.1.1"

    reread = RouterNetworkConfig.from_dict(config.to_dict())
    lan = reread.interface("enp1s0").lan
    assert lan.is_side_gateway
    assert lan.upstream_gateway == "192.168.1.1"
    assert [entry.name for entry in reread.side_gateway_lans] == ["enp1s0"]
    assert not network_config(
        lan_entry("enp1s0", address="192.168.100.1")
    ).side_gateway_lans
