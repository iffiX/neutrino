"""What the exit-node list does to the proxy switch, and what a node write
leaves behind.

Two pairings are guarded here. A proxy that is on and a list with nothing
enabled in it is not a state: the balancer has nothing to select, so rendering
the xray configuration raises and every Apply after it fails with that. And a
node write reaches the exit controller rather than the render, so switching
one on or off takes effect at once and leaves nothing to apply.
"""

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.xray.exit_controller import XrayExitStatus
from neutrino_hub.modules.xray.node_config import XrayNodeList
from neutrino_hub.modules.xray.node_health import XrayNodeHealth, XrayNodeSample
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers.hub import proxy_node as nodes_router
from neutrino_hub.web.routers.hub import proxy as proxy_router
from tests.conftest import unlock_vault

MEASURED_AT = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)

# One reachable-looking node, as a share link and as stored configuration.
SHARE_LINK = "ss://YWVzLTI1Ni1nY206c2VjcmV0@203.0.113.10:5800#Tokyo"  # scan: allow
STORED = {
    "nodes": [
        {
            "id": "hk1",
            "name": "Tokyo",
            "address": "203.0.113.10",
            "is_enabled": True,
            "protocol": "shadowsocks",
            "secret_id": "0" * 32,
            "shadowsocks": {"port": 5800, "method": "aes-256-gcm"},
        }
    ],
    "balancer": {
        "probe_url": "https://www.gstatic.com/generate_204",
        "reference_url": "http://www.msftconnecttest.com/connecttest.txt",
        "probe_interval_s": 60,
    },
}
BALANCER = dict(STORED["balancer"])


class FakeRuntime:
    """The two files these routes read and write, held in memory."""

    def __init__(self):
        self.files = {
            "xray/nodes.json": dict(STORED),
            "xray/routing.json": {
                "is_proxy_enabled": True,
                "is_geoip_split_enabled": True,
                "direct_domains": [],
                "direct_ips": [],
                "is_local_proxy_enabled": False,
                "socks_ports": [],
                "remote_dns": {"address": "1.1.1.1", "port": 53},
                "direct_dns": {"address": "223.5.5.5", "port": 53},
            },
        }
        self.is_config_dirty = False
        self.stats = _NoTraffic()
        self.exit_controller = _ExitController(self)
        self.listening_ports = _HeldPorts()

    def node_list(self) -> XrayNodeList:
        return XrayNodeList.from_dict(self.files["xray/nodes.json"])

    def routing(self) -> dict:
        return dict(self.files["xray/routing.json"])


class _HeldPorts:
    """A box with something already on 8080."""

    def ports(self, *, ignoring: str = "") -> set:
        return {8080}


class _NoTraffic:
    def outbound_traffic(self) -> list:
        return []


class _ExitController:
    """The exit rounds as these routes reach them.

    Records every call, so a test reads what the route asked for rather than
    what it measured; the measurements themselves are written down by hand.
    """

    def __init__(self, runtime: FakeRuntime):
        self._runtime = runtime
        self.status = XrayExitStatus()
        self.windows: dict = {}
        self.refreshed: list = []
        self.reselect_count = 0
        self.wake_count = 0

    def healths(self) -> dict:
        return dict(self.windows)

    def refresh(self, *, only: "str | None" = None) -> XrayExitStatus:
        self.refreshed.append(only)
        if only is not None and not any(
            node.id == only for node in self._runtime.node_list().nodes
        ):
            raise KeyError(f"no node with id {only!r}")
        return self.status

    def reselect(self) -> XrayExitStatus:
        self.reselect_count += 1
        return self.status

    def wake(self) -> None:
        self.wake_count += 1


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    unlock_vault(monkeypatch, tmp_path)
    runtime = FakeRuntime()
    for module in (nodes_router, proxy_router):
        monkeypatch.setattr(
            module,
            "write_config",
            lambda name, data, runtime=runtime: runtime.files.__setitem__(name, data),
        )
    app = FastAPI()
    app.include_router(nodes_router.router)
    app.include_router(proxy_router.router)
    app.dependency_overrides[require_session] = lambda: None
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as opened:
        yield opened, runtime


def is_proxy_on(runtime) -> bool:
    return runtime.files["xray/routing.json"]["is_proxy_enabled"]


def test_removing_the_last_node_switches_the_proxy_off(client):
    """Otherwise the next Apply fails on a configuration that cannot be
    rendered, and the page says nothing about the switch that fixes it."""
    opened, runtime = client

    response = opened.post("/api/hub/proxy/node/remove", json={"node_id": "hk1"})

    assert response.status_code == 200
    assert not is_proxy_on(runtime)


def test_disabling_the_last_node_switches_the_proxy_off(client):
    """The same state reached by the other door. It used to be refused here
    and allowed there, which is one rule with two answers."""
    opened, runtime = client

    response = opened.post(
        "/api/hub/proxy/node/set", json={"node_id": "hk1", "is_enabled": False}
    )

    assert response.status_code == 200
    assert not is_proxy_on(runtime)


def test_a_node_that_stays_leaves_the_switch_alone(client):
    opened, runtime = client
    opened.post(
        "/api/hub/proxy/node/add", json={"link": SHARE_LINK.replace("hk1", "hk2")}
    )

    opened.post("/api/hub/proxy/node/remove", json={"node_id": "hk1"})

    assert is_proxy_on(runtime)


def test_adding_a_node_does_not_switch_the_proxy_back_on(client):
    """It is the person's switch. Emptying the list is what turns it off,
    because that state cannot be rendered; filling it again is not consent to
    start proxying."""
    opened, runtime = client
    opened.post("/api/hub/proxy/node/remove", json={"node_id": "hk1"})

    opened.post("/api/hub/proxy/node/add", json={"link": SHARE_LINK})

    assert not is_proxy_on(runtime)


def test_the_switch_cannot_be_turned_on_with_nothing_to_go_out_through(client):
    opened, runtime = client
    opened.post("/api/hub/proxy/node/remove", json={"node_id": "hk1"})
    settings = dict(runtime.files["xray/routing.json"], is_proxy_enabled=True)

    response = opened.post("/api/hub/proxy/set", json=settings)

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "no_exit_node_enabled"


def test_two_listeners_cannot_share_a_port(client):
    opened, runtime = client
    settings = dict(
        runtime.files["xray/routing.json"],
        socks_ports=[
            {"port": 1080, "is_proxied": False},
            {"port": 1080, "is_proxied": True},
        ],
    )

    response = opened.post("/api/hub/proxy/set", json=settings)

    assert response.status_code == 400


@pytest.mark.parametrize("port", [0, -1, 65536])
def test_a_port_no_listener_can_take_is_refused(client, port):
    opened, runtime = client
    settings = dict(
        runtime.files["xray/routing.json"],
        socks_ports=[{"port": port, "is_proxied": False}],
    )

    response = opened.post("/api/hub/proxy/set", json=settings)

    assert response.status_code == 400


@pytest.mark.parametrize(
    "settings,label",
    [
        ({"probe_interval_s": 0}, "a probe interval of zero"),
        ({"probe_interval_s": -60}, "a probe interval running backwards"),
        ({"probe_interval_s": 999999}, "a probe interval of days"),
        ({"probe_url": "not a url"}, "a probe target that is not a URL"),
        ({"probe_url": ""}, "no probe target at all"),
        ({"reference_url": "not a url"}, "a reference that is not a URL"),
        ({"reference_url": ""}, "no reference at all"),
    ],
)
def test_the_balancer_refuses_what_a_round_cannot_keep(client, settings, label):
    """A round fetches both addresses and sleeps the interval between two of
    them, so a bad one is a hub that measures nothing and never says why."""
    opened, _ = client
    body = dict(BALANCER)
    body.update(settings)

    response = opened.post("/api/hub/proxy/balancer/set", json=body)

    assert response.status_code == 400, label


def test_many_listeners_are_kept_in_the_order_they_were_given(client):
    """Adding a row at a time is how the page works, and a list that reorders
    itself under that is one nobody can edit."""
    opened, runtime = client
    ports = [
        {"port": 2000 + index, "is_proxied": index % 2 == 0} for index in range(32)
    ]
    settings = dict(runtime.files["xray/routing.json"], socks_ports=ports)

    response = opened.post("/api/hub/proxy/set", json=settings)

    assert response.status_code == 200
    assert runtime.files["xray/routing.json"]["socks_ports"] == ports


@pytest.mark.parametrize(
    "resolver",
    [
        {"address": "not.an.address", "port": 53},
        {"address": "", "port": 53},
        {"address": "1.1.1.1", "port": 0},
        {"address": "1.1.1.1", "port": 70000},
    ],
)
def test_a_resolver_the_proxy_cannot_use_is_refused(client, resolver):
    """Both resolvers are written straight into the xray config. A bad one is
    a proxy that will not start, found at the next Apply rather than here."""
    opened, runtime = client

    response = opened.post(
        "/api/hub/proxy/set",
        json=dict(runtime.files["xray/routing.json"], direct_dns=resolver),
    )

    assert response.status_code == 400


@pytest.mark.parametrize(
    "lists,label",
    [
        ({"direct_ips": ["192.0.2.300"]}, "an address with a byte over 255"),
        ({"direct_ips": ["cn"]}, "a country code where an address goes"),
        ({"direct_ips": [""]}, "a blank line left in the list"),
        ({"direct_domains": ["regexp:(unclosed"]}, "a regular expression that is not"),
    ],
)
def test_a_direct_list_xray_will_not_load_is_refused(client, lists, label):
    """xray refuses the whole configuration over one of these, so accepting it
    here is a page that saves and then fails every Apply after it."""
    opened, runtime = client
    settings = dict(runtime.files["xray/routing.json"], **lists)

    response = opened.post("/api/hub/proxy/set", json=settings)

    assert response.status_code == 400


def test_a_direct_list_of_prefixes_and_databases_is_kept(client):
    opened, runtime = client
    settings = dict(
        runtime.files["xray/routing.json"],
        direct_ips=["192.0.2.0/24", "geoip:cn"],
        direct_domains=["geosite:cn", "example.com"],
    )

    response = opened.post("/api/hub/proxy/set", json=settings)

    assert response.status_code == 200
    assert runtime.files["xray/routing.json"]["direct_ips"] == [
        "192.0.2.0/24",
        "geoip:cn",
    ]


def test_a_listener_cannot_take_a_port_the_box_already_holds(client):
    """xray validates a configuration without binding it and its unit reports
    started at fork, so this is found otherwise as a proxy that is simply
    absent."""
    opened, runtime = client
    settings = dict(
        runtime.files["xray/routing.json"],
        socks_ports=[{"port": 8080, "is_proxied": False}],
    )

    response = opened.post("/api/hub/proxy/set", json=settings)

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "port_already_in_use",
        "params": {"value": 8080},
    }


def test_a_free_port_is_still_accepted(client):
    opened, runtime = client
    settings = dict(
        runtime.files["xray/routing.json"],
        socks_ports=[{"port": 1080, "is_proxied": False}],
    )

    assert opened.post("/api/hub/proxy/set", json=settings).status_code == 200


def test_a_proxied_listener_needs_no_exit_node_to_be_saved(client):
    """It is a listener waiting for a node, not a contradiction: the renderer
    declines to publish it while there is nothing to go out through, so the
    page has nothing to refuse."""
    opened, runtime = client
    opened.post("/api/hub/proxy/node/remove", json={"node_id": "hk1"})
    settings = dict(
        runtime.files["xray/routing.json"],
        socks_ports=[{"port": 1081, "is_proxied": True}],
    )

    response = opened.post("/api/hub/proxy/set", json=settings)

    assert response.status_code == 200


def test_the_hubs_own_switch_cannot_be_turned_on_with_nothing_to_go_out_through(client):
    """It diverts, so it needs somewhere for what it diverts to go."""
    opened, runtime = client
    opened.post("/api/hub/proxy/node/remove", json={"node_id": "hk1"})
    settings = dict(runtime.files["xray/routing.json"], is_local_proxy_enabled=True)

    response = opened.post("/api/hub/proxy/set", json=settings)

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "no_exit_node_enabled"


def test_an_added_link_seals_its_secret_and_stores_the_reference(client):
    opened, runtime = client

    response = opened.post(
        "/api/hub/proxy/node/add", json={"link": SHARE_LINK.replace("hk1", "hk2")}
    )

    assert response.status_code == 201
    stored = runtime.files["xray/nodes.json"]["nodes"][-1]
    assert stored["secret_id"]
    assert "password" not in stored["shadowsocks"]
    from neutrino_hub.modules.credentials.vault import SecretVault

    assert SecretVault().open(stored["secret_id"]) == {"value": "secret"}


def test_removing_a_node_takes_its_vault_object_with_it(client):
    opened, runtime = client
    opened.post(
        "/api/hub/proxy/node/add", json={"link": SHARE_LINK.replace("hk1", "hk2")}
    )
    stored = runtime.files["xray/nodes.json"]["nodes"][-1]

    opened.post("/api/hub/proxy/node/remove", json={"node_id": stored["id"]})

    from neutrino_hub.modules.credentials.vault import SecretVault

    assert SecretVault().get(stored["secret_id"]) is None


def measured(*, request_ms: "int | None") -> XrayNodeHealth:
    """One node's window, as a round would leave it."""
    return XrayNodeHealth(
        tag="node_hk1",
        samples=[XrayNodeSample(at=MEASURED_AT, connect_ms=12, request_ms=request_ms)],
        probed_at=MEASURED_AT,
        succeeded_at=MEASURED_AT if request_ms is not None else None,
    )


def test_the_list_reports_what_the_controller_measured(client):
    """The list reads the windows the controller already holds; it measures
    nothing and reaches xray for nothing."""
    opened, runtime = client
    runtime.exit_controller.windows = {"node_hk1": measured(request_ms=140)}
    runtime.exit_controller.status = XrayExitStatus(exit_tag="node_hk1")

    node = opened.get("/api/hub/proxy/node").json()["nodes"][0]

    assert node["is_alive"]
    assert node["is_selected"]
    assert (node["connect_ms"], node["request_ms"]) == (12, 140)
    assert node["probed_at"] == MEASURED_AT.isoformat()
    assert node["success_rate"] == 1.0
    assert node["score_ms"] == 140


def test_a_node_nobody_has_measured_reads_as_neither_alive_nor_timed(client):
    """An empty window is ignorance, not a failure, and the page says so by
    showing no number at all."""
    opened, _ = client

    node = opened.get("/api/hub/proxy/node").json()["nodes"][0]

    assert not node["is_alive"]
    assert (node["connect_ms"], node["request_ms"], node["score_ms"]) == (
        None,
        None,
        None,
    )
    assert node["probed_at"] == ""


def test_a_switched_off_node_is_still_reported_with_its_measurement(client):
    """Every node stays resident in xray and keeps a window, so the page can
    show what a node does before anybody enables it."""
    opened, runtime = client
    runtime.exit_controller.windows = {"node_hk1": measured(request_ms=140)}
    opened.post("/api/hub/proxy/node/set", json={"node_id": "hk1", "is_enabled": False})

    nodes = opened.get("/api/hub/proxy/node").json()["nodes"]

    assert [node["id"] for node in nodes] == ["hk1"]
    assert not nodes[0]["is_enabled"]
    assert nodes[0]["is_alive"]


def test_testing_one_node_measures_that_one_and_answers_with_the_list(client):
    """A write answers with what the matching read answers, so the page
    replaces its state rather than merging a single node into it."""
    opened, runtime = client

    response = opened.post("/api/hub/proxy/node/test", json={"node_id": "hk1"})

    assert response.status_code == 200
    assert runtime.exit_controller.refreshed == ["hk1"]
    assert [node["id"] for node in response.json()["nodes"]] == ["hk1"]


def test_testing_with_no_node_measures_them_all_in_one_round(client):
    """Test-all used to be one request per node, each holding a thread for a
    whole probe timeout."""
    opened, runtime = client

    response = opened.post("/api/hub/proxy/node/test", json={})

    assert response.status_code == 200
    assert runtime.exit_controller.refreshed == [None]


def test_testing_a_node_that_is_not_in_the_list_is_refused_by_name(client):
    opened, _ = client

    response = opened.post("/api/hub/proxy/node/test", json={"node_id": "gone"})

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "node_unknown",
        "params": {"node": "gone"},
    }


def test_switching_a_node_on_reaches_the_controller_and_leaves_no_apply(client):
    """Every node is resident in xray, so enabling one changes which node may
    be chosen and nothing that has to be rendered."""
    opened, runtime = client

    response = opened.post(
        "/api/hub/proxy/node/set", json={"node_id": "hk1", "is_enabled": True}
    )

    assert response.status_code == 200
    assert runtime.exit_controller.reselect_count == 1
    assert not runtime.is_config_dirty


def test_renaming_a_node_leaves_nothing_to_apply(client):
    opened, runtime = client

    opened.post("/api/hub/proxy/node/set", json={"node_id": "hk1", "name": "Osaka"})

    assert runtime.files["xray/nodes.json"]["nodes"][0]["name"] == "Osaka"
    assert not runtime.is_config_dirty


def test_losing_the_last_enabled_node_does_leave_something_to_apply(client):
    """The scopes are switched off in `config/`, and that is a render the box
    is not running yet."""
    opened, runtime = client

    opened.post("/api/hub/proxy/node/set", json={"node_id": "hk1", "is_enabled": False})

    assert runtime.is_config_dirty


def test_the_measurement_settings_take_effect_without_an_apply(client):
    """None of the three reaches the xray configuration; the next round reads
    them out of `config/`."""
    opened, runtime = client

    response = opened.post(
        "/api/hub/proxy/balancer/set", json=dict(BALANCER, probe_interval_s=30)
    )

    assert response.status_code == 200
    assert runtime.files["xray/nodes.json"]["balancer"]["probe_interval_s"] == 30
    assert runtime.exit_controller.wake_count == 1
    assert not runtime.is_config_dirty


def test_the_reference_address_is_kept_beside_the_probe_address(client):
    opened, runtime = client

    opened.post(
        "/api/hub/proxy/balancer/set",
        json=dict(BALANCER, reference_url="http://example.net/probe"),
    )

    balancer = runtime.files["xray/nodes.json"]["balancer"]
    assert balancer["reference_url"] == "http://example.net/probe"
    assert balancer["probe_url"] == BALANCER["probe_url"]
