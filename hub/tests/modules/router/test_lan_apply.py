"""What applying a served network does to the interface's other roles.

A radio that was an uplink a moment ago still has a lease client running on
it, and a served network takes no lease, wired or wireless: the address is
the one somebody chose. The access point's unit is also the one the package
ships, since the applier restarts it by name.
"""

from pathlib import Path

from neutrino_hub.modules.router import routes
from neutrino_hub.modules.router.constants import ROUTER_HOSTAPD_UNIT
from neutrino_hub.modules.router.link_status import LINK_KIND_WIFI

from tests.conftest import lan_entry, network_config, wan_entry

SERVICES = Path(routes.__file__).resolve().parents[2] / "data" / "services"


def _applier(kinds: dict) -> routes.RouterInterfaceApplier:
    """An applier over the given link kinds, with no machine read."""
    applier = routes.RouterInterfaceApplier.__new__(routes.RouterInterfaceApplier)
    applier._kinds = kinds
    applier._is_failed_restarted = True
    applier._is_lease_awaited = True
    applier._waiting = []
    return applier


def test_a_wireless_lan_stops_its_lease_client_before_publishing(monkeypatch):
    calls = []

    class FakeLeaseClient:
        def __init__(self, *, interface):
            self.interface = interface

        def stop(self):
            calls.append(("lease stopped", self.interface))

    class FakeAccessPoint:
        def __init__(self, *, interface):
            self.interface = interface

        def publish(self, *, interface, is_failed_restarted=True):
            calls.append(("published", self.interface))
            return True

    monkeypatch.setattr(routes, "RouterDhcpClient", FakeLeaseClient)
    monkeypatch.setattr(routes, "RouterWifiAccessPoint", FakeAccessPoint)
    network = network_config(
        lan_entry(
            "wlp3s0", address="192.168.101.2", ap_ssid="n", ap_passphrase="12345678"
        )
    )

    changes = _applier({"wlp3s0": LINK_KIND_WIFI})._apply_lan(
        network.interface("wlp3s0")
    )

    assert calls == [("lease stopped", "wlp3s0"), ("published", "wlp3s0")]
    assert changes == ["wlp3s0 publishing n on 192.168.101.2/24"]


def test_a_radio_taken_down_under_a_running_access_point_is_raised(monkeypatch):
    """hostapd keeps running with its radio down and publishes nothing until
    the radio is back up."""
    raised = []

    class FakeLeaseClient:
        def __init__(self, *, interface):
            pass

        def stop(self):
            pass

    class FakeAccessPoint:
        def __init__(self, *, interface):
            pass

        def publish(self, *, interface, is_failed_restarted=True):
            return False

    monkeypatch.setattr(routes, "RouterDhcpClient", FakeLeaseClient)
    monkeypatch.setattr(routes, "RouterWifiAccessPoint", FakeAccessPoint)
    monkeypatch.setattr(routes.links, "set_up", raised.append)
    up = set()
    monkeypatch.setattr(routes, "admin_up_interfaces", lambda: up)
    radio = network_config(
        lan_entry(
            "wlp3s0", address="192.168.101.2", ap_ssid="n", ap_passphrase="12345678"
        )
    ).interface("wlp3s0")
    applier = _applier({"wlp3s0": LINK_KIND_WIFI})

    assert applier._apply_lan(radio) == ["wlp3s0 up"]
    assert raised == ["wlp3s0"]

    up.add("wlp3s0")
    assert applier._apply_lan(radio) == []
    assert raised == ["wlp3s0"]


def test_a_joined_radio_rereads_its_networks_only_when_they_changed(monkeypatch):
    """Re-reading makes the radio reassociate, and every link event would
    otherwise drop the uplink it is."""
    calls = []

    class FakeClient:
        state = "active"

        def __init__(self, *, interface):
            pass

        def reconfigure(self):
            calls.append("reconfigure")

        def start(self):
            calls.append("start")

    class FakeAccessPoint:
        state = "inactive"

        def __init__(self, *, interface):
            pass

        def unpublish(self):
            calls.append("unpublish")

    changed = [False]
    monkeypatch.setattr(routes, "RouterWifiClient", FakeClient)
    monkeypatch.setattr(routes, "RouterWifiAccessPoint", FakeAccessPoint)
    monkeypatch.setattr(routes, "_known_networks", lambda: None)
    monkeypatch.setattr(
        routes, "write_supplicant_config", lambda name, known: changed[0]
    )
    radio = network_config(wan_entry("wlp3s0")).interface("wlp3s0")
    applier = _applier({"wlp3s0": LINK_KIND_WIFI})

    applier._join_network(radio)
    assert calls == []

    changed[0] = True
    applier._join_network(radio)
    assert calls == ["reconfigure"]


def test_the_access_point_unit_is_the_one_the_package_ships():
    template = ROUTER_HOSTAPD_UNIT.replace("{interface}", "")

    assert (SERVICES / template).is_file(), sorted(p.name for p in SERVICES.iterdir())
