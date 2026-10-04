"""The network's resolvers: the uplinks' leases and rows by priority, the
system's own where the hub does not address the machine, the fallbacks when
none names any, and the record a render leaves for the lookups between two
renders."""

import pytest

from neutrino_hub.modules.router import routes
from neutrino_hub.modules.router.network_resolvers import (
    compose_network_resolvers,
    parse_recorded_resolvers,
    resolver_refusal,
)

from tests.conftest import StubLinkStatus, link, network_config, wan_entry

FALLBACKS = [
    {"address": "223.5.5.5", "port": 53},
    {"address": "119.29.29.29", "port": 53},
]


def static_entry(name: str, *rows, **rest) -> dict:
    return wan_entry(
        name,
        method="static",
        address="198.51.100.203",
        prefix_len=25,
        gateway="198.51.100.129",
        dns=list(rows),
        **rest,
    )


def compose(network, *, order, leases=None, system=()) -> list:
    return compose_network_resolvers(
        network=network,
        uplink_order=list(order),
        lease_dns=dict(leases or {}),
        system_resolvers=list(system),
    )


# --- composing ----------------------------------------------------------------


def test_a_dhcp_uplink_gives_the_resolvers_its_lease_names():
    network = network_config(wan_entry("enp2s0"))

    assert compose(
        network, order=["enp2s0"], leases={"enp2s0": ["192.168.1.1", "192.0.2.53"]}
    ) == [
        {"address": "192.168.1.1", "port": 53},
        {"address": "192.0.2.53", "port": 53},
    ]


def test_a_static_uplink_gives_its_own_rows_with_their_ports():
    network = network_config(
        static_entry(
            "enp2s0",
            {"address": "192.0.2.53", "port": 5353},
            {"address": "192.168.1.1", "port": 53},
        )
    )

    assert compose(network, order=["enp2s0"], leases={"enp2s0": ["10.0.0.1"]}) == [
        {"address": "192.0.2.53", "port": 5353},
        {"address": "192.168.1.1", "port": 53},
    ]


def test_several_uplinks_give_theirs_in_the_order_of_priority():
    network = network_config(
        wan_entry("enp2s0"),
        static_entry("enp3s0", {"address": "192.0.2.53", "port": 53}),
        wan_entry("wlp4s0"),
    )

    composed = compose(
        network,
        order=["wlp4s0", "enp3s0", "enp2s0"],
        leases={"enp2s0": ["192.168.1.1"], "wlp4s0": ["10.8.0.1", "192.168.1.1"]},
    )

    assert composed == [
        {"address": "10.8.0.1", "port": 53},
        {"address": "192.168.1.1", "port": 53},
        {"address": "192.0.2.53", "port": 53},
    ]


@pytest.mark.parametrize(
    "network",
    [
        network_config(wan_entry("enp2s0")),
        network_config(static_entry("enp2s0")),
        network_config(),
    ],
    ids=["a lease naming none", "a static uplink listing none", "no uplink"],
)
def test_with_no_resolver_named_the_built_in_fallbacks_answer(network):
    assert compose(network, order=["enp2s0"], leases={"enp2s0": []}) == FALLBACKS


def test_where_the_hub_does_not_address_the_machine_the_systems_own_are_used():
    network = network_config(wan_entry("enp2s0"), mode="side_gateway")

    assert compose(
        network,
        order=["enp2s0"],
        leases={"enp2s0": ["10.0.0.1"]},
        system=["192.168.1.1"],
    ) == [{"address": "192.168.1.1", "port": 53}]
    assert compose(network_config(mode="server"), order=[], system=[]) == FALLBACKS


# --- reading them off the machine ---------------------------------------------


class FakeDhcpClient:
    leases = {"enp2s0": ["192.168.1.1"], "enp3s0": ["10.8.0.1"]}
    asked: list = []

    def __init__(self, *, interface: str):
        self._interface = interface

    def lease_dns(self) -> list:
        FakeDhcpClient.asked.append(self._interface)
        return list(self.leases.get(self._interface, []))


def test_the_leases_are_read_off_the_uplinks_that_carry(monkeypatch):
    """An uplink holding no address holds no lease worth reading: dhcpcd
    would answer from a lease file it kept from before."""
    monkeypatch.setattr(routes, "RouterDhcpClient", FakeDhcpClient)
    FakeDhcpClient.asked = []
    network = network_config(
        wan_entry("enp2s0", intent="primary"),
        wan_entry("enp3s0"),
        static_entry("enp4s0", {"address": "192.0.2.53", "port": 53}),
    )
    status = StubLinkStatus(
        links=[
            link("enp2s0", address="192.168.1.20/24"),
            link("enp3s0", address=None),
            link("enp4s0", address="198.51.100.203/25"),
        ],
        gateways={"enp2s0": "192.168.1.1", "enp4s0": "198.51.100.129"},
    )

    resolvers = routes.read_network_resolvers(network, status=status)

    assert FakeDhcpClient.asked == ["enp2s0"]
    assert resolvers == [
        {"address": "192.168.1.1", "port": 53},
        {"address": "192.0.2.53", "port": 53},
    ]


def test_outside_router_mode_the_system_is_asked(monkeypatch):
    class Platform:
        def system_resolvers(self) -> list:
            return ["192.168.1.1"]

    monkeypatch.setattr(routes, "hub_platform", Platform)
    monkeypatch.setattr(routes, "RouterDhcpClient", None)

    assert routes.read_network_resolvers(network_config(mode="server")) == [
        {"address": "192.168.1.1", "port": 53}
    ]


# --- the record ---------------------------------------------------------------


def test_the_record_comes_back_as_it_was_written(monkeypatch, tmp_path):
    record = tmp_path / "router_network_resolvers.json"
    monkeypatch.setattr(routes, "ROUTER_NETWORK_RESOLVERS_PATH", record)
    rows = [{"address": "192.168.1.1", "port": 53}, {"address": "::1", "port": 5353}]

    routes.record_network_resolvers(rows)

    assert routes.rendered_network_resolvers() == rows


def test_with_no_record_the_fallbacks_answer(monkeypatch, tmp_path):
    monkeypatch.setattr(
        routes, "ROUTER_NETWORK_RESOLVERS_PATH", tmp_path / "missing.json"
    )

    assert routes.rendered_network_resolvers() == FALLBACKS


@pytest.mark.parametrize("text", ["", "{}", "[{}]", '[{"address": "a", "port": "x"}]'])
def test_a_record_that_is_not_a_list_of_rows_reads_as_the_fallbacks(text):
    assert parse_recorded_resolvers(text) == FALLBACKS


# --- the rows a person sends --------------------------------------------------


def test_rows_of_addresses_and_ports_stand():
    rows = [
        {"address": "192.0.2.53", "port": 53},
        {"address": "2001:db8::1", "port": 1},
    ]

    assert resolver_refusal(rows, port_min=1, port_max=65535) is None


@pytest.mark.parametrize(
    ("row", "refusal"),
    [
        (
            {"address": "dns.example.net", "port": 53},
            ("resolver_address_invalid", {"address": "dns.example.net"}),
        ),
        (
            {"address": "192.0.2.53", "port": 65536},
            ("port_out_of_range", {"minimum": 1, "maximum": 65535, "value": 65536}),
        ),
    ],
)
def test_the_first_row_that_cannot_be_asked_is_named(row, refusal):
    rows = [{"address": "192.0.2.1", "port": 53}, row]

    assert resolver_refusal(rows, port_min=1, port_max=65535) == refusal
