"""Windows Firewall, with PowerShell faked.

What these pin: the hub's rules are read by their prefix, a missing rule is
created on its interfaces, a rule whose port or interfaces moved is changed,
a rule on no interface is disabled rather than removed, a rule no purpose
names is removed, all in one script, and a firewall already right is not
touched.
"""

import pytest

from neutrino_hub.modules.firewall.constants import (
    FIREWALL_WINDOWS_CHANGE_SCRIPT,
    FIREWALL_WINDOWS_READ_SCRIPT,
)
from neutrino_hub.modules.firewall.renderer import FirewallPortRule
from neutrino_hub.modules.firewall.windows_applier import FirewallWindowsApplier
from tests.conftest import FakePowerShell

ON = ("Ethernet Instance 0 2",)
RULES = [
    FirewallPortRule("neutrino_hub_panel_http", "TCP", 8080, ON),
    FirewallPortRule("neutrino_hub_agent", "TCP", 8443, ON),
    FirewallPortRule("neutrino_hub_socks_1080_tcp", "TCP", 1080, ON),
]


def held(*entries, interfaces=ON, is_enabled=True) -> dict:
    return {
        "rules": [
            {
                "name": name,
                "protocol": protocol,
                "port": port,
                "is_enabled": is_enabled,
                "interfaces": list(interfaces),
            }
            for name, protocol, port in entries
        ]
    }


def document(name, protocol, port, interfaces=ON) -> dict:
    return {
        "name": name,
        "protocol": protocol,
        "port": port,
        "interfaces": list(interfaces),
    }


def test_a_fresh_machine_has_every_rule_created():
    powershell = FakePowerShell({FIREWALL_WINDOWS_READ_SCRIPT: {"rules": []}})

    notes = FirewallWindowsApplier(powershell=powershell).apply(RULES)

    assert notes == [
        "firewall opened neutrino_hub_panel_http",
        "firewall opened neutrino_hub_agent",
        "firewall opened neutrino_hub_socks_1080_tcp",
    ]
    (read_script, read), (change_script, change) = powershell.runs
    assert read_script == FIREWALL_WINDOWS_READ_SCRIPT
    assert read == {"prefix": "neutrino_hub_"}
    assert change_script == FIREWALL_WINDOWS_CHANGE_SCRIPT
    assert change["create"] == [
        document("neutrino_hub_panel_http", "TCP", "8080"),
        document("neutrino_hub_agent", "TCP", "8443"),
        document("neutrino_hub_socks_1080_tcp", "TCP", "1080"),
    ]
    assert change["update"] == [] and change["remove"] == []
    assert change["description"]


def test_a_moved_port_is_changed_and_a_rule_no_purpose_names_is_removed():
    powershell = FakePowerShell(
        {
            FIREWALL_WINDOWS_READ_SCRIPT: held(
                ("neutrino_hub_panel_http", "TCP", "9000"),
                ("neutrino_hub_agent", "TCP", "8443"),
                ("neutrino_hub_socks_1080_tcp", "TCP", "1080"),
                ("neutrino_hub_socks_1090_tcp", "TCP", "1090"),
            )
        }
    )

    notes = FirewallWindowsApplier(powershell=powershell).apply(RULES)

    assert notes == [
        "firewall moved neutrino_hub_panel_http to 8080",
        "firewall closed neutrino_hub_socks_1090_tcp",
    ]
    change = powershell.runs[1][1]
    assert change["create"] == []
    assert change["update"] == [document("neutrino_hub_panel_http", "TCP", "8080")]
    assert change["remove"] == ["neutrino_hub_socks_1090_tcp"]


def test_a_firewall_already_right_is_read_and_left_alone():
    powershell = FakePowerShell(
        {
            FIREWALL_WINDOWS_READ_SCRIPT: held(
                ("neutrino_hub_panel_http", "tcp", "8080"),
                ("neutrino_hub_agent", "TCP", "8443"),
                ("neutrino_hub_socks_1080_tcp", "TCP", "1080"),
            )
        }
    )

    assert FirewallWindowsApplier(powershell=powershell).apply(RULES) == []
    assert len(powershell.runs) == 1


def test_one_rule_held_comes_back_bare_and_is_still_read():
    powershell = FakePowerShell(
        {
            FIREWALL_WINDOWS_READ_SCRIPT: {
                "rules": {
                    "name": "neutrino_hub_agent",
                    "protocol": "TCP",
                    "port": "8443",
                    "is_enabled": True,
                    "interfaces": "Ethernet Instance 0 2",
                }
            }
        }
    )

    FirewallWindowsApplier(powershell=powershell).apply(RULES[1:2])

    assert len(powershell.runs) == 1


def test_a_removal_takes_every_rule_of_the_hubs_away():
    powershell = FakePowerShell(
        {
            FIREWALL_WINDOWS_READ_SCRIPT: held(
                ("neutrino_hub_panel_http", "TCP", "8080"),
                ("neutrino_hub_agent", "TCP", "8443"),
            )
        }
    )

    notes = FirewallWindowsApplier(powershell=powershell).remove()

    assert notes == [
        "firewall closed neutrino_hub_agent",
        "firewall closed neutrino_hub_panel_http",
    ]
    assert powershell.runs[1][1]["remove"] == [
        "neutrino_hub_agent",
        "neutrino_hub_panel_http",
    ]


def test_a_removal_with_nothing_held_runs_nothing_more():
    powershell = FakePowerShell({FIREWALL_WINDOWS_READ_SCRIPT: {"rules": []}})

    assert FirewallWindowsApplier(powershell=powershell).remove() == []
    assert len(powershell.runs) == 1


def test_powershell_that_cannot_run_is_an_os_error():
    powershell = FakePowerShell(error=OSError("powershell exited 1"))

    with pytest.raises(OSError):
        FirewallWindowsApplier(powershell=powershell).apply(RULES)


def test_the_ai_gateway_s_port_is_opened_and_moved_like_the_rest():
    held_rules = held(("neutrino_hub_ai_gateway", "TCP", "8317"))
    powershell = FakePowerShell({FIREWALL_WINDOWS_READ_SCRIPT: held_rules})
    rule = FirewallPortRule("neutrino_hub_ai_gateway", "TCP", 9317, ON)

    notes = FirewallWindowsApplier(powershell=powershell).apply([rule])

    assert notes == ["firewall moved neutrino_hub_ai_gateway to 9317"]
    (_, _), (_, change) = powershell.runs
    assert change["update"] == [document("neutrino_hub_ai_gateway", "TCP", "9317")]


def test_a_rule_held_on_every_interface_is_scoped_to_the_exposed_ones():
    powershell = FakePowerShell(
        {
            FIREWALL_WINDOWS_READ_SCRIPT: held(
                ("neutrino_hub_panel_http", "TCP", "8080"), interfaces=["Any"]
            )
        }
    )
    rule = FirewallPortRule(
        "neutrino_hub_panel_http", "TCP", 8080, ("Ethernet Instance 0 2", "wt0")
    )

    notes = FirewallWindowsApplier(powershell=powershell).apply([rule])

    assert notes == [
        "firewall scoped neutrino_hub_panel_http to Ethernet Instance 0 2, wt0"
    ]
    assert powershell.runs[1][1]["update"] == [
        document(
            "neutrino_hub_panel_http",
            "TCP",
            "8080",
            ["Ethernet Instance 0 2", "wt0"],
        )
    ]


def test_a_rule_on_no_interface_is_disabled_and_kept():
    powershell = FakePowerShell(
        {FIREWALL_WINDOWS_READ_SCRIPT: held(("neutrino_hub_panel_http", "TCP", "8080"))}
    )
    rule = FirewallPortRule("neutrino_hub_panel_http", "TCP", 8080, ())

    notes = FirewallWindowsApplier(powershell=powershell).apply([rule])

    assert notes == ["firewall disabled neutrino_hub_panel_http"]
    change = powershell.runs[1][1]
    assert change["update"] == [document("neutrino_hub_panel_http", "TCP", "8080", [])]
    assert change["remove"] == []


def test_a_disabled_rule_still_on_no_interface_is_left_alone():
    powershell = FakePowerShell(
        {
            FIREWALL_WINDOWS_READ_SCRIPT: held(
                ("neutrino_hub_panel_http", "TCP", "8080"),
                interfaces=["Wi-Fi"],
                is_enabled=False,
            )
        }
    )
    rule = FirewallPortRule("neutrino_hub_panel_http", "TCP", 8080, ())

    assert FirewallWindowsApplier(powershell=powershell).apply([rule]) == []
    assert len(powershell.runs) == 1


def test_the_aliases_are_compared_as_a_set_whatever_their_case():
    powershell = FakePowerShell(
        {
            FIREWALL_WINDOWS_READ_SCRIPT: held(
                ("neutrino_hub_agent", "TCP", "8443"), interfaces=["WT0", "Wi-Fi"]
            )
        }
    )
    rule = FirewallPortRule("neutrino_hub_agent", "TCP", 8443, ("Wi-Fi", "wt0"))

    assert FirewallWindowsApplier(powershell=powershell).apply([rule]) == []


def test_the_change_script_scopes_or_disables_each_rule():
    assert "-InterfaceAlias $aliases" in FIREWALL_WINDOWS_CHANGE_SCRIPT
    assert "-Enabled False" in FIREWALL_WINDOWS_CHANGE_SCRIPT
    assert "Get-NetFirewallInterfaceFilter" in FIREWALL_WINDOWS_READ_SCRIPT
