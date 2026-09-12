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

from tests.conftest import lan_entry, network_config

SERVICES = Path(routes.__file__).resolve().parents[2] / "data" / "services"


def _applier(kinds: dict) -> routes.RouterInterfaceApplier:
    """An applier over the given link kinds, with no machine read."""
    applier = routes.RouterInterfaceApplier.__new__(routes.RouterInterfaceApplier)
    applier._kinds = kinds
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

        def publish(self, *, interface):
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


def test_the_access_point_unit_is_the_one_the_package_ships():
    template = ROUTER_HOSTAPD_UNIT.replace("{interface}", "")

    assert (SERVICES / template).is_file(), sorted(p.name for p in SERVICES.iterdir())
