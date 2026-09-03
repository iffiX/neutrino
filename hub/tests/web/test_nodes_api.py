"""What the exit-node list does to the proxy switch.

The pairing these guard: a proxy that is on and a list with nothing enabled in
it is not a state — the balancer has nothing to select, so rendering the xray
configuration raises and every Apply after it fails with that. The panel used
to let somebody reach it by deleting the last node, and then offered no way
out: the one thing that fixes it is the switch the page never mentioned.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.xray.node_config import XrayNodeList
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers import nodes as nodes_router
from neutrino_hub.web.routers import proxy as proxy_router
from tests.conftest import unlock_vault

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
        "strategy": "leastPing",
        "probe_url": "https://www.gstatic.com/generate_204",
        "probe_interval_s": 60,
    },
}


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
        self.node_probe = _NoProbes()
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


class _NoProbes:
    def results(self, nodes) -> list:
        return []


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

    response = opened.delete("/api/proxy/nodes/hk1")

    assert response.status_code == 200
    assert not is_proxy_on(runtime)


def test_disabling_the_last_node_switches_the_proxy_off(client):
    """The same state reached by the other door. It used to be refused here
    and allowed there, which is one rule with two answers."""
    opened, runtime = client

    response = opened.put("/api/proxy/nodes/hk1", json={"is_enabled": False})

    assert response.status_code == 200
    assert not is_proxy_on(runtime)


def test_a_node_that_stays_leaves_the_switch_alone(client):
    opened, runtime = client
    opened.post("/api/proxy/nodes", json={"link": SHARE_LINK.replace("hk1", "hk2")})

    opened.delete("/api/proxy/nodes/hk1")

    assert is_proxy_on(runtime)


def test_adding_a_node_does_not_switch_the_proxy_back_on(client):
    """It is the person's switch. Emptying the list is what turns it off,
    because that state cannot be rendered; filling it again is not consent to
    start proxying."""
    opened, runtime = client
    opened.delete("/api/proxy/nodes/hk1")

    opened.post("/api/proxy/nodes", json={"link": SHARE_LINK})

    assert not is_proxy_on(runtime)


def test_the_switch_cannot_be_turned_on_with_nothing_to_go_out_through(client):
    opened, runtime = client
    opened.delete("/api/proxy/nodes/hk1")
    settings = dict(runtime.files["xray/routing.json"], is_proxy_enabled=True)

    response = opened.put("/api/proxy", json=settings)

    assert response.status_code == 400
    assert "exit node" in response.json()["detail"]


def test_two_listeners_cannot_share_a_port(client):
    opened, runtime = client
    settings = dict(
        runtime.files["xray/routing.json"],
        socks_ports=[
            {"port": 1080, "is_proxied": False},
            {"port": 1080, "is_proxied": True},
        ],
    )

    response = opened.put("/api/proxy", json=settings)

    assert response.status_code == 400


@pytest.mark.parametrize("port", [0, -1, 65536])
def test_a_port_no_listener_can_take_is_refused(client, port):
    opened, runtime = client
    settings = dict(
        runtime.files["xray/routing.json"],
        socks_ports=[{"port": port, "is_proxied": False}],
    )

    response = opened.put("/api/proxy", json=settings)

    assert response.status_code == 400


@pytest.mark.parametrize(
    "settings,label",
    [
        ({"probe_interval_s": 0}, "a probe interval of zero"),
        ({"probe_interval_s": -60}, "a probe interval running backwards"),
        ({"probe_interval_s": 999999}, "a probe interval of days"),
        ({"probe_url": "not a url"}, "a probe target that is not a URL"),
        ({"probe_url": ""}, "no probe target at all"),
    ],
)
def test_the_balancer_refuses_what_the_observatory_cannot_keep(client, settings, label):
    """These reach xray's observatory, which fails at run time rather than at
    load time: a bad one is a proxy that starts and then never picks a node."""
    opened, _ = client
    body = {
        "strategy": "leastPing",
        "probe_url": "https://www.gstatic.com/generate_204",
        "probe_interval_s": 60,
    }
    body.update(settings)

    response = opened.put("/api/proxy/balancer", json=body)

    assert response.status_code == 400, label


def test_many_listeners_are_kept_in_the_order_they_were_given(client):
    """Adding a row at a time is how the page works, and a list that reorders
    itself under that is one nobody can edit."""
    opened, runtime = client
    ports = [
        {"port": 2000 + index, "is_proxied": index % 2 == 0} for index in range(32)
    ]
    settings = dict(runtime.files["xray/routing.json"], socks_ports=ports)

    response = opened.put("/api/proxy", json=settings)

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

    response = opened.put(
        "/api/proxy", json=dict(runtime.files["xray/routing.json"], direct_dns=resolver)
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

    response = opened.put("/api/proxy", json=settings)

    assert response.status_code == 400


def test_a_direct_list_of_prefixes_and_databases_is_kept(client):
    opened, runtime = client
    settings = dict(
        runtime.files["xray/routing.json"],
        direct_ips=["192.0.2.0/24", "geoip:cn"],
        direct_domains=["geosite:cn", "example.com"],
    )

    response = opened.put("/api/proxy", json=settings)

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

    response = opened.put("/api/proxy", json=settings)

    assert response.status_code == 400
    assert "8080" in response.json()["detail"]


def test_a_free_port_is_still_accepted(client):
    opened, runtime = client
    settings = dict(
        runtime.files["xray/routing.json"],
        socks_ports=[{"port": 1080, "is_proxied": False}],
    )

    assert opened.put("/api/proxy", json=settings).status_code == 200


def test_a_proxied_listener_needs_no_exit_node_to_be_saved(client):
    """It is a listener waiting for a node, not a contradiction: the renderer
    declines to publish it while there is nothing to go out through, so the
    page has nothing to refuse."""
    opened, runtime = client
    opened.delete("/api/proxy/nodes/hk1")
    settings = dict(
        runtime.files["xray/routing.json"],
        socks_ports=[{"port": 1081, "is_proxied": True}],
    )

    response = opened.put("/api/proxy", json=settings)

    assert response.status_code == 200


def test_the_hubs_own_switch_cannot_be_turned_on_with_nothing_to_go_out_through(client):
    """It diverts, so it needs somewhere for what it diverts to go."""
    opened, runtime = client
    opened.delete("/api/proxy/nodes/hk1")
    settings = dict(runtime.files["xray/routing.json"], is_local_proxy_enabled=True)

    response = opened.put("/api/proxy", json=settings)

    assert response.status_code == 400
    assert "exit node" in response.json()["detail"]


def test_an_added_link_seals_its_secret_and_stores_the_reference(client):
    opened, runtime = client

    response = opened.post(
        "/api/proxy/nodes", json={"link": SHARE_LINK.replace("hk1", "hk2")}
    )

    assert response.status_code == 201
    stored = runtime.files["xray/nodes.json"]["nodes"][-1]
    assert stored["secret_id"]
    assert "password" not in stored["shadowsocks"]
    from neutrino_hub.modules.credentials.vault import SecretVault

    assert SecretVault().open(stored["secret_id"]) == {"value": "secret"}


def test_removing_a_node_takes_its_vault_object_with_it(client):
    opened, runtime = client
    opened.post("/api/proxy/nodes", json={"link": SHARE_LINK.replace("hk1", "hk2")})
    stored = runtime.files["xray/nodes.json"]["nodes"][-1]

    opened.delete(f"/api/proxy/nodes/{stored['id']}")

    from neutrino_hub.modules.credentials.vault import SecretVault

    assert SecretVault().get(stored["secret_id"]) is None
