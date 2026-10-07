"""A VLAN that goes takes its lease client with it, and a hand-back stops
every lease client systemd still has, whatever the configuration names."""

from neutrino_hub.modules.router import routes
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig


class LeaseClient:
    """A lease client recording each stop, in the order of the calls."""

    calls: list = []
    standing: set = set()

    def __init__(self, *, interface):
        self.interface = interface
        self.unit = f"neutrino_hub_dhcpcd@{interface}.service"

    @property
    def is_standing(self):
        return self.interface in LeaseClient.standing

    def stop(self):
        LeaseClient.calls.append(("stop", self.unit))


def test_a_vlan_s_lease_client_is_stopped_before_its_device_goes(monkeypatch):
    LeaseClient.calls = []
    monkeypatch.setattr(routes, "RouterDhcpClient", LeaseClient)
    monkeypatch.setattr(
        routes.links,
        "remove_vlan",
        lambda name: LeaseClient.calls.append(("remove", name)) or True,
    )

    assert routes.remove_vlan_device("enp3s0.1") == ["enp3s0.1 removed"]
    assert LeaseClient.calls == [
        ("stop", "neutrino_hub_dhcpcd@enp3s0.1.service"),
        ("remove", "enp3s0.1"),
    ]


def test_a_disabled_vlan_s_lease_client_is_stopped(monkeypatch):
    LeaseClient.calls = []
    monkeypatch.setattr(routes, "RouterDhcpClient", LeaseClient)
    monkeypatch.setattr(routes.links, "remove_vlan", lambda name: True)
    network = RouterNetworkConfig.from_dict(
        {
            "mode": "router",
            "interfaces": [
                {"name": "enp3s0", "role": "split"},
                {
                    "name": "enp3s0.1",
                    "role": "disabled",
                    "vlan": {"parent": "enp3s0", "id": 1},
                },
            ],
        }
    )
    applier = routes.RouterInterfaceApplier.__new__(routes.RouterInterfaceApplier)
    applier._network = network
    applier._kinds = {}

    assert applier._apply_disabled(network.interface("enp3s0.1")) == [
        "enp3s0.1 removed"
    ]
    assert ("stop", "neutrino_hub_dhcpcd@enp3s0.1.service") in LeaseClient.calls


def test_a_hand_back_stops_the_lease_clients_systemd_lists(monkeypatch):
    LeaseClient.calls = []
    LeaseClient.standing = {"enp1s0", "enp3s0.1"}

    class Idle:
        is_running = False

        def __init__(self, *, interface):
            pass

    class Ruleset:
        def flush(self):
            pass

    monkeypatch.setattr(routes, "RouterDhcpClient", LeaseClient)
    monkeypatch.setattr(routes, "RouterWifiClient", Idle)
    monkeypatch.setattr(routes, "RouterWifiAccessPoint", Idle)
    monkeypatch.setattr(routes, "RouterRulesetApplier", Ruleset)
    monkeypatch.setattr(
        routes, "lease_client_interfaces", lambda: ["enp1s0", "enp3s0.1"]
    )
    monkeypatch.setattr(routes.stack, "stand_up", lambda: [])
    monkeypatch.setattr(routes, "rendered_network_resolvers", lambda: [])
    network = RouterNetworkConfig.from_dict(
        {"mode": "router", "interfaces": [{"name": "enp1s0", "role": "wan"}]}
    )

    changes = routes.hand_back(network)

    assert LeaseClient.calls == [
        ("stop", "neutrino_hub_dhcpcd@enp1s0.service"),
        ("stop", "neutrino_hub_dhcpcd@enp3s0.1.service"),
    ]
    assert "stopped neutrino_hub_dhcpcd@enp3s0.1.service" in changes
