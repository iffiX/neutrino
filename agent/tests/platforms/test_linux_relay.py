"""The relays on Linux: the Podman bridges, and their rules in ufw and firewalld.

What these pin: a bridge is ``podmanN`` or ``cni-podmanN`` and each IPv4
address on one is a relay address with its index and prefix; ``ip`` runs
only while the kernel lists a bridge; the agent's ufw rules are read from
``ufw show added`` by their comment and its firewalld rules from
``--list-all-zones`` by their text, ``/32`` or not; each firewall is asked
only while it runs, ufw by ``ufw status`` and firewalld by
``firewall-cmd --state``; a missing rule is added and a rule of the agent's
no relay asks for is removed, with the exact commands the lab checks; a
firewalld rule goes in the bridge's zone, the default zone while the bridge
is in none, at runtime and permanently; a command that fails stops the
sync; and every command runs in the C locale.
"""

import json
import subprocess

import pytest

from neutrino_agent.platforms.base import RelayAddress, RelayRule
from neutrino_agent.platforms.linux_relay import (
    LinuxRelayFirewall,
    bridges_from,
    command_environment,
    firewalld_rich_rule,
    firewalld_rule_of,
    firewalld_rules_from,
    is_bridge_name,
    read_bridges,
    subnet_of,
    ufw_rule_words,
    ufw_rules_from,
)

# What ``ip -j -4 addr`` printed on a machine with netavark's default and
# one module network, a CNI bridge, Docker, the user-mode network of a
# Podman machine and the uplink.
IP_ADDR = [
    {"ifindex": 1, "ifname": "lo", "addr_info": [{"family": "inet", "local": "127.0.0.1", "prefixlen": 8}]},
    {"ifindex": 2, "ifname": "enp1s0", "addr_info": [{"family": "inet", "local": "192.168.122.41", "prefixlen": 24}]},
    {"ifindex": 3, "ifname": "podman0", "addr_info": [{"family": "inet", "local": "10.88.0.1", "prefixlen": 16}]},
    {
        "ifindex": 6,
        "ifname": "podman1",
        "addr_info": [
            {"family": "inet", "local": "10.89.0.1", "prefixlen": 24},
            {"family": "inet6", "local": "fd00::1", "prefixlen": 64},
        ],
    },
    {"ifindex": 7, "ifname": "cni-podman1", "addr_info": [{"family": "inet", "local": "10.89.1.1", "prefixlen": 24}]},
    {"ifindex": 8, "ifname": "docker0", "addr_info": [{"family": "inet", "local": "172.17.0.1", "prefixlen": 16}]},
    {"ifindex": 9, "ifname": "podman-usermode", "addr_info": [{"family": "inet", "local": "192.168.127.2", "prefixlen": 24}]},
    {"ifname": "podman2", "addr_info": [{"family": "inet", "local": "10.89.2.1", "prefixlen": 24}]},
    "not an interface",
]  # fmt: skip

PODMAN1_RULE = RelayRule(interface="podman1", address="10.89.0.1", prefix=24, port=8317)
CNI_RULE = RelayRule(interface="cni-podman1", address="10.89.1.1", prefix=24, port=3101)


@pytest.mark.parametrize(
    ("name", "is_bridge"),
    [
        ("podman0", True),
        ("podman12", True),
        ("cni-podman0", True),
        ("podman", False),
        ("podman-usermode", False),
        ("cni-podman", False),
        ("xpodman1", False),
        ("docker0", False),
    ],
)
def test_a_bridge_is_podman_n_or_cni_podman_n(name, is_bridge):
    assert is_bridge_name(name) is is_bridge


def test_each_ipv4_address_on_a_bridge_is_a_relay_address():
    assert bridges_from(IP_ADDR) == [
        RelayAddress(interface="podman0", index=3, address="10.88.0.1", prefix=16),
        RelayAddress(interface="podman1", index=6, address="10.89.0.1", prefix=24),
        RelayAddress(interface="cni-podman1", index=7, address="10.89.1.1", prefix=24),
    ]


@pytest.mark.parametrize("entries", [None, {}, "text", []])
def test_output_that_is_no_list_holds_no_bridge(entries):
    assert bridges_from(entries) == []


class IpRun:
    """``ip``, recorded, answering a canned table."""

    def __init__(self, table=None, returncode=0, error=None):
        self.calls = []
        self.table = IP_ADDR if table is None else table
        self.returncode = returncode
        self.error = error

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        if self.error is not None:
            raise self.error
        return subprocess.CompletedProcess(
            argv, self.returncode, json.dumps(self.table), ""
        )


def test_ip_runs_only_while_the_kernel_lists_a_bridge():
    run = IpRun()

    found = read_bridges(names=lambda: [(1, "lo"), (2, "enp1s0")], run=run)

    assert found == []
    assert run.calls == []


def test_the_bridges_are_read_from_ip_while_one_is_listed():
    run = IpRun()

    found = read_bridges(names=lambda: [(1, "lo"), (6, "podman1")], run=run)

    assert run.calls == [["ip", "-j", "-4", "addr"]]
    assert [address.interface for address in found] == [
        "podman0",
        "podman1",
        "cni-podman1",
    ]


@pytest.mark.parametrize(
    "run",
    [
        IpRun(returncode=1),
        IpRun(error=OSError("no ip")),
        IpRun(error=subprocess.TimeoutExpired("ip", 10)),
    ],
)
def test_an_ip_that_fails_reads_no_bridge(run):
    assert read_bridges(names=lambda: [(6, "podman1")], run=run) == []


def test_a_kernel_list_that_cannot_be_read_reads_no_bridge():
    def failing():
        raise OSError("no netlink")

    assert read_bridges(names=failing, run=IpRun()) == []


def test_a_rule_s_subnet_is_its_interface_s_network():
    assert subnet_of(PODMAN1_RULE) == "10.89.0.0/24"
    assert (
        subnet_of(RelayRule(interface="x", address="10.89.0.1", prefix=0, port=1))
        == "10.89.0.1/32"
    )


# --- ufw ---

UFW_ADDED = """Added user rules (see 'ufw status' for running firewall):
ufw allow 22/tcp
ufw allow in on podman1 to 10.89.0.1 port 8317 proto tcp comment 'neutrino_agent_relay'
ufw allow in on podman0 from any to 10.88.0.1 port 3101 proto tcp comment 'neutrino_agent_relay'
ufw allow in on podman1 to 10.89.0.1 port 9000 proto tcp comment 'mine'
ufw allow in on podman1 to 10.89.0.1 port 9001 proto tcp
ufw allow in on podman1 from 10.89.0.5 to 10.89.0.1 port 9002 proto tcp comment 'neutrino_agent_relay'
ufw deny in on podman1 to 10.89.0.1 port 9003 proto tcp comment 'neutrino_agent_relay'
ufw allow in on podman1 to 10.89.0.1 port 9004 proto udp comment 'neutrino_agent_relay'
"""


def test_the_agent_s_ufw_rules_are_the_ones_with_its_comment():
    assert ufw_rules_from(UFW_ADDED) == {
        ("podman1", "10.89.0.1", 8317),
        ("podman0", "10.88.0.1", 3101),
    }


def test_the_ufw_rule_is_the_one_the_standard_names():
    assert " ".join(ufw_rule_words("podman1", "10.89.0.1", 8317)) == (
        "allow in on podman1 to 10.89.0.1 port 8317 proto tcp "
        "comment neutrino_agent_relay"
    )


# --- firewalld ---

LIST_ALL_ZONES = """block
  target: %%REJECT%%
  rich rules:

public (default, active)
  target: default
  interfaces: eth0
  services: cockpit dhcpv6-client ssh
  rich rules:
\trule family="ipv4" source address="10.89.0.0/24" destination address="10.89.0.1/32" port port="8317" protocol="tcp" accept
\trule family="ipv4" source address="10.88.0.0/16" destination address="10.88.0.1" port port="3101" protocol="tcp" accept
\trule family="ipv4" source address="192.168.1.0/24" service name="ssh" accept
trusted (active)
  target: ACCEPT
  sources: 10.89.0.0/24
  rich rules:
"""


def test_the_agent_s_firewalld_rules_are_found_by_their_text_in_every_zone():
    found = firewalld_rules_from(LIST_ALL_ZONES)

    assert found == {
        ("public", "10.89.0.0/24", "10.89.0.1", 8317): (
            'rule family="ipv4" source address="10.89.0.0/24" '
            'destination address="10.89.0.1/32" port port="8317" '
            'protocol="tcp" accept'
        ),
        ("public", "10.88.0.0/16", "10.88.0.1", 3101): (
            'rule family="ipv4" source address="10.88.0.0/16" '
            'destination address="10.88.0.1" port port="3101" '
            'protocol="tcp" accept'
        ),
    }


@pytest.mark.parametrize(
    "text",
    [
        'rule family="ipv4" source address="10.89.0.0/24" destination address="10.89.0.1/32" port port="8317" protocol="udp" accept',
        'rule family="ipv4" source address="10.89.0.0/24" destination address="10.89.0.1/32" port port="8317" protocol="tcp" drop',
        'rule family="ipv6" source address="fd00::/64" destination address="fd00::1/128" port port="8317" protocol="tcp" accept',
        'rule family="ipv4" source address="nonsense" destination address="10.89.0.1/32" port port="8317" protocol="tcp" accept',
        'rule family="ipv4" service name="ssh" accept',
    ],
)  # fmt: skip
def test_a_rich_rule_of_any_other_shape_is_not_the_agent_s(text):
    assert firewalld_rule_of(text) is None


def test_the_rich_rule_is_the_one_the_standard_names():
    assert firewalld_rich_rule(PODMAN1_RULE) == (
        'rule family="ipv4" source address="10.89.0.0/24" '
        'destination address="10.89.0.1/32" port port="8317" '
        'protocol="tcp" accept'
    )
    assert firewalld_rule_of(firewalld_rich_rule(PODMAN1_RULE)) == (
        "10.89.0.0/24",
        "10.89.0.1",
        8317,
    )


# --- the sync ---


class FirewallRun:
    """ufw and firewall-cmd as a machine answers them, every command recorded."""

    def __init__(
        self,
        *,
        ufw=None,
        firewalld=None,
        zones=None,
        default_zone="public",
        runtime="",
        permanent="",
        failing=(),
    ):
        self.calls = []
        self.ufw = ufw
        self.firewalld = firewalld
        self.zones = dict(zones or {})
        self.default_zone = default_zone
        self.runtime = runtime
        self.permanent = permanent
        self.failing = tuple(failing)

    def __call__(self, argv):
        self.calls.append(list(argv))
        joined = " ".join(argv)
        for prefix in self.failing:
            if joined.startswith(prefix):
                return subprocess.CompletedProcess(argv, 1, "", "refused")
        if argv[0] == "ufw":
            if self.ufw is None:
                raise FileNotFoundError("ufw")
            if argv[1:] == ["status"]:
                return subprocess.CompletedProcess(argv, 0, self.ufw, "")
            if argv[1:] == ["show", "added"]:
                return subprocess.CompletedProcess(argv, 0, UFW_ADDED, "")
            return subprocess.CompletedProcess(argv, 0, "Rule added\n", "")
        if self.firewalld is None:
            raise FileNotFoundError("firewall-cmd")
        if argv[1:] == ["--state"]:
            return subprocess.CompletedProcess(
                argv, 0 if self.firewalld == "running" else 252, self.firewalld, ""
            )
        if argv[1].startswith("--get-zone-of-interface="):
            interface = argv[1].split("=", 1)[1]
            if interface in self.zones:
                return subprocess.CompletedProcess(
                    argv, 0, self.zones[interface] + "\n", ""
                )
            return subprocess.CompletedProcess(argv, 2, "no zone\n", "")
        if argv[1:] == ["--get-default-zone"]:
            return subprocess.CompletedProcess(argv, 0, self.default_zone + "\n", "")
        if argv[1:] == ["--list-all-zones"]:
            return subprocess.CompletedProcess(argv, 0, self.runtime, "")
        if argv[1:] == ["--permanent", "--list-all-zones"]:
            return subprocess.CompletedProcess(argv, 0, self.permanent, "")
        return subprocess.CompletedProcess(argv, 0, "success\n", "")


def test_on_plain_nftables_nothing_is_added():
    run = FirewallRun()

    assert LinuxRelayFirewall(run=run).sync(frozenset({PODMAN1_RULE})) == []
    assert run.calls == [["ufw", "status"], ["firewall-cmd", "--state"]]


def test_an_inactive_ufw_and_a_stopped_firewalld_are_given_nothing():
    run = FirewallRun(ufw="Status: inactive\n", firewalld="not running")

    assert LinuxRelayFirewall(run=run).sync(frozenset({PODMAN1_RULE})) == []
    assert run.calls == [["ufw", "status"], ["firewall-cmd", "--state"]]


def test_an_active_ufw_gets_each_missing_rule_and_loses_each_rule_no_relay_asks_for():
    run = FirewallRun(ufw="Status: active\n\nTo Action From\n")

    lines = LinuxRelayFirewall(run=run).sync(frozenset({PODMAN1_RULE, CNI_RULE}))

    assert run.calls == [
        ["ufw", "status"],
        ["ufw", "show", "added"],
        [
            "ufw",
            "allow",
            "in",
            "on",
            "cni-podman1",
            "to",
            "10.89.1.1",
            "port",
            "3101",
            "proto",
            "tcp",
            "comment",
            "neutrino_agent_relay",
        ],
        [
            "ufw",
            "--force",
            "delete",
            "allow",
            "in",
            "on",
            "podman0",
            "to",
            "10.88.0.1",
            "port",
            "3101",
            "proto",
            "tcp",
            "comment",
            "neutrino_agent_relay",
        ],
        ["firewall-cmd", "--state"],
    ]
    assert lines == [
        "added ufw rule: allow in on cni-podman1 to 10.89.1.1 port 3101 proto tcp",
        "removed ufw rule: allow in on podman0 to 10.88.0.1 port 3101 proto tcp",
    ]


def test_no_relay_takes_every_rule_of_the_agent_s_out_of_ufw():
    run = FirewallRun(ufw="Status: active\n")

    LinuxRelayFirewall(run=run).sync(frozenset())

    deleted = [call[8:11] for call in run.calls if call[1:3] == ["--force", "delete"]]
    assert sorted(deleted) == [
        ["10.88.0.1", "port", "3101"],
        ["10.89.0.1", "port", "8317"],
    ]


def test_firewalld_gets_the_rule_in_the_default_zone_at_runtime_and_permanently():
    run = FirewallRun(firewalld="running")

    lines = LinuxRelayFirewall(run=run).sync(frozenset({PODMAN1_RULE}))

    rule = firewalld_rich_rule(PODMAN1_RULE)
    assert run.calls == [
        ["ufw", "status"],
        ["firewall-cmd", "--state"],
        ["firewall-cmd", "--get-zone-of-interface=podman1"],
        ["firewall-cmd", "--get-default-zone"],
        ["firewall-cmd", "--list-all-zones"],
        ["firewall-cmd", "--zone=public", f"--add-rich-rule={rule}"],
        ["firewall-cmd", "--permanent", "--list-all-zones"],
        ["firewall-cmd", "--permanent", "--zone=public", f"--add-rich-rule={rule}"],
    ]
    assert lines == [
        f"added firewalld rule in public (runtime): {rule}",
        f"added firewalld rule in public (permanent): {rule}",
    ]


def test_a_bridge_in_a_zone_has_its_rule_there():
    run = FirewallRun(firewalld="running", zones={"podman1": "internal"})

    LinuxRelayFirewall(run=run).sync(frozenset({PODMAN1_RULE}))

    added = [call for call in run.calls if call[-1].startswith("--add-rich-rule=")]
    assert [call[-2] for call in added] == ["--zone=internal", "--zone=internal"]
    assert ["firewall-cmd", "--get-default-zone"] not in run.calls


def test_firewalld_keeps_a_rule_it_holds_and_loses_the_agent_s_others_as_printed():
    run = FirewallRun(
        firewalld="running", runtime=LIST_ALL_ZONES, permanent=LIST_ALL_ZONES
    )

    LinuxRelayFirewall(run=run).sync(frozenset({PODMAN1_RULE}))

    changed = [
        call
        for call in run.calls
        if any(word.startswith(("--add-rich-rule=", "--remove-rich-rule=")) for word in call)
    ]  # fmt: skip
    stale = (
        'rule family="ipv4" source address="10.88.0.0/16" '
        'destination address="10.88.0.1" port port="3101" protocol="tcp" accept'
    )
    assert changed == [
        ["firewall-cmd", "--zone=public", f"--remove-rich-rule={stale}"],
        [
            "firewall-cmd",
            "--permanent",
            "--zone=public",
            f"--remove-rich-rule={stale}",
        ],
    ]


def test_both_firewalls_are_given_the_rule_where_both_run():
    run = FirewallRun(ufw="Status: active\n", firewalld="running")

    lines = LinuxRelayFirewall(run=run).sync(frozenset({CNI_RULE}))

    assert any(line.startswith("added ufw rule") for line in lines)
    assert any(line.startswith("added firewalld rule") for line in lines)


@pytest.mark.parametrize(
    "failing", ["ufw show", "ufw allow", "firewall-cmd --list-all-zones"]
)
def test_a_firewall_command_that_fails_stops_the_sync(failing):
    run = FirewallRun(ufw="Status: active\n", firewalld="running", failing=[failing])

    with pytest.raises(subprocess.CalledProcessError):
        LinuxRelayFirewall(run=run).sync(frozenset({CNI_RULE}))


def test_every_firewall_command_runs_in_the_c_locale(monkeypatch):
    monkeypatch.setenv("LANG", "de_DE.UTF-8")
    monkeypatch.setenv("LC_ALL", "de_DE.UTF-8")

    environment = command_environment()

    assert environment["LANG"] == "C"
    assert environment["LC_ALL"] == "C"
