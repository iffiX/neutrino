"""The relays on Windows: WSL's vEthernet adapter, and the rules in Windows Firewall.

What these pin: the relay addresses are the IPv4 addresses of the adapter
whose name starts ``vEthernet (WSL``, and no other adapter's; the firewall
holds one rule per relayed port, ``neutrino_agent_relay_<port>``, scoped to
the adapter; a missing rule is added, a rule no relay asks for is removed, a
rule whose port or adapter moved is replaced, and a rule of another name is
left alone.
"""

from neutrino_agent.platforms.base import RelayAddress, RelayRule
from neutrino_agent.platforms.windows_relay import (
    rule_changes,
    rule_name,
    wanted_rules,
    wsl_addresses_from,
)

WSL = "vEthernet (WSL (Hyper-V firewall))"
ADAPTERS = [
    {"name": "Ethernet Instance 0 2", "mac": "", "addresses": ["192.168.122.46"]},
    {"name": WSL, "mac": "", "addresses": ["fe80::1", "172.20.208.1"]},
    {"name": "vEthernet (Default Switch)", "mac": "", "addresses": ["172.29.0.1"]},
]  # fmt: skip


def rule(port, interface=WSL):
    return RelayRule(interface=interface, address="172.20.208.1", prefix=0, port=port)


def test_the_relay_addresses_are_wsl_s_adapter_s_ipv4_addresses():
    assert wsl_addresses_from(ADAPTERS) == [
        RelayAddress(interface=WSL, index=0, address="172.20.208.1", prefix=0)
    ]


def test_no_wsl_adapter_is_no_relay_address():
    assert wsl_addresses_from(ADAPTERS[:1] + ADAPTERS[2:]) == []


def test_one_rule_per_relayed_port_named_after_it():
    assert rule_name(8317) == "neutrino_agent_relay_8317"
    assert wanted_rules(frozenset({rule(8317), rule(3101)})) == {
        "neutrino_agent_relay_3101": {
            "name": "neutrino_agent_relay_3101",
            "port": "3101",
            "alias": WSL,
        },
        "neutrino_agent_relay_8317": {
            "name": "neutrino_agent_relay_8317",
            "port": "8317",
            "alias": WSL,
        },
    }


def test_a_missing_rule_is_added_and_a_stale_one_removed():
    found = [
        {"name": "neutrino_agent_relay_3101", "port": "3101", "alias": WSL},
        {"name": "neutrino_agent_relay_9000", "port": "9000", "alias": WSL},
        {"name": "neutrino_smb_fence", "port": "445", "alias": "Any"},
    ]

    add, remove = rule_changes(frozenset({rule(8317), rule(3101)}), found)

    assert add == [{"name": "neutrino_agent_relay_8317", "port": "8317", "alias": WSL}]
    assert remove == ["neutrino_agent_relay_9000"]


def test_a_rule_on_another_adapter_is_replaced():
    found = [
        {
            "name": "neutrino_agent_relay_8317",
            "port": "8317",
            "alias": "vEthernet (WSL)",
        }
    ]

    add, remove = rule_changes(frozenset({rule(8317)}), found)

    assert remove == ["neutrino_agent_relay_8317"]
    assert add == [{"name": "neutrino_agent_relay_8317", "port": "8317", "alias": WSL}]


def test_no_relay_removes_every_rule_of_the_agent_s():
    found = [{"name": "neutrino_agent_relay_8317", "port": "8317", "alias": WSL}]

    assert rule_changes(frozenset(), found) == ([], ["neutrino_agent_relay_8317"])
