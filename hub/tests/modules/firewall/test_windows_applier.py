"""Windows Firewall, with PowerShell faked.

What these pin: the hub's rules are read by their prefix with their remote
addresses and interfaces, a missing rule is created, a rule whose port,
remote addresses or interfaces moved is removed and created again, a rule no
purpose names is removed, all in one script, and a firewall already right
is not touched, an IPv4 network Windows reads back with its mask spelled
out included. An alias Windows has no adapter by yet is waited for a bounded
number of runs, then left out with a note; a rule Windows refuses leaves the
others applied and is answered by name; the next pass scopes a rule left
narrowed or disabled again.
"""

import pytest

from neutrino_hub.modules.firewall.constants import (
    FIREWALL_WINDOWS_CHANGE_SCRIPT,
    FIREWALL_WINDOWS_READ_SCRIPT,
    FIREWALL_WINDOWS_RETRY_COUNT,
    FIREWALL_WINDOWS_RETRY_WAIT_S,
)
from neutrino_hub.modules.firewall.renderer import FirewallPortRule
from neutrino_hub.modules.firewall.windows_applier import FirewallWindowsApplier
from tests.conftest import FakePowerShell

SEGMENTS = ("192.168.1.0/24", "2001:db8:1::/64")
RULES = [
    FirewallPortRule("neutrino_hub_panel_http", "TCP", 8080, SEGMENTS),
    FirewallPortRule("neutrino_hub_agent", "TCP", 8443, SEGMENTS),
    FirewallPortRule("neutrino_hub_socks_1080_tcp", "TCP", 1080, SEGMENTS),
]
# How Windows reads the same remote addresses back.
READ_BACK = ["192.168.1.0/255.255.255.0", "2001:db8:1::/64"]


def held(*entries, remote=READ_BACK, interfaces=("Any",), is_enabled=True) -> dict:
    return {
        "rules": [
            {
                "name": name,
                "protocol": protocol,
                "port": port,
                "is_enabled": is_enabled,
                "interfaces": list(interfaces),
                "remote_addresses": list(remote),
            }
            for name, protocol, port in entries
        ]
    }


def document(name, protocol, port, remote=SEGMENTS, interfaces=()) -> dict:
    return {
        "name": name,
        "protocol": protocol,
        "port": port,
        "remote_addresses": list(remote),
        "interfaces": list(interfaces),
    }


def test_a_fresh_machine_has_every_rule_created():
    powershell = FakePowerShell({FIREWALL_WINDOWS_READ_SCRIPT: {"rules": []}})

    notes, refused = FirewallWindowsApplier(powershell=powershell).apply(RULES)

    assert notes == [
        "firewall opened neutrino_hub_panel_http",
        "firewall opened neutrino_hub_agent",
        "firewall opened neutrino_hub_socks_1080_tcp",
    ]
    assert refused == []
    (read_script, read), (change_script, change) = powershell.runs
    assert read_script == FIREWALL_WINDOWS_READ_SCRIPT
    assert read == {"prefix": "neutrino_hub_"}
    assert change_script == FIREWALL_WINDOWS_CHANGE_SCRIPT
    assert change["create"] == [
        document("neutrino_hub_panel_http", "TCP", "8080"),
        document("neutrino_hub_agent", "TCP", "8443"),
        document("neutrino_hub_socks_1080_tcp", "TCP", "1080"),
    ]
    assert change["remove"] == []
    assert change["description"]


def test_a_moved_port_is_written_again_and_a_rule_no_purpose_names_is_removed():
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

    notes, refused = FirewallWindowsApplier(powershell=powershell).apply(RULES)

    assert notes == [
        "firewall moved neutrino_hub_panel_http to 8080",
        "firewall closed neutrino_hub_socks_1090_tcp",
    ]
    change = powershell.runs[1][1]
    assert change["create"] == [document("neutrino_hub_panel_http", "TCP", "8080")]
    assert change["remove"] == [
        "neutrino_hub_socks_1090_tcp",
        "neutrino_hub_panel_http",
    ]


def test_a_firewall_already_right_is_read_and_left_alone():
    """Windows spells an IPv4 network with its mask; it is the same network."""
    powershell = FakePowerShell(
        {
            FIREWALL_WINDOWS_READ_SCRIPT: held(
                ("neutrino_hub_panel_http", "tcp", "8080"),
                ("neutrino_hub_agent", "TCP", "8443"),
                ("neutrino_hub_socks_1080_tcp", "TCP", "1080"),
            )
        }
    )

    assert FirewallWindowsApplier(powershell=powershell).apply(RULES) == ([], [])
    assert len(powershell.runs) == 1


def test_a_changed_ipv6_prefix_writes_the_rule_again_with_the_new_network():
    powershell = FakePowerShell(
        {
            FIREWALL_WINDOWS_READ_SCRIPT: held(
                ("neutrino_hub_agent", "TCP", "8443"),
                remote=["192.168.1.0/255.255.255.0", "2001:db8:9::/64"],
            )
        }
    )

    notes, refused = FirewallWindowsApplier(powershell=powershell).apply(RULES[1:2])

    assert notes == [
        "firewall opened neutrino_hub_agent to 192.168.1.0/24, 2001:db8:1::/64"
    ]
    change = powershell.runs[1][1]
    assert change["remove"] == ["neutrino_hub_agent"]
    assert change["create"] == [document("neutrino_hub_agent", "TCP", "8443")]


def test_a_rule_held_open_to_any_address_is_narrowed_to_the_segments():
    powershell = FakePowerShell(
        {
            FIREWALL_WINDOWS_READ_SCRIPT: held(
                ("neutrino_hub_panel_http", "TCP", "8080"), remote=["Any"]
            )
        }
    )

    notes, _ = FirewallWindowsApplier(powershell=powershell).apply(RULES[:1])

    assert notes == [
        "firewall opened neutrino_hub_panel_http to 192.168.1.0/24, 2001:db8:1::/64"
    ]


def test_one_rule_held_comes_back_bare_and_is_still_read():
    powershell = FakePowerShell(
        {
            FIREWALL_WINDOWS_READ_SCRIPT: {
                "rules": {
                    "name": "neutrino_hub_agent",
                    "protocol": "TCP",
                    "port": "8443",
                    "is_enabled": True,
                    "interfaces": "Any",
                    "remote_addresses": READ_BACK,
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


def test_the_aliases_are_compared_as_a_set_whatever_their_case():
    powershell = FakePowerShell(
        {
            FIREWALL_WINDOWS_READ_SCRIPT: held(
                ("neutrino_hub_agent_direct", "TCP", "8443"),
                remote=["Any"],
                interfaces=["WT0", "Wi-Fi"],
            )
        }
    )
    rule = FirewallPortRule(
        "neutrino_hub_agent_direct", "TCP", 8443, (), ("Wi-Fi", "wt0")
    )

    assert FirewallWindowsApplier(powershell=powershell).apply([rule]) == ([], [])


def test_the_scripts_name_the_remote_addresses_and_the_interfaces():
    assert "Get-NetFirewallAddressFilter" in FIREWALL_WINDOWS_READ_SCRIPT
    assert "Get-NetFirewallInterfaceFilter" in FIREWALL_WINDOWS_READ_SCRIPT
    assert "RemoteAddress = $remote" in FIREWALL_WINDOWS_CHANGE_SCRIPT
    assert "$options.InterfaceAlias = $aliases" in FIREWALL_WINDOWS_CHANGE_SCRIPT
    assert "$options.Enabled = 'False'" in FIREWALL_WINDOWS_CHANGE_SCRIPT


def test_the_change_script_keeps_only_the_aliases_windows_knows():
    assert "Get-NetAdapter -IncludeHidden" in FIREWALL_WINDOWS_CHANGE_SCRIPT
    assert "$known -contains $_" in FIREWALL_WINDOWS_CHANGE_SCRIPT
    assert "catch" in FIREWALL_WINDOWS_CHANGE_SCRIPT
    assert "dropped = @($dropped); failed = @($failed)" in (
        FIREWALL_WINDOWS_CHANGE_SCRIPT
    )


# --- Adapters that come up late, and rules Windows refuses -----------------

ETHERNET = "Ethernet Instance 0 2"
EASYTIER = "et_2_tncd"
REFUSAL = "The parameter is incorrect."


class FakeWindows:
    """Windows Firewall behind PowerShell, as the two scripts see it.

    Attributes:
        rules: The hub's rules Windows holds, by name, as the read answers.
        changes: Every document the change script ran with.
    """

    def __init__(self, *, known, held=(), refusing=()):
        """
        Args:
            known: The adapter names Windows has at each change run; the
                last list holds for every run after it.
            held: The rules Windows holds at first, as the read answers.
            refusing: The names of the rules every change refuses.
        """
        self.rules = {entry["name"]: dict(entry) for entry in held}
        self.changes: list = []
        self._known = [list(names) for names in known]
        self._refusing = set(refusing)

    def __call__(self, script, document):
        if script == FIREWALL_WINDOWS_READ_SCRIPT:
            return {"rules": [dict(rule) for rule in self.rules.values()]}
        known = {
            name.lower()
            for name in self._known[min(len(self.changes), len(self._known) - 1)]
        }
        self.changes.append(document)
        dropped, failed = [], []
        for name in document["remove"]:
            self.rules.pop(name, None)
        for rule in document["create"]:
            aliases = [name for name in rule["interfaces"] if name.lower() in known]
            unknown = [name for name in rule["interfaces"] if name not in aliases]
            if unknown:
                dropped.append({"name": rule["name"], "interfaces": unknown})
            if rule["name"] in self._refusing:
                failed.append({"name": rule["name"], "error": REFUSAL})
                continue
            self.rules[rule["name"]] = {
                "name": rule["name"],
                "protocol": rule["protocol"],
                "port": rule["port"],
                "is_enabled": bool(aliases) or not rule["interfaces"],
                "interfaces": aliases or ["Any"],
                "remote_addresses": rule["remote_addresses"] or ["Any"],
            }
        return {"changed": True, "dropped": dropped, "failed": failed}


def link_rule(*interfaces) -> FirewallPortRule:
    return FirewallPortRule(
        "neutrino_hub_agent_link", "TCP", 8443, ("fe80::/64",), interfaces
    )


def link_held(*interfaces, is_enabled=True) -> dict:
    return {
        "name": "neutrino_hub_agent_link",
        "protocol": "TCP",
        "port": "8443",
        "is_enabled": is_enabled,
        "interfaces": list(interfaces),
        "remote_addresses": ["fe80::/64"],
    }


def test_an_adapter_up_by_the_third_run_gets_the_rule_fully_scoped():
    windows = FakeWindows(
        known=[[ETHERNET], [ETHERNET], [ETHERNET, EASYTIER]],
        held=[link_held(ETHERNET, "et_1_tncd")],
    )
    waits = []
    applier = FirewallWindowsApplier(powershell=windows, sleep=waits.append)

    notes, refused = applier.apply([link_rule(ETHERNET, EASYTIER)])

    assert notes == [
        f"firewall scoped neutrino_hub_agent_link to {ETHERNET}, {EASYTIER}"
    ]
    assert refused == []
    assert waits == [FIREWALL_WINDOWS_RETRY_WAIT_S] * 2
    assert len(windows.changes) == 3
    assert windows.rules["neutrino_hub_agent_link"]["interfaces"] == [
        ETHERNET,
        EASYTIER,
    ]


def test_an_adapter_never_up_is_left_out_after_the_last_run_with_a_note():
    windows = FakeWindows(known=[[ETHERNET]], held=[link_held("et_1_tncd")])
    waits = []
    applier = FirewallWindowsApplier(powershell=windows, sleep=waits.append)

    notes, refused = applier.apply([link_rule(EASYTIER)])

    assert notes == [
        "firewall disabled neutrino_hub_agent_link",
        f"firewall left {EASYTIER} out of neutrino_hub_agent_link:"
        " Windows has no adapter by that name",
    ]
    assert refused == []
    assert len(windows.changes) == FIREWALL_WINDOWS_RETRY_COUNT
    assert waits == [FIREWALL_WINDOWS_RETRY_WAIT_S] * (FIREWALL_WINDOWS_RETRY_COUNT - 1)
    assert windows.rules["neutrino_hub_agent_link"]["is_enabled"] is False


def test_a_refused_rule_leaves_the_others_applied_and_is_answered_by_name():
    windows = FakeWindows(known=[[ETHERNET]], refusing=["neutrino_hub_panel_http"])
    waits = []
    applier = FirewallWindowsApplier(powershell=windows, sleep=waits.append)

    notes, refused = applier.apply(RULES)

    assert notes == [
        "firewall opened neutrino_hub_agent",
        "firewall opened neutrino_hub_socks_1080_tcp",
    ]
    assert refused == [
        {
            "rule": "neutrino_hub_panel_http",
            "detail": f"neutrino_hub_panel_http: {REFUSAL}",
        }
    ]
    assert sorted(windows.rules) == [
        "neutrino_hub_agent",
        "neutrino_hub_socks_1080_tcp",
    ]
    assert len(windows.changes) == FIREWALL_WINDOWS_RETRY_COUNT
    assert [rule["name"] for rule in windows.changes[1]["create"]] == [
        "neutrino_hub_panel_http"
    ]


def test_the_next_pass_scopes_a_rule_left_narrowed_or_disabled_again():
    direct = FirewallPortRule("neutrino_hub_agent_direct", "TCP", 8443, (), (EASYTIER,))
    link = link_rule(ETHERNET, EASYTIER)
    windows = FakeWindows(known=[[ETHERNET]])
    FirewallWindowsApplier(powershell=windows, sleep=lambda seconds: None).apply(
        [link, direct]
    )
    assert windows.rules["neutrino_hub_agent_link"]["interfaces"] == [ETHERNET]
    assert windows.rules["neutrino_hub_agent_direct"]["is_enabled"] is False

    windows._known = [[ETHERNET, EASYTIER]]
    windows.changes = []
    notes, refused = FirewallWindowsApplier(
        powershell=windows, sleep=lambda seconds: None
    ).apply([link, direct])

    assert notes == [
        f"firewall scoped neutrino_hub_agent_link to {ETHERNET}, {EASYTIER}",
        f"firewall scoped neutrino_hub_agent_direct to {EASYTIER}",
    ]
    assert refused == []
    assert len(windows.changes) == 1
    assert windows.rules["neutrino_hub_agent_direct"]["interfaces"] == [EASYTIER]
