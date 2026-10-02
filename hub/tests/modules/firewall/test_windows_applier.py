"""Windows Firewall, with PowerShell faked.

What these pin: the hub's rules are read by their prefix, a missing rule is
created, a rule whose port moved is changed, a rule no purpose names is
removed, all in one script, and a firewall already right is not touched.
"""

import pytest

from neutrino_hub.modules.firewall.constants import (
    FIREWALL_WINDOWS_CHANGE_SCRIPT,
    FIREWALL_WINDOWS_READ_SCRIPT,
)
from neutrino_hub.modules.firewall.renderer import FirewallPortRule
from neutrino_hub.modules.firewall.windows_applier import FirewallWindowsApplier
from tests.conftest import FakePowerShell

RULES = [
    FirewallPortRule("neutrino_hub_panel_http", "TCP", 8080),
    FirewallPortRule("neutrino_hub_agent", "TCP", 8443),
    FirewallPortRule("neutrino_hub_socks_1080_tcp", "TCP", 1080),
]


def held(*entries) -> dict:
    return {
        "rules": [
            {"name": name, "protocol": protocol, "port": port}
            for name, protocol, port in entries
        ]
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
        {"name": "neutrino_hub_panel_http", "protocol": "TCP", "port": "8080"},
        {"name": "neutrino_hub_agent", "protocol": "TCP", "port": "8443"},
        {"name": "neutrino_hub_socks_1080_tcp", "protocol": "TCP", "port": "1080"},
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
    assert change["update"] == [
        {"name": "neutrino_hub_panel_http", "protocol": "TCP", "port": "8080"}
    ]
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
