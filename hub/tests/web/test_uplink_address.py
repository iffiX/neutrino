"""The address the strip names as WAN, in the modes with and without one."""

from neutrino_hub.web import panel_runtime as runtime_module
from neutrino_hub.web.panel_runtime import PanelRuntime

from tests.conftest import StubLinkStatus, link


def runtime_with(monkeypatch, *, network: dict, status: StubLinkStatus) -> PanelRuntime:
    runtime = object.__new__(PanelRuntime)
    monkeypatch.setattr(runtime_module, "read_config", lambda name: network)
    monkeypatch.setattr(runtime_module, "RouterLinkStatus", lambda: status)
    return runtime


def test_a_wan_role_answers_first(monkeypatch):
    network = {
        "mode": "router",
        "interfaces": [
            {"name": "enp1s0", "role": "wan"},
            {"name": "enp2s0", "role": "lan", "lan": {"address": "192.168.8.1"}},
        ],
    }
    status = StubLinkStatus(
        [
            link("enp1s0", address="203.0.113.7/24"),
            link("enp2s0", address="192.168.8.1/24"),
        ],
        gateways={"enp1s0": "203.0.113.1"},
    )
    runtime = runtime_with(monkeypatch, network=network, status=status)

    assert runtime.uplink_address() == "203.0.113.7/24"


def test_a_box_with_no_wan_role_names_the_default_route_interface(monkeypatch):
    """A server gives no port a role and still got installed over the network.

    The strip answering "no address" there reads as a fault on a box that is
    plainly reachable.
    """
    network = {"mode": "server", "interfaces": [{"name": "enp1s0"}]}
    status = StubLinkStatus(
        [link("enp1s0", address="203.0.113.7/24")],
        gateways={"enp1s0": "203.0.113.1"},
    )
    runtime = runtime_with(monkeypatch, network=network, status=status)

    assert runtime.uplink_address() == "203.0.113.7/24"


def test_a_box_with_no_way_out_has_no_address_to_name(monkeypatch):
    network = {"mode": "server", "interfaces": [{"name": "enp1s0"}]}
    status = StubLinkStatus([link("enp1s0", address="203.0.113.7/24")])
    runtime = runtime_with(monkeypatch, network=network, status=status)

    assert runtime.uplink_address() is None
