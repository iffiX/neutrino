"""Reading the uplink's byte counters and working out which uplink it is.

What this guards is the tile on the dashboard: it has to be the machine's own
interface, the same one vnstat draws the history chart from, and not the proxy
core's totals it used to add up.
"""

from neutrino_hub.system import interface_traffic
from neutrino_hub.system.interface_traffic import (
    default_route_interface,
    interface_counters,
    traffic_interface,
)
from tests.conftest import lan_entry, network_config, wan_entry

PROC_NET_DEV = """\
Inter-|   Receive                                                |  Transmit
 face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed
    lo:    1024      12    0    0    0     0          0         0     1024      12    0    0    0     0       0          0
enp2s0: 90000000  120000    0    0    0     0          0         0  4500000   80000    0    0    0     0       0          0
enp1s0:  700000    9000    0    0    0     0          0         0   310000    4000    0    0    0     0       0          0
"""

PROC_NET_ROUTE = """\
Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\tMTU\tWindow\tIRTT
enp1s0\t0064A8C0\t00000000\t0001\t0\t0\t0\t00FFFFFF\t0\t0\t0
wlp3s0\t00000000\t0164A8C0\t0003\t0\t0\t600\t00000000\t0\t0\t0
enp2s0\t00000000\t0102A8C0\t0003\t0\t0\t100\t00000000\t0\t0\t0
"""


def _tables(monkeypatch, tmp_path, *, dev: str = PROC_NET_DEV, route: str = ""):
    """Point the reader at tables written for this test."""
    dev_path = tmp_path / "dev"
    dev_path.write_text(dev, encoding="utf-8")
    route_path = tmp_path / "route"
    route_path.write_text(route, encoding="utf-8")
    monkeypatch.setattr(interface_traffic, "PROC_NET_DEV", dev_path)
    monkeypatch.setattr(interface_traffic, "PROC_NET_ROUTE", route_path)


def test_an_interface_reports_what_it_has_received_and_sent(monkeypatch, tmp_path):
    _tables(monkeypatch, tmp_path)

    assert interface_counters("enp2s0") == (90000000, 4500000)


def test_a_name_the_table_does_not_carry_reads_as_nothing(monkeypatch, tmp_path):
    """None, not zeros: a missing interface is not an idle one."""
    _tables(monkeypatch, tmp_path)

    assert interface_counters("enp9s0") is None


def test_no_interface_at_all_reads_as_nothing(monkeypatch, tmp_path):
    _tables(monkeypatch, tmp_path)

    assert interface_counters("") is None


def test_a_table_the_box_does_not_have_reads_as_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(interface_traffic, "PROC_NET_DEV", tmp_path / "absent")

    assert interface_counters("enp2s0") is None


def test_the_default_route_names_its_interface(monkeypatch, tmp_path):
    """Lowest metric wins, the way the kernel picks between two of them."""
    _tables(monkeypatch, tmp_path, route=PROC_NET_ROUTE)

    assert default_route_interface() == "enp2s0"


def test_a_box_with_no_way_out_names_no_interface(monkeypatch, tmp_path):
    _tables(monkeypatch, tmp_path, route=PROC_NET_ROUTE.splitlines()[0])

    assert default_route_interface() == ""


def test_the_configured_uplink_is_the_traffic_interface(monkeypatch, tmp_path):
    """A WAN role settles it, so the tile and the history chart agree."""
    _tables(monkeypatch, tmp_path, route=PROC_NET_ROUTE)
    network = network_config(
        wan_entry("enp2s0"), lan_entry("enp1s0", address="192.168.100.1")
    )

    assert traffic_interface(network=network) == "enp2s0"


def test_a_box_with_no_wan_role_falls_back_to_the_default_route(monkeypatch, tmp_path):
    """Server and passthrough modes give no port the role and still route."""
    _tables(monkeypatch, tmp_path, route=PROC_NET_ROUTE)
    network = network_config(lan_entry("enp1s0", address="192.168.100.1"))

    assert traffic_interface(network=network) == "enp2s0"


def test_neither_an_uplink_nor_a_route_names_nothing(monkeypatch, tmp_path):
    _tables(monkeypatch, tmp_path)
    network = network_config()

    assert traffic_interface(network=network) == ""
