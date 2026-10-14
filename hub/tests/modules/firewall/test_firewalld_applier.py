"""firewalld, with firewall-cmd faked.

What these pin: the zones and rich rules are read from ``--list-all-zones``
as firewall-cmd prints them; the hub's rules are found by their priority and
the person's are never touched; a change goes to the runtime and to the
permanent configuration; a runtime already holding the rules reads nothing
more and changes nothing; the removal takes the hub's rules out of both,
and with firewalld stopped out of the permanent configuration through
``firewall-offline-cmd``.
"""

from neutrino_hub.modules.firewall.firewalld_applier import (
    FirewallFirewalldApplier,
    parse_zones,
    rule_key,
)
from neutrino_hub.modules.firewall.renderer import firewalld_rule

from tests.conftest import FakeFirewalld

OWN = 'rule family="ipv4" source address="10.9.0.0/16" service name="ssh" accept'
PANEL = firewalld_rule(
    family="ipv4", source="192.168.1.0/24", port=8080, protocol="TCP"
)
AGENT = firewalld_rule(
    family="ipv4", source="192.168.1.0/24", port=8443, protocol="TCP"
)
PEER = firewalld_rule(port=51820, protocol="UDP")


def firewalld(**zones) -> FakeFirewalld:
    return FakeFirewalld(
        zones={
            "public": {"interfaces": ["eth0"], "runtime": [OWN], "permanent": [OWN]},
            "trusted": {"interfaces": ["wt0"]},
            **zones,
        }
    )


def test_the_zones_and_their_rules_are_read_as_firewall_cmd_prints_them():
    listing = (
        "public (active)\n"
        "  target: default\n"
        "  interfaces: eth0 eth1\n"
        "  rich rules: \n"
        f"\t{OWN}\n"
        f"\t{PANEL}\n"
        "\n"
        "trusted\n"
        "  target: ACCEPT\n"
        "  interfaces: \n"
        "  rich rules: \n"
    )

    assert parse_zones(listing) == {
        "public": {"interfaces": ["eth0", "eth1"], "rules": [OWN, PANEL]},
        "trusted": {"interfaces": [], "rules": []},
    }


def test_a_rule_is_the_hubs_by_its_priority_alone():
    assert rule_key(PANEL) == ("ipv4", "192.168.1.0/24", "8080", "tcp", "accept")
    assert rule_key(OWN) is None
    assert rule_key(PANEL.replace("32123", "0")) is None


def test_a_survey_reads_each_devices_zone_the_default_and_the_hubs_rules():
    fake = firewalld(public={"interfaces": ["eth0"], "runtime": [OWN, PANEL]})

    devices, default, held = FirewallFirewalldApplier(run=fake).survey()

    assert devices == {"eth0": "public", "wt0": "trusted"}
    assert default == "public"
    assert held == {"public": [PANEL]}


def test_the_rules_go_to_the_runtime_and_the_permanent_configuration():
    fake = firewalld()
    applier = FirewallFirewalldApplier(run=fake)

    notes = applier.apply(
        {"public": [PANEL, AGENT], "trusted": [PEER]}, held=applier.held()
    )

    assert notes == [
        "firewalld zone public: 2 rules added, 0 removed",
        "firewalld zone trusted: 1 rules added, 0 removed",
    ]
    for layer in ("runtime", "permanent"):
        assert fake.zones["public"][layer] == [OWN, PANEL, AGENT]
        assert fake.zones["trusted"][layer] == [PEER]


def test_a_runtime_already_right_reads_nothing_more_and_changes_nothing():
    fake = firewalld(
        public={"interfaces": ["eth0"], "runtime": [OWN, PANEL], "permanent": [OWN]}
    )
    applier = FirewallFirewalldApplier(run=fake)
    held = applier.held()
    fake.commands.clear()

    assert applier.apply({"public": [PANEL]}, held=held) == []
    assert fake.commands == []


def test_a_rule_no_longer_wanted_is_removed_and_the_persons_kept():
    fake = firewalld(
        public={
            "interfaces": ["eth0"],
            "runtime": [OWN, PANEL, AGENT],
            "permanent": [OWN, PANEL, AGENT],
        }
    )
    applier = FirewallFirewalldApplier(run=fake)

    notes = applier.apply({"public": [AGENT]}, held=applier.held())

    assert notes == ["firewalld zone public: 0 rules added, 1 removed"]
    for layer in ("runtime", "permanent"):
        assert fake.zones["public"][layer] == [OWN, AGENT]


def test_the_removal_takes_the_hubs_rules_out_of_both_layers():
    fake = firewalld(
        public={
            "interfaces": ["eth0"],
            "runtime": [OWN, PANEL],
            "permanent": [OWN, PANEL, PEER],
        }
    )

    notes = FirewallFirewalldApplier(run=fake).remove()

    assert notes == ["firewalld zone public: 0 rules added, 1 removed"]
    for layer in ("runtime", "permanent"):
        assert fake.zones["public"][layer] == [OWN]


def test_with_firewalld_stopped_the_removal_edits_the_permanent_configuration():
    fake = firewalld(
        public={"interfaces": ["eth0"], "permanent": [OWN, PANEL]},
    )
    fake.is_running = False

    notes = FirewallFirewalldApplier(run=fake).remove()

    assert notes == ["firewalld zone public: 0 rules added, 1 removed"]
    assert fake.zones["public"]["permanent"] == [OWN]
    assert all(command[0] != "firewall-cmd" for command in fake.commands[1:])


def test_firewalld_not_installed_is_not_running():
    def missing(command, **_keywords):
        from neutrino_hub.utils.subprocess_run import CommandResult

        return CommandResult(command, 127, "", "firewall-cmd is not installed")

    assert not FirewallFirewalldApplier(run=missing).is_running()
