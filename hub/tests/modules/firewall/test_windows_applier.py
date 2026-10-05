"""Windows Firewall, with PowerShell faked.

What these pin: the hub's rules are read by their prefix, a missing rule is
created on its interfaces, a rule whose port or interfaces moved is changed,
a rule on no interface is disabled rather than removed, a rule no purpose
names is removed, all in one script, and a firewall already right is not
touched. An alias Windows has no adapter by yet is waited for a bounded
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

    notes, refused = FirewallWindowsApplier(powershell=powershell).apply(RULES)

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

    notes, refused = FirewallWindowsApplier(powershell=powershell).apply(RULES)

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

    assert FirewallWindowsApplier(powershell=powershell).apply(RULES) == ([], [])
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

    notes, refused = FirewallWindowsApplier(powershell=powershell).apply([rule])

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

    notes, refused = FirewallWindowsApplier(powershell=powershell).apply([rule])

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

    notes, refused = FirewallWindowsApplier(powershell=powershell).apply([rule])

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

    assert FirewallWindowsApplier(powershell=powershell).apply([rule]) == ([], [])
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

    assert FirewallWindowsApplier(powershell=powershell).apply([rule]) == ([], [])


def test_the_change_script_scopes_or_disables_each_rule():
    assert "-InterfaceAlias $aliases" in FIREWALL_WINDOWS_CHANGE_SCRIPT
    assert "-Enabled False" in FIREWALL_WINDOWS_CHANGE_SCRIPT
    assert "Get-NetFirewallInterfaceFilter" in FIREWALL_WINDOWS_READ_SCRIPT


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
        for rule in document["update"] + document["create"]:
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
                "is_enabled": bool(aliases),
                "interfaces": aliases or ["Any"],
            }
        return {"changed": True, "dropped": dropped, "failed": failed}


def easytier_rule(*interfaces) -> FirewallPortRule:
    return FirewallPortRule("neutrino_hub_easytier_tcp", "TCP", 11010, interfaces)


def easytier_held(*interfaces, is_enabled=True) -> dict:
    return {
        "name": "neutrino_hub_easytier_tcp",
        "protocol": "TCP",
        "port": "11010",
        "is_enabled": is_enabled,
        "interfaces": list(interfaces),
    }


def test_an_adapter_up_by_the_third_run_gets_the_rule_fully_scoped():
    windows = FakeWindows(
        known=[[ETHERNET], [ETHERNET], [ETHERNET, EASYTIER]],
        held=[easytier_held(ETHERNET, "et_1_tncd")],
    )
    waits = []
    applier = FirewallWindowsApplier(powershell=windows, sleep=waits.append)

    notes, refused = applier.apply([easytier_rule(ETHERNET, EASYTIER)])

    assert notes == [
        f"firewall scoped neutrino_hub_easytier_tcp to {ETHERNET}, {EASYTIER}"
    ]
    assert refused == []
    assert waits == [FIREWALL_WINDOWS_RETRY_WAIT_S] * 2
    assert len(windows.changes) == 3
    assert windows.rules["neutrino_hub_easytier_tcp"]["interfaces"] == [
        ETHERNET,
        EASYTIER,
    ]


def test_an_adapter_never_up_is_left_out_after_the_last_run_with_a_note():
    windows = FakeWindows(known=[[ETHERNET]], held=[easytier_held("et_1_tncd")])
    waits = []
    applier = FirewallWindowsApplier(powershell=windows, sleep=waits.append)

    notes, refused = applier.apply([easytier_rule(EASYTIER)])

    assert notes == [
        "firewall disabled neutrino_hub_easytier_tcp",
        f"firewall left {EASYTIER} out of neutrino_hub_easytier_tcp:"
        " Windows has no adapter by that name",
    ]
    assert refused == []
    assert len(windows.changes) == FIREWALL_WINDOWS_RETRY_COUNT
    assert waits == [FIREWALL_WINDOWS_RETRY_WAIT_S] * (FIREWALL_WINDOWS_RETRY_COUNT - 1)
    assert windows.rules["neutrino_hub_easytier_tcp"]["is_enabled"] is False


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
            "detail": f"neutrino_hub_panel_http on {ETHERNET}: {REFUSAL}",
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
    udp = FirewallPortRule("neutrino_hub_easytier_udp", "UDP", 11010, (EASYTIER,))
    tcp = easytier_rule(ETHERNET, EASYTIER)
    windows = FakeWindows(known=[[ETHERNET]])
    FirewallWindowsApplier(powershell=windows, sleep=lambda seconds: None).apply(
        [tcp, udp]
    )
    assert windows.rules["neutrino_hub_easytier_tcp"]["interfaces"] == [ETHERNET]
    assert windows.rules["neutrino_hub_easytier_udp"]["is_enabled"] is False

    windows._known = [[ETHERNET, EASYTIER]]
    windows.changes = []
    notes, refused = FirewallWindowsApplier(
        powershell=windows, sleep=lambda seconds: None
    ).apply([tcp, udp])

    assert notes == [
        f"firewall scoped neutrino_hub_easytier_tcp to {ETHERNET}, {EASYTIER}",
        f"firewall scoped neutrino_hub_easytier_udp to {EASYTIER}",
    ]
    assert refused == []
    assert len(windows.changes) == 1
    assert windows.rules["neutrino_hub_easytier_udp"]["interfaces"] == [EASYTIER]


def test_the_agent_rule_names_no_address_so_it_covers_ipv4_and_ipv6():
    """A rule with no local or remote address matches both families: the
    agent port answers on IPv6 wherever it answers on IPv4."""
    powershell = FakePowerShell({FIREWALL_WINDOWS_READ_SCRIPT: {"rules": []}})

    FirewallWindowsApplier(powershell=powershell).apply(RULES)

    _, (change_script, change) = powershell.runs
    assert "Address" not in change_script
    assert change["create"][1] == document("neutrino_hub_agent", "TCP", "8443")
