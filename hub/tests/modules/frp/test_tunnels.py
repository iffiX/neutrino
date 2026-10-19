"""Which tunnels each vendor lists, and each row's node and region."""

from neutrino_hub.modules.frp.tunnels import openfrp_tunnels, sakurafrp_tunnels
from tests.modules.frp.fake_vendors import (
    OPENFRP_NODES,
    OPENFRP_PROXIES,
    SAKURAFRP_NODES,
    SAKURAFRP_TUNNELS,
)


def test_sakurafrp_lists_tcp_tunnels_to_the_connection_port_off_guarded_nodes():
    """UDP and HTTP are left out, another local port is left out, and a node
    forcing access authentication is left out."""
    rows = sakurafrp_tunnels(SAKURAFRP_TUNNELS, SAKURAFRP_NODES, agent_port=8443)

    assert [row.name for row in rows] == ["neutrino", "hk"]


def test_a_sakurafrp_row_names_its_node_its_region_and_its_public_address():
    neutrino, hong_kong = sakurafrp_tunnels(
        SAKURAFRP_TUNNELS, SAKURAFRP_NODES, agent_port=8443
    )

    assert (neutrino.tunnel_id, neutrino.node_name, neutrino.region) == (
        "114514",
        "宁波电信",
        "mainland",
    )
    assert (neutrino.public_host, neutrino.public_port) == ("frp-a.natfrp.cloud", 41234)
    assert (neutrino.dial_host, neutrino.dial_port) == ("frp-a.natfrp.cloud", 0)
    assert hong_kong.region == "outside_mainland"


def test_sakurafrp_follows_the_connection_port():
    rows = sakurafrp_tunnels(SAKURAFRP_TUNNELS, SAKURAFRP_NODES, agent_port=22)

    assert [row.name for row in rows] == ["ssh"]


def test_a_sakurafrp_tunnel_on_an_unknown_node_is_left_out():
    rows = sakurafrp_tunnels(SAKURAFRP_TUNNELS, {}, agent_port=8443)

    assert rows == []


def test_openfrp_lists_tcp_tunnels_to_the_connection_port_with_auto_tls_off():
    """``autoTls`` is ``"true"`` or a certificate's name when on."""
    rows = openfrp_tunnels(OPENFRP_PROXIES, OPENFRP_NODES, agent_port=8443)

    assert [row.name for row in rows] == ["neutrino", "tokyo"]


def test_an_openfrp_row_names_its_node_its_region_and_its_public_address():
    neutrino, tokyo = openfrp_tunnels(OPENFRP_PROXIES, OPENFRP_NODES, agent_port=8443)

    assert (neutrino.tunnel_id, neutrino.node_id, neutrino.node_name) == (
        "120623",
        "41",
        "重庆联通-2",
    )
    assert neutrino.region == "mainland"
    assert (neutrino.public_host, neutrino.public_port) == (
        "cn-cq-plc-1.of-7af93c01.shop",
        51607,
    )
    assert (neutrino.dial_host, neutrino.dial_port) == (
        "cn-cq-plc-1.of-7af93c01.shop",
        8120,
    )
    assert tokyo.region == "abroad"


def test_openfrps_hong_kong_macao_and_taiwan_region():
    proxy = dict(OPENFRP_PROXIES[0], nid=2)

    (row,) = openfrp_tunnels([proxy], OPENFRP_NODES, agent_port=8443)

    assert row.region == "hk_mo_tw"
    assert row.dial_port == 0
