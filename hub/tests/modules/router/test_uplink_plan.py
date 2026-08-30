"""The uplink planner: which way out the gateway chooses, and why.

This is the module with the most ways to be quietly wrong. Every case here is
one it has to get right for the box to have internet, so they are named after
the situation rather than the function under test.
"""

import pytest

from neutrino_hub.modules.router.uplink_plan import plan_uplinks

from tests.conftest import network_config, wan_entry, wired_facts, wireless_facts

UPSTREAM_GATEWAY = "198.51.100.129"


def active_names(plan) -> list[str]:
    return [uplink.name for uplink in plan.active]


# --- One upstream reached twice ---------------------------------------------


@pytest.mark.parametrize("policy", ["failover", "balance"])
def test_two_ports_onto_one_upstream_are_one_line(policy):
    """Two interfaces sharing a next hop are one connection, not two.

    This is the situation that used to take the box off the network: both
    interfaces held an address on one segment, answered each other's ARP, and a
    reactivation had the gateway report a conflict against itself. Recognising
    them as one line means only one is ever brought up to carry traffic, and
    nobody has to notice the problem to avoid it.

    Balancing cannot override it. Splitting flows across two doors onto one
    broadband gains nothing, so the policy is not even consulted here.
    """
    plan = plan_uplinks(
        network=network_config(wan_entry("enp2s0"), wan_entry("wlp3s0"), policy=policy),
        facts={
            "enp2s0": wired_facts(
                "enp2s0", gateway=UPSTREAM_GATEWAY, cidr="198.51.100.203/25"
            ),
            "wlp3s0": wireless_facts(
                "wlp3s0", gateway=UPSTREAM_GATEWAY, cidr="198.51.100.197/25"
            ),
        },
    )

    assert len(plan.lines) == 1
    assert plan.lines[0].is_shared
    assert active_names(plan) == ["enp2s0"]
    assert not plan.is_balancing
    assert "shares an upstream line with enp2s0" in plan.uplink("wlp3s0").reason


def test_addresses_on_one_segment_group_before_any_route_exists():
    """A shared segment is enough; the uplinks need not have routes yet.

    Right after a reload neither interface has a default route, and grouping on
    the next hop alone would briefly see two independent lines and bring both
    up — recreating the conflict for exactly as long as it takes DHCP to
    answer.
    """
    plan = plan_uplinks(
        network=network_config(wan_entry("enp2s0"), wan_entry("enp3s0")),
        facts={
            "enp2s0": wired_facts("enp2s0", cidr="192.168.1.10/24"),
            "enp3s0": wired_facts("enp3s0", cidr="192.168.1.11/24"),
        },
    )

    assert len(plan.lines) == 1
    assert active_names(plan) == ["enp2s0"]


# --- Genuinely separate lines -----------------------------------------------


def test_failover_uses_only_the_best_line():
    plan = plan_uplinks(
        network=network_config(wan_entry("enp2s0"), wan_entry("enp3s0")),
        facts={
            "enp2s0": wired_facts(
                "enp2s0", gateway="192.168.1.1", cidr="192.168.1.10/24", speed=1000
            ),
            "enp3s0": wired_facts(
                "enp3s0", gateway="10.0.0.1", cidr="10.0.0.10/24", speed=2500
            ),
        },
    )

    assert len(plan.lines) == 2
    assert active_names(plan) == ["enp3s0"]


def test_balance_carries_on_every_separate_line():
    plan = plan_uplinks(
        network=network_config(
            wan_entry("enp2s0"), wan_entry("enp3s0"), policy="balance"
        ),
        facts={
            "enp2s0": wired_facts(
                "enp2s0", gateway="192.168.1.1", cidr="192.168.1.10/24"
            ),
            "enp3s0": wired_facts("enp3s0", gateway="10.0.0.1", cidr="10.0.0.10/24"),
        },
    )

    assert sorted(active_names(plan)) == ["enp2s0", "enp3s0"]
    assert plan.is_balancing


# --- What the ranking is built from -----------------------------------------


def test_wired_outranks_a_faster_negotiating_radio():
    """Speed only separates links of the same medium.

    Negotiated speed describes the cable, not the line behind it, and a radio
    claiming 1.2 Gb/s of PHY rate is not therefore a better uplink than a
    100 Mb/s wire. Letting speed outrank medium would pick the radio here.
    """
    plan = plan_uplinks(
        network=network_config(wan_entry("wlp3s0"), wan_entry("enp2s0")),
        facts={
            "wlp3s0": wireless_facts(
                "wlp3s0", gateway="10.0.0.1", cidr="10.0.0.9/24", speed=1200
            ),
            "enp2s0": wired_facts(
                "enp2s0", gateway="192.168.1.1", cidr="192.168.1.10/24", speed=100
            ),
        },
    )

    assert active_names(plan) == ["enp2s0"]


def test_speed_breaks_the_tie_within_one_medium():
    plan = plan_uplinks(
        network=network_config(wan_entry("enp2s0"), wan_entry("enp3s0")),
        facts={
            "enp2s0": wired_facts(
                "enp2s0", gateway="192.168.1.1", cidr="192.168.1.10/24", speed=1000
            ),
            "enp3s0": wired_facts(
                "enp3s0", gateway="10.0.0.1", cidr="10.0.0.10/24", speed=10000
            ),
        },
    )

    assert active_names(plan) == ["enp3s0"]
    assert "10 Gb/s" in plan.uplink("enp3s0").reason


def test_an_uplink_with_no_carrier_is_never_chosen():
    plan = plan_uplinks(
        network=network_config(wan_entry("enp2s0")),
        facts={"enp2s0": wired_facts("enp2s0", is_carrying=False)},
    )

    assert active_names(plan) == []
    assert plan.uplink("enp2s0").reason == "no carrier"


# --- Intent: the part that cannot be inferred -------------------------------


def test_backup_only_stays_dark_even_when_it_is_the_faster_link():
    """Cost is not measurable, so it has to be stated.

    A metered mobile link can negotiate faster than the broadband beside it and
    must still never carry traffic by choice. No ranking built from what the
    box can see would work this out.
    """
    plan = plan_uplinks(
        network=network_config(
            wan_entry("enp2s0"),
            wan_entry("usb0", intent="backup_only"),
            policy="balance",
        ),
        facts={
            "enp2s0": wired_facts(
                "enp2s0", gateway="192.168.1.1", cidr="192.168.1.10/24", speed=100
            ),
            "usb0": wired_facts(
                "usb0", gateway="10.64.0.1", cidr="10.64.0.5/24", speed=1000
            ),
        },
    )

    assert active_names(plan) == ["enp2s0"]
    assert plan.uplink("usb0").reason == "held back as backup only"


def test_backup_only_takes_over_when_nothing_else_carries():
    plan = plan_uplinks(
        network=network_config(
            wan_entry("enp2s0"), wan_entry("usb0", intent="backup_only")
        ),
        facts={
            "enp2s0": wired_facts("enp2s0", is_carrying=False),
            "usb0": wired_facts("usb0", gateway="10.64.0.1", cidr="10.64.0.5/24"),
        },
    )

    assert active_names(plan) == ["usb0"]


def test_backups_are_never_balanced_against_each_other():
    """Falling back onto two metered links at once would spend twice the data."""
    plan = plan_uplinks(
        network=network_config(
            wan_entry("usb0", intent="backup_only"),
            wan_entry("usb1", intent="backup_only"),
            policy="balance",
        ),
        facts={
            "usb0": wired_facts("usb0", gateway="10.64.0.1", cidr="10.64.0.5/24"),
            "usb1": wired_facts("usb1", gateway="10.65.0.1", cidr="10.65.0.5/24"),
        },
    )

    assert active_names(plan) == ["usb0"]


def test_pinned_primary_wins_over_a_faster_link():
    plan = plan_uplinks(
        network=network_config(
            wan_entry("enp2s0"), wan_entry("enp3s0", intent="primary")
        ),
        facts={
            "enp2s0": wired_facts(
                "enp2s0", gateway="192.168.1.1", cidr="192.168.1.10/24", speed=10000
            ),
            "enp3s0": wired_facts(
                "enp3s0", gateway="10.0.0.1", cidr="10.0.0.10/24", speed=100
            ),
        },
    )

    assert active_names(plan) == ["enp3s0"]
    assert "pinned primary" in plan.uplink("enp3s0").reason


# --- Route metrics ----------------------------------------------------------


def test_the_active_uplink_gets_the_lowest_metric():
    plan = plan_uplinks(
        network=network_config(wan_entry("enp2s0"), wan_entry("enp3s0")),
        facts={
            "enp2s0": wired_facts(
                "enp2s0", gateway="192.168.1.1", cidr="192.168.1.10/24", speed=2500
            ),
            "enp3s0": wired_facts(
                "enp3s0", gateway="10.0.0.1", cidr="10.0.0.10/24", speed=1000
            ),
        },
    )

    active = plan.uplink("enp2s0")
    standby = plan.uplink("enp3s0")
    assert active.is_active and not standby.is_active
    assert active.route_metric < standby.route_metric


def test_backup_metrics_sit_far_above_the_ordinary_ones():
    """A backup must lose to any ordinary uplink that comes back."""
    plan = plan_uplinks(
        network=network_config(
            wan_entry("enp2s0"), wan_entry("usb0", intent="backup_only")
        ),
        facts={
            "enp2s0": wired_facts(
                "enp2s0", gateway="192.168.1.1", cidr="192.168.1.10/24"
            ),
            "usb0": wired_facts("usb0", gateway="10.64.0.1", cidr="10.64.0.5/24"),
        },
    )

    assert plan.uplink("usb0").route_metric > plan.uplink("enp2s0").route_metric + 100


# --- Degenerate shapes ------------------------------------------------------


def test_a_box_with_no_uplinks_plans_nothing():
    plan = plan_uplinks(network=network_config(), facts={})

    assert plan.lines == []
    assert plan.uplinks == []
    assert not plan.is_balancing


def test_an_interface_the_snapshot_never_mentions_is_treated_as_down():
    plan = plan_uplinks(network=network_config(wan_entry("enp9s0")), facts={})

    assert active_names(plan) == []
    assert plan.uplink("enp9s0").reason == "no carrier"


def test_every_uplink_appears_exactly_once():
    """The plan is a partition: nothing is dropped and nothing is counted twice."""
    plan = plan_uplinks(
        network=network_config(
            wan_entry("enp2s0"), wan_entry("wlp3s0"), wan_entry("usb0")
        ),
        facts={
            "enp2s0": wired_facts(
                "enp2s0", gateway=UPSTREAM_GATEWAY, cidr="198.51.100.203/25"
            ),
            "wlp3s0": wireless_facts(
                "wlp3s0", gateway=UPSTREAM_GATEWAY, cidr="198.51.100.197/25"
            ),
            "usb0": wired_facts("usb0", gateway="10.64.0.1", cidr="10.64.0.5/24"),
        },
    )

    from_lines = [member.name for line in plan.lines for member in line.members]
    assert sorted(from_lines) == ["enp2s0", "usb0", "wlp3s0"]
    assert sorted(uplink.name for uplink in plan.uplinks) == sorted(from_lines)
    assert [uplink.rank for uplink in plan.uplinks] == [1, 2, 3]
