"""The Network tab's API, with the machine underneath it replaced by a stub.

Nothing here reads ``config/`` or touches an interface. The runtime is a fake
holding the configuration in memory, and the link reader answers from a
dictionary, so the whole request path — validation, the plan, the view — is
exercised without the suite being able to reconfigure the box it runs on.

The validations are the point. Each one stands between a saved form and a
gateway that has stopped being reachable.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.router.connections import (
    RouterConnection,
    RouterConnectionSet,
)
from neutrino_hub.modules.router.credentials import RouterCredentialReader
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig
from neutrino_hub.modules.router.link_status import LINK_KIND_WIFI
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers import network as network_router

from tests.conftest import StubLinkStatus, lan_entry, link, wan_entry

UPSTREAM_GATEWAY = "198.51.100.129"


class FakeRuntime:
    """Just the parts of :class:`PanelRuntime` the Network routes reach for."""

    def __init__(self, config: RouterNetworkConfig, status: StubLinkStatus):
        self._config = config
        self._status = status
        self._connections = RouterConnectionSet()
        self.applied: list[str | None] = []

    def network(self) -> RouterNetworkConfig:
        return RouterNetworkConfig.from_dict(self._config.to_dict())

    def write_network(self, config: RouterNetworkConfig) -> None:
        self._config = config

    def connections(self) -> RouterConnectionSet:
        return RouterConnectionSet.from_dict(self._connections.to_dict())

    def write_connections(self, connections: RouterConnectionSet) -> None:
        self._connections = connections

    def link_status(self) -> StubLinkStatus:
        return self._status

    async def apply_network(self, *, only: str | None = None) -> str:
        self.applied.append(only)
        return "applied"


@pytest.fixture
def box(monkeypatch):
    """A gateway with a wired uplink, a wired LAN, and an idle radio."""
    config = RouterNetworkConfig.from_dict(
        {
            "interfaces": [
                wan_entry("enp2s0"),
                lan_entry("enp1s0", address="192.168.100.1"),
                {"name": "wlp3s0", "role": "disabled"},
            ]
        }
    )
    status = StubLinkStatus(
        links=[
            link("enp2s0", address="198.51.100.203/25"),
            link("enp1s0", address="192.168.100.1/24", speed_mbps=2500),
            link("wlp3s0", kind=LINK_KIND_WIFI, is_up=False, speed_mbps=None),
        ],
        gateways={"enp2s0": UPSTREAM_GATEWAY},
    )
    runtime = FakeRuntime(config, status)

    # The routes build a reader of their own in a couple of places rather than
    # taking the runtime's, so the class itself is swapped for the stub.
    monkeypatch.setattr(
        network_router, "RouterLinkStatus", lambda: runtime.link_status()
    )

    app = FastAPI()
    app.include_router(network_router.router)
    app.dependency_overrides[require_session] = lambda: None
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as client:
        yield client, runtime, status


def settings_of(client, name: str) -> dict:
    payload = client.get("/api/network").json()
    for entry in payload["interfaces"]:
        if entry["settings"]["name"] == name:
            return entry["settings"]
    raise AssertionError(f"no interface {name} in the view")


# --- Reading ----------------------------------------------------------------


def test_the_view_reports_every_interface_with_its_live_state(box):
    client, _, _ = box

    payload = client.get("/api/network").json()

    names = {entry["settings"]["name"] for entry in payload["interfaces"]}
    assert names == {"enp1s0", "enp2s0", "wlp3s0"}
    assert payload["default_gateway"] == UPSTREAM_GATEWAY
    assert payload["uplink_policy"] == "failover"


def test_the_view_carries_the_plan_the_gateway_made(box):
    client, _, _ = box

    payload = client.get("/api/network").json()

    assert len(payload["lines"]) == 1
    member = payload["lines"][0]["members"][0]
    assert member["name"] == "enp2s0"
    assert member["is_active"]
    assert member["reason"]


def test_an_interface_with_no_lan_address_is_offered_a_free_subnet(box):
    """Picking a subnet has a right answer nobody wants to work out by hand."""
    client, _, _ = box

    proposed = settings_of(client, "wlp3s0")["lan"]

    assert proposed["address"] not in ("", "192.168.100.1")
    assert proposed["dhcp_range_start"].startswith(
        proposed["address"].rsplit(".", 1)[0]
    )


# --- Saving -----------------------------------------------------------------


def test_saving_an_interface_applies_only_that_one(box):
    """One interface at a time, so a mistake in the Wi-Fi cannot drop the LAN."""
    client, runtime, _ = box
    draft = settings_of(client, "wlp3s0")
    draft["role"] = "wan"

    response = client.put("/api/network/interfaces/wlp3s0", json=draft)

    assert response.status_code == 200
    assert runtime.applied == ["wlp3s0"]
    assert runtime.network().interface("wlp3s0").is_wan


def test_the_path_and_the_body_must_name_the_same_interface(box):
    client, _, _ = box
    draft = settings_of(client, "wlp3s0")

    response = client.put("/api/network/interfaces/enp1s0", json=draft)

    assert response.status_code == 400


def test_changing_the_policy_reapplies_everything(box):
    client, runtime, _ = box

    response = client.put(
        "/api/network",
        json={"is_ssh_from_wan_allowed": False, "uplink_policy": "balance"},
    )

    assert response.status_code == 200
    assert runtime.network().uplink_policy == "balance"
    assert runtime.applied == [None]


def test_an_unknown_policy_is_refused(box):
    client, _, _ = box

    response = client.put(
        "/api/network",
        json={"is_ssh_from_wan_allowed": True, "uplink_policy": "round_robin"},
    )

    assert response.status_code == 400


# --- Validations that keep the box reachable --------------------------------


def test_a_dhcp_pool_may_not_swallow_the_gateway_address(box):
    """Handing a client the gateway's own address breaks the whole network."""
    client, _, _ = box
    draft = settings_of(client, "enp1s0")
    draft["lan"]["dhcp_range_start"] = "192.168.100.1"

    response = client.put("/api/network/interfaces/enp1s0", json=draft)

    assert response.status_code == 400
    assert "outside the DHCP range" in response.json()["detail"]


def test_a_dhcp_pool_must_lie_inside_its_own_network(box):
    client, _, _ = box
    draft = settings_of(client, "enp1s0")
    draft["lan"]["dhcp_range_start"] = "10.0.0.10"
    draft["lan"]["dhcp_range_end"] = "10.0.0.20"

    response = client.put("/api/network/interfaces/enp1s0", json=draft)

    assert response.status_code == 400


def test_two_served_networks_may_not_overlap(box):
    """Overlapping LANs leave clients on either with an ambiguous route."""
    client, _, _ = box
    draft = settings_of(client, "wlp3s0")
    draft["role"] = "lan"
    draft["lan"].update(
        {
            "address": "192.168.100.9",
            "dhcp_range_start": "192.168.100.20",
            "dhcp_range_end": "192.168.100.30",
        }
    )
    draft["wifi"]["ap_ssid"] = "neutrino"
    draft["wifi"]["ap_passphrase"] = "hunter2hunter2"

    response = client.put("/api/network/interfaces/wlp3s0", json=draft)

    assert response.status_code == 400
    assert "overlaps" in response.json()["detail"]


def test_an_access_point_needs_a_usable_passphrase(box):
    """There is no open option: an open access point is an open route in."""
    client, _, _ = box
    draft = settings_of(client, "wlp3s0")
    draft["role"] = "lan"
    draft["wifi"]["ap_ssid"] = "neutrino"
    draft["wifi"]["ap_passphrase"] = "short"

    response = client.put("/api/network/interfaces/wlp3s0", json=draft)

    assert response.status_code == 400
    assert "8 to 63" in response.json()["detail"]


def test_a_static_uplink_gateway_must_sit_in_its_own_subnet(box):
    client, _, _ = box
    draft = settings_of(client, "enp2s0")
    draft["wan"].update(
        {
            "method": "static",
            "address": "10.0.0.5",
            "prefix_len": 24,
            "gateway": "10.9.9.1",
        }
    )

    response = client.put("/api/network/interfaces/enp2s0", json=draft)

    assert response.status_code == 400
    assert "must lie inside" in response.json()["detail"]


def test_a_static_uplink_without_a_gateway_is_refused(box):
    client, _, _ = box
    draft = settings_of(client, "enp2s0")
    draft["wan"].update(
        {"method": "static", "address": "10.0.0.5", "prefix_len": 24, "gateway": None}
    )

    response = client.put("/api/network/interfaces/enp2s0", json=draft)

    assert response.status_code == 400


def test_a_radio_without_access_point_mode_cannot_serve_a_network(box):
    """Refused up front rather than at the moment the access point fails to start."""
    client, runtime, status = box
    status._links = [
        (
            entry
            if entry.name != "wlp3s0"
            else link("wlp3s0", kind=LINK_KIND_WIFI, is_up=False, is_ap_capable=False)
        )
        for entry in status._links
    ]
    draft = settings_of(client, "wlp3s0")
    draft["role"] = "lan"
    draft["wifi"]["ap_ssid"] = "neutrino"
    draft["wifi"]["ap_passphrase"] = "hunter2hunter2"

    response = client.put("/api/network/interfaces/wlp3s0", json=draft)

    assert response.status_code == 400
    assert "access-point mode" in response.json()["detail"]
    assert runtime.applied == []


def test_a_valid_access_point_is_accepted(box):
    client, runtime, _ = box
    draft = settings_of(client, "wlp3s0")
    draft["role"] = "lan"
    draft["wifi"]["ap_ssid"] = "neutrino"
    draft["wifi"]["ap_passphrase"] = "hunter2hunter2"

    response = client.put("/api/network/interfaces/wlp3s0", json=draft)

    assert response.status_code == 200
    assert runtime.network().interface("wlp3s0").is_lan


# --- Warnings ---------------------------------------------------------------


def test_two_uplinks_on_one_segment_produce_no_warning(box):
    """The planner already groups them, so there is nothing left to warn about."""
    client, runtime, status = box
    config = runtime.network()
    config.replace(
        RouterNetworkConfig.from_dict({"interfaces": [wan_entry("wlp3s0")]}).interfaces[
            0
        ]
    )
    runtime.write_network(config)
    status._links = [
        (
            entry
            if entry.name != "wlp3s0"
            else link("wlp3s0", kind=LINK_KIND_WIFI, address="198.51.100.197/25")
        )
        for entry in status._links
    ]
    status._gateways["wlp3s0"] = UPSTREAM_GATEWAY

    payload = client.get("/api/network").json()

    assert payload["warnings"] == []
    assert len(payload["lines"]) == 1
    assert payload["lines"][0]["is_shared"]


def test_an_uplink_sharing_a_segment_with_a_served_lan_is_flagged(box):
    """The gateway cannot both hand out addresses on a network and be a client of it."""
    client, _, status = box
    status._links = [
        entry if entry.name != "enp2s0" else link("enp2s0", address="192.168.100.50/24")
        for entry in status._links
    ]

    payload = client.get("/api/network").json()

    assert len(payload["warnings"]) == 1
    assert "192.168.100.0/24" in payload["warnings"][0]


def test_pinning_an_uplink_primary_unpins_the_previous_one(box):
    """ "Prefer this one" is exclusive: the panel is not the only thing that PUTs."""
    client, runtime, _ = box
    config = runtime.network()
    config.replace(
        RouterNetworkConfig.from_dict(
            {"interfaces": [wan_entry("enp2s0", intent="primary")]}
        ).interfaces[0]
    )
    config.replace(
        RouterNetworkConfig.from_dict({"interfaces": [wan_entry("wlp3s0")]}).interfaces[
            0
        ]
    )
    runtime.write_network(config)

    draft = settings_of(client, "wlp3s0")
    draft["role"] = "wan"
    draft["wan"]["intent"] = "primary"
    response = client.put("/api/network/interfaces/wlp3s0", json=draft)

    assert response.status_code == 200
    saved = runtime.network()
    assert saved.interface("wlp3s0").wan.is_pinned_primary
    assert saved.interface("enp2s0").wan.intent == "auto"


# --- A machine the hub is a guest on -----------------------------------------


@pytest.fixture
def guest_box(monkeypatch):
    """A VPS: one port, addressed by whatever built the image, not by us."""
    config = RouterNetworkConfig.from_dict(
        {
            "mode": "server",
            "interfaces": [{"name": "enp1s0", "role": "disabled", "is_exposed": True}],
        }
    )
    status = StubLinkStatus(
        links=[link("enp1s0", address="198.51.100.7/24")],
        gateways={"enp1s0": UPSTREAM_GATEWAY},
    )
    runtime = FakeRuntime(config, status)
    monkeypatch.setattr(
        network_router, "RouterLinkStatus", lambda: runtime.link_status()
    )
    app = FastAPI()
    app.include_router(network_router.router)
    app.dependency_overrides[require_session] = lambda: None
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as client:
        yield client, runtime, status


def test_the_view_says_the_box_does_not_address_its_own_ports(guest_box):
    client, _, _ = guest_box

    assert client.get("/api/network").json()["is_addressing_owned"] is False


def test_the_view_reports_which_mode_the_box_is_in(guest_box):
    client, _, _ = guest_box

    assert client.get("/api/network").json()["mode"] == "server"


def test_the_view_offers_every_mode(guest_box):
    """Switching asks for no port, so there is nothing a machine can be too
    small for: a router on one wire is a router whose port is a trunk."""
    client, _, _ = guest_box

    offered = [mode["key"] for mode in client.get("/api/network").json()["modes"]]

    assert offered == ["server", "side_gateway", "router"]


def test_a_save_cannot_change_whether_an_interface_answers(guest_box):
    """Exposure is written by the panel that shows every interface at once,
    so a body claiming otherwise is a stale client."""
    client, runtime, _ = guest_box
    draft = settings_of(client, "enp1s0")
    draft["is_exposed"] = False

    response = client.put("/api/network/interfaces/enp1s0", json=draft)

    assert response.status_code == 200
    assert runtime.network().interface("enp1s0").is_exposed


def test_closing_every_interface_is_allowed(guest_box):
    """It leaves the box reachable over the overlay and nowhere else, which is
    a posture somebody may want and the firewall is the only thing that has to
    understand it."""
    client, runtime, _ = guest_box

    response = client.put("/api/network", json=_options(exposed=[]))

    assert response.status_code == 200
    assert runtime.network().exposed_device_names == []


def test_an_interface_this_machine_does_not_have_cannot_be_opened(guest_box):
    client, _, _ = guest_box

    response = client.put("/api/network", json=_options(exposed=["enp9s0"]))

    assert response.status_code == 400


def test_a_mode_that_is_not_one_of_them_is_refused(box):
    client, _, _ = box

    response = client.put("/api/network/mode", json={"mode": "one_arm_router"})

    assert response.status_code == 400


def test_becoming_a_router_takes_the_machine_over(guest_box):
    """And leaves the roles to the interface panel: the mode says the hub
    addresses this machine, not what each port is for."""
    client, runtime, _ = guest_box

    response = client.put("/api/network/mode", json={"mode": "router"})

    assert response.status_code == 200
    saved = runtime.network()
    assert saved.mode == "router"
    assert saved.is_addressing_owned
    assert saved.interface("enp1s0").is_disabled


def test_becoming_a_router_keeps_the_roles_a_router_had(box):
    """Nothing about the wiring changes when the mode is re-read; only the
    modes that cannot hold a role take one away."""
    client, runtime, _ = box
    client.put("/api/network/mode", json={"mode": "server"})

    client.put("/api/network/mode", json={"mode": "router"})

    assert {entry.role for entry in runtime.network().interfaces} == {"disabled"}


def test_becoming_a_router_drops_the_upstream_router_a_side_gateway_left(
    guest_box,
):
    """A router's way out is an uplink, and the panel has no field for a
    served network's own router outside the side-gateway mode."""
    client, runtime, _ = guest_box
    client.put("/api/network/mode", json={"mode": "side_gateway"})

    client.put("/api/network/mode", json={"mode": "router"})

    saved = runtime.network().interface("enp1s0")
    assert saved.lan.upstream_gateway is None


def test_becoming_a_server_hands_the_machine_back(box, monkeypatch):
    """Leaving the router mode has to give the interfaces back to whatever ran
    the machine before. Without it the box keeps the addresses it was given,
    frozen, with nothing renewing the lease."""
    handed: list = []
    monkeypatch.setattr(
        network_router, "hand_back", lambda network: handed.append(network.mode) or []
    )
    client, runtime, _ = box

    response = client.put("/api/network/mode", json={"mode": "server"})

    assert response.status_code == 200
    assert handed == ["server"]
    saved = runtime.network()
    assert saved.mode == "server"
    assert not saved.is_addressing_owned
    assert {entry.role for entry in saved.interfaces} == {"disabled"}


def test_a_machine_already_a_guest_is_not_handed_back_again(guest_box, monkeypatch):
    handed: list = []
    monkeypatch.setattr(
        network_router, "hand_back", lambda network: handed.append(network) or []
    )
    client, _, _ = guest_box

    client.put("/api/network/mode", json={"mode": "side_gateway"})

    assert handed == []


def test_a_side_gateway_answers_on_the_network_it_joined(guest_box):
    """It is where the panel and DNS are reached. A served network the input
    chain drops on is one the devices told to use it cannot resolve through."""
    client, runtime, _ = guest_box

    client.put("/api/network/mode", json={"mode": "side_gateway"})

    assert runtime.network().interface("enp1s0").is_exposed


def test_leaving_a_mode_with_trunks_takes_the_VLANs_with_it(box, monkeypatch):
    """Neither guest mode has trunks. A VLAN left behind as an entry claiming
    to be a physical port can never be deleted and its tag can never be made
    again."""
    removed: list = []
    monkeypatch.setattr(
        network_router, "remove_vlan_device", lambda name: removed.append(name) or []
    )
    client, runtime, _ = box
    client.put(
        "/api/network/interfaces/enp1s0",
        json=dict(settings_of(client, "enp1s0"), role="split"),
    )
    assert any(entry.is_vlan for entry in runtime.network().interfaces)

    client.put("/api/network/mode", json={"mode": "server"})

    saved = runtime.network()
    assert [entry.name for entry in saved.interfaces if entry.is_vlan] == []
    assert removed == ["enp1s0.main"]


def test_becoming_a_side_gateway_joins_the_network_it_is_already_on(guest_box):
    """The port carrying the way out is the network it forwards for, and the
    address it holds there is the one to keep: nobody types an address for a
    network somebody else runs."""
    client, runtime, _ = guest_box

    response = client.put("/api/network/mode", json={"mode": "side_gateway"})

    assert response.status_code == 200
    joined = runtime.network().interface("enp1s0")
    assert joined.is_lan
    assert joined.lan.address == "198.51.100.7"
    assert joined.lan.upstream_gateway == UPSTREAM_GATEWAY
    assert not joined.lan.is_dhcp_enabled


def _options(*, exposed: list) -> dict:
    return {
        "uplink_policy": "failover",
        "is_inter_lan_allowed": True,
        "exposed_interfaces": exposed,
    }


def _read_only_from(monkeypatch, store, tmp_path) -> None:
    """Point the reader at one directory of this test's own making."""
    monkeypatch.setattr(
        network_router,
        "RouterCredentialReader",
        lambda: RouterCredentialReader(
            nm_dirs=(store,),
            iwd_dir=tmp_path / "none",
            wpa_dir=tmp_path / "none",
            netplan_dir=tmp_path / "none",
        ),
    )


def test_taking_the_machine_over_reads_the_wifi_it_already_knew(
    guest_box, tmp_path, monkeypatch
):
    """A box that has been somebody's laptop already has the passphrase on
    disk. Reading it is the difference between one that keeps working and one
    that asks for every network again."""
    client, runtime, _ = guest_box
    store = tmp_path / "system-connections"
    store.mkdir()
    (store / "home.nmconnection").write_text(
        "[connection]\ntype=wifi\n\n[wifi]\nssid=home-5g\n\n"
        "[wifi-security]\nkey-mgmt=wpa-psk\npsk=from-the-laptop\npsk-flags=0\n"
    )
    _read_only_from(monkeypatch, store, tmp_path)

    client.put("/api/network/mode", json=_becoming_an_owner())

    known = runtime.connections().find("home-5g")
    assert known is not None
    assert known.psk == "from-the-laptop"
    assert known.source == "inherited:networkmanager"


def test_a_network_somebody_typed_is_not_replaced_by_one_that_was_found(
    guest_box, tmp_path, monkeypatch
):
    """Somebody typed that one. A decision is not overwritten by what was
    found lying about on the disk."""
    client, runtime, _ = guest_box
    typed = RouterConnectionSet(
        connections=[RouterConnection(ssid="home-5g", psk="what-i-typed")]
    )
    runtime.write_connections(typed)
    store = tmp_path / "system-connections"
    store.mkdir()
    (store / "home.nmconnection").write_text(
        "[connection]\ntype=wifi\n\n[wifi]\nssid=home-5g\n\n"
        "[wifi-security]\nkey-mgmt=wpa-psk\npsk=stale-one\npsk-flags=0\n"
    )
    _read_only_from(monkeypatch, store, tmp_path)

    client.put("/api/network/mode", json=_becoming_an_owner())

    assert runtime.connections().find("home-5g").psk == "what-i-typed"


def _becoming_an_owner() -> dict:
    """The guest box being taken over."""
    return {"mode": "router"}


# --- the networks the box knows ---


def test_a_stored_passphrase_never_comes_back_out(box):
    """A listing says a network is known, never what its key is."""
    client, runtime, _ = box
    runtime.write_connections(
        RouterConnectionSet(
            connections=[RouterConnection(ssid="home", psk="hunter2hunter2")]
        )
    )

    payload = client.get("/api/network/wifi_networks").json()

    assert payload["networks"][0]["ssid"] == "home"
    assert payload["networks"][0]["has_secret"] is True
    assert "hunter2hunter2" not in response_text(payload)


def test_a_network_whose_key_is_elsewhere_says_so(box):
    """False is what makes the page ask for it once, rather than the radio
    failing to associate every time the network comes into range."""
    client, runtime, _ = box
    runtime.write_connections(
        RouterConnectionSet(
            connections=[
                RouterConnection(ssid="office", psk="", source="inherited:iwd")
            ]
        )
    )

    network = client.get("/api/network/wifi_networks").json()["networks"][0]

    assert network["has_secret"] is False
    assert network["source"] == "inherited:iwd"


def test_the_preferred_network_is_listed_first(box):
    client, runtime, _ = box
    runtime.write_connections(
        RouterConnectionSet(
            connections=[
                RouterConnection(ssid="guest", psk="x" * 12, priority=1),
                RouterConnection(ssid="home", psk="x" * 12, priority=10),
            ]
        )
    )

    names = [
        entry["ssid"]
        for entry in client.get("/api/network/wifi_networks").json()["networks"]
    ]

    assert names == ["home", "guest"]


def test_forgetting_a_network_removes_it(box, monkeypatch):
    client, runtime, _ = box
    monkeypatch.setattr(network_router, "_rerender_radios", lambda runtime, known: None)
    runtime.write_connections(
        RouterConnectionSet(connections=[RouterConnection(ssid="home", psk="x" * 12)])
    )

    response = client.delete("/api/network/wifi_networks/home")

    assert response.status_code == 200
    assert response.json()["networks"] == []
    assert runtime.connections().find("home") is None


def test_forgetting_one_the_box_does_not_know_is_a_404(box):
    client, _, _ = box

    assert client.delete("/api/network/wifi_networks/never-seen").status_code == 404


def response_text(payload) -> str:
    import json

    return json.dumps(payload)
