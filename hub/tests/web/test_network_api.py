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
        self.applied: list[str | None] = []

    def network(self) -> RouterNetworkConfig:
        return RouterNetworkConfig.from_dict(self._config.to_dict())

    def write_network(self, config: RouterNetworkConfig) -> None:
        self._config = config

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
        "/api/network/options",
        json={"is_ssh_from_wan_allowed": False, "uplink_policy": "balance"},
    )

    assert response.status_code == 200
    assert runtime.network().uplink_policy == "balance"
    assert runtime.applied == [None]


def test_an_unknown_policy_is_refused(box):
    client, _, _ = box

    response = client.put(
        "/api/network/options",
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
