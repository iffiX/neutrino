"""The policy table diverted packets are delivered by.

It holds the local default route and one route per served network naming
its interface: the kernel checks a diverted packet's source against this
table when `src_valid_mark` is on, and with only the local route there every
source is a martian.
"""

from neutrino_hub.modules.router import routes
from neutrino_hub.modules.router.constants import ROUTER_ROUTE_TABLE
from neutrino_hub.modules.router.routes import RouterRulesetApplier, served_networks

from tests.conftest import lan_entry, network_config, wan_entry


class Recorder:
    """Answers `ip rule show` and `ip route show` from text and records the rest."""

    def __init__(self, *, rules: str = "", table: str = ""):
        self.rules = rules
        self.table = table
        self.commands: list[list[str]] = []

    def __call__(self, command, **keywords):
        self.commands.append(list(command))
        if command[:3] == ["ip", "rule", "show"]:
            return _Ran(self.rules)
        if command[:3] == ["ip", "route", "show"]:
            return _Ran(self.table)
        return _Ran("")


class _Ran:
    def __init__(self, stdout: str):
        self.stdout = stdout
        self.stderr = ""
        self.is_success = True
        self.exit_code = 0


def test_the_served_networks_are_named_at_their_network_address():
    network = network_config(
        wan_entry("enp2s0"),
        lan_entry("enp1s0", address="192.168.110.1"),
        lan_entry("wlp3s0", address="192.168.111.1"),
    )

    assert served_networks(network) == [
        ("enp1s0", "192.168.110.0/24"),
        ("wlp3s0", "192.168.111.0/24"),
    ]


def test_each_served_network_gets_a_route_in_the_policy_table(monkeypatch):
    recorder = Recorder(
        rules=f"100:\tfrom all fwmark 0x1 lookup {ROUTER_ROUTE_TABLE}",
        table="local default dev lo scope host\n",
    )
    monkeypatch.setattr(routes, "run", recorder)

    RouterRulesetApplier().apply_policy_route(
        [("enp1s0", "192.168.110.0/24"), ("wlp3s0", "192.168.111.0/24")]
    )

    table = str(ROUTER_ROUTE_TABLE)
    assert [c for c in recorder.commands if c[:3] == ["ip", "route", "replace"]] == [
        ["ip", "route", "replace", "192.168.110.0/24", "dev", "enp1s0", "table", table],
        ["ip", "route", "replace", "192.168.111.0/24", "dev", "wlp3s0", "table", table],
    ]
    assert not any(c[:3] == ["ip", "route", "add"] for c in recorder.commands)


def test_a_network_no_longer_served_leaves_the_table(monkeypatch):
    recorder = Recorder(
        rules=f"100:\tfrom all fwmark 0x1 lookup {ROUTER_ROUTE_TABLE}",
        table=(
            "local default dev lo scope host\n"
            "192.168.110.0/24 dev enp1s0 scope link\n"
            "192.168.111.0/24 dev wlp3s0 scope link\n"
        ),
    )
    monkeypatch.setattr(routes, "run", recorder)

    RouterRulesetApplier().apply_policy_route([("enp1s0", "192.168.110.0/24")])

    table = str(ROUTER_ROUTE_TABLE)
    changes = [
        c for c in recorder.commands if c[:2] == ["ip", "route"] and c[2] != "show"
    ]
    assert changes == [
        ["ip", "route", "del", "192.168.111.0/24", "dev", "wlp3s0", "table", table]
    ]


def test_the_local_route_is_added_once(monkeypatch):
    recorder = Recorder(rules="", table="")
    monkeypatch.setattr(routes, "run", recorder)

    RouterRulesetApplier().apply_policy_route([])

    assert [
        "ip",
        "route",
        "add",
        "local",
        "default",
        "dev",
        "lo",
        "table",
        str(ROUTER_ROUTE_TABLE),
    ] in recorder.commands
