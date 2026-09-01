"""Every shape a box can be, every switch between them, and the proxy in each.

network.md states what each mode is and what each transition costs; this file
holds a live box to it. The walk reaches every ordered pair of the three
modes, and inside router mode it visits the shapes that are wiring rather
than modes: the LAN on a VLAN tag of one wire, and more than one way out.

File order is run order, and the walk is one continuous story — a test picks
up the box exactly as the one before it left it. The box needs one interface
and proves more with three: the second becomes another uplink, the third a
network to serve. `setup_vms.sh` builds exactly that machine, with a client
VM on the served wire whose lease is the end-to-end signal that serving
works; set NEUTRINO_LAN_CLIENT=1 when one is listening.
"""

import os
import time
from pathlib import Path

import pytest

import machine_state

NODE_LINK = "ss://YWVzLTI1Ni1nY206c2VjcmV0@203.0.113.10:5800#matrix"  # scan: allow
LAN_ADDRESS = "192.168.90.1"
ONE_ARM_ADDRESS = "192.168.91.1"
ONE_ARM_TAG = 3
DNSMASQ_CONF = Path("/var/lib/neutrino/generated/dnsmasq_neutrino.conf")
XRAY_CONF = Path("/var/lib/neutrino/generated/xray_config.json")
LEASE_FILE = Path("/var/lib/misc/dnsmasq.leases")
STOOD_DOWN = Path("/var/lib/neutrino/stood_down.json")
SETTLE_LIMIT_S = 30.0
LEASE_LIMIT_S = 180.0


# --- reading the box ----------------------------------------------------------


def until(check, *, limit_s: float = SETTLE_LIMIT_S, message: str = "") -> None:
    """Wait for a condition that follows a unit restart or a lease."""
    deadline = time.monotonic() + limit_s
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(1.0)
    raise AssertionError(message or "did not settle in time")


def firewall() -> str:
    return machine_state.firewall_table()


def rules() -> str:
    return machine_state.run(["ip", "rule", "show"])


def addresses_on(device: str) -> str:
    return machine_state.run(["ip", "-4", "-o", "addr", "show", "dev", device])


def device_exists(device: str) -> bool:
    return bool(machine_state.run(["ip", "-o", "link", "show", "dev", device]).strip())


def dnsmasq_conf() -> str:
    return DNSMASQ_CONF.read_text(encoding="utf-8")


def masquerades_out_of(device: str) -> bool:
    """Whether the loaded table masquerades what leaves by this device.

    Read from `nft list` rather than from the render, so the spelling is the
    kernel's: a one-element set comes back as a bare name, not `{ "x" }`.
    """
    return any(
        "masquerade" in line and f'"{device}"' in line
        for line in firewall().splitlines()
    )


# --- driving the panel --------------------------------------------------------


def put_mode(panel, mode: str) -> None:
    status, answer = panel.call("PUT", "/network/mode", {"mode": mode})
    assert status == 200, answer


def settings_of(panel, name: str) -> dict:
    for entry in panel.read("/network")["interfaces"]:
        if entry["settings"]["name"] == name:
            return entry["settings"]
    raise AssertionError(f"{name} is not on the network page")


def put_interface(panel, name: str, **changes) -> None:
    body = settings_of(panel, name)
    for key, value in changes.items():
        if isinstance(value, dict) and isinstance(body.get(key), dict):
            body[key] = {**body[key], **value}
        else:
            body[key] = value
    status, answer = panel.call("PUT", f"/network/interfaces/{name}", body)
    assert status == 200, answer


def put_options(panel, **changes) -> None:
    view = panel.read("/network")
    body = {
        "uplink_policy": view["uplink_policy"],
        "is_inter_lan_allowed": view["is_inter_lan_allowed"],
        "exposed_interfaces": [
            entry["settings"]["name"]
            for entry in view["interfaces"]
            if entry["settings"]["is_exposed"]
        ],
    }
    body.update(changes)
    status, answer = panel.call("PUT", "/network", body)
    assert status == 200, answer


def put_proxy(panel, **changes) -> None:
    body = dict(panel.read("/proxy"))
    body.update(changes)
    status, answer = panel.call("PUT", "/proxy", body)
    assert status == 200, answer
    status, answer = panel.call("POST", "/proxy/apply")
    assert status == 200, answer
    assert answer.get("is_applied"), answer


def lan_body(address: str) -> dict:
    prefix = address.rsplit(".", 1)[0]
    return {
        "address": address,
        "prefix_len": 24,
        "is_dhcp_enabled": True,
        "dhcp_range_start": f"{prefix}.100",
        "dhcp_range_end": f"{prefix}.200",
        "dhcp_lease_time": "12h",
        "upstream_gateway": None,
    }


def vlan_lan_body(parent: str, tag: int, address: str) -> dict:
    return {
        "name": f"{parent}.{tag}",
        "role": "lan",
        "is_exposed": True,
        "wan": {
            "method": "dhcp",
            "address": None,
            "prefix_len": 24,
            "gateway": None,
            "intent": "auto",
            "cloned_mac": None,
        },
        "lan": lan_body(address),
        "wifi": {"ssid": "", "ap_ssid": "", "ap_passphrase": "", "ap_band": "bg"},
        "vlan": {"parent": parent, "id": tag},
    }


# --- the wiring this box offers ----------------------------------------------


@pytest.fixture(scope="module")
def wiring(panel, before) -> dict:
    """Which port is the way in, and what the spare ports are for.

    The way in keeps carrying the panel session; the first spare becomes the
    second uplink and the last one the served network, which is the order
    `setup_vms.sh` wires them in. Override with NEUTRINO_WAN2_PORT and
    NEUTRINO_LAN_PORT when the wiring is anything else.
    """
    physical = [
        entry["settings"]["name"]
        for entry in panel.read("/network")["interfaces"]
        if entry["link"]["is_present"]
        and entry["settings"]["vlan"] is None
        and entry["link"]["kind"] == "ethernet"
    ]
    way_in = before["interface"]
    spares = [name for name in physical if name != way_in]
    return {
        "way_in": way_in,
        "wan2": os.environ.get("NEUTRINO_WAN2_PORT")
        or (spares[0] if len(spares) > 1 else None),
        "lan": os.environ.get("NEUTRINO_LAN_PORT") or (spares[-1] if spares else None),
        "manager": before["manager"],
    }


# --- a server, and its proxy --------------------------------------------------


def test_the_box_arrives_a_server(panel, wiring):
    assert panel.read("/network")["mode"] == "server"
    assert "policy accept" in machine_state.run(
        ["nft", "list", "chain", "inet", "neutrino", "forward"]
    )
    assert "masquerade" not in firewall()
    assert "tproxy" not in firewall()
    assert "fwmark" not in rules()
    assert machine_state.is_active(wiring["manager"])


def test_a_server_proxies_its_ports_and_itself(panel):
    """The scopes that do not need a forwarded network work without one."""
    if not panel.read("/proxy/nodes")["nodes"]:
        assert panel.status("POST", "/proxy/nodes", {"link": NODE_LINK}) == 201
    put_proxy(
        panel,
        is_local_proxy_enabled=True,
        socks_ports=[{"port": 1091, "is_proxied": True}],
    )

    body = firewall()
    assert 'iifname "lo"' in body and "tproxy" in body
    assert "fwmark" in rules()
    assert "socks_1091_in" in XRAY_CONF.read_text(encoding="utf-8")
    # No network is forwarded, so nothing but loopback is diverted.
    assert "iifname !=" not in body


def test_the_lan_switch_does_nothing_on_a_server(panel):
    """It is the person's switch and it survives; what it does follows the
    mode, and a server has no LAN for it to mean anything on."""
    put_proxy(panel, is_proxy_enabled=True)

    assert "iifname !=" not in firewall()
    assert panel.read("/proxy")["is_proxy_enabled"]


def test_a_server_can_put_its_proxy_away(panel):
    put_proxy(
        panel,
        is_proxy_enabled=False,
        is_local_proxy_enabled=False,
        socks_ports=[],
    )

    assert "tproxy" not in firewall()
    assert "fwmark" not in rules()


# --- server -> side gateway ---------------------------------------------------


def test_a_server_becomes_a_side_gateway(panel, wiring):
    put_mode(panel, "side_gateway")

    view = panel.read("/network")
    joined = settings_of(panel, wiring["way_in"])
    assert view["mode"] == "side_gateway"
    assert joined["role"] == "lan"
    assert joined["lan"]["upstream_gateway"]
    assert machine_state.run(["sysctl", "-n", "net.ipv4.ip_forward"]).strip() == "1"
    assert "masquerade" in firewall()
    # Addressing stays the machine's own: nothing was stood down.
    assert machine_state.is_active(wiring["manager"])
    assert not STOOD_DOWN.exists()


def test_a_side_gateway_diverts_the_network_it_joined(panel, wiring):
    put_proxy(panel, is_proxy_enabled=True)
    assert f'"{wiring["way_in"]}"' in firewall()
    assert "tproxy" in firewall()

    put_proxy(panel, is_proxy_enabled=False)
    assert "tproxy" not in firewall()


# --- side gateway -> router ---------------------------------------------------


def test_a_side_gateway_becomes_a_router(panel, wiring):
    put_mode(panel, "router")
    put_interface(panel, wiring["way_in"], role="wan", lan={"upstream_gateway": None})

    until(
        lambda: not machine_state.is_active(wiring["manager"]),
        message="the machine's own manager was never stood down",
    )
    assert STOOD_DOWN.exists()
    until(
        lambda: "/" in addresses_on(wiring["way_in"]),
        message="the uplink never took a lease under the hub's client",
    )


def test_the_router_serves_a_network(panel, wiring):
    if wiring["lan"] is None:
        pytest.skip("this box has no spare port to serve on")
    put_interface(panel, wiring["lan"], role="lan", lan=lan_body(LAN_ADDRESS))

    assert LAN_ADDRESS in addresses_on(wiring["lan"])
    assert f'interface={wiring["lan"]}' in dnsmasq_conf()
    assert "dhcp-range=" in dnsmasq_conf()
    assert masquerades_out_of(wiring["way_in"])
    assert "policy drop" in machine_state.run(
        ["nft", "list", "chain", "inet", "neutrino", "forward"]
    )
    until(
        lambda: LAN_ADDRESS in machine_state.resolv_conf(),
        message="the box never came to resolve at its own dnsmasq",
    )


def test_a_client_on_the_served_wire_takes_a_lease(wiring):
    """The end-to-end signal that serving works: a machine nobody configured
    asks on the wire and is answered."""
    if os.environ.get("NEUTRINO_LAN_CLIENT") != "1":
        pytest.skip("no client VM is listening on the served wire")

    def leased() -> bool:
        try:
            return LAN_ADDRESS.rsplit(".", 1)[0] in LEASE_FILE.read_text(
                encoding="utf-8"
            )
        except OSError:
            return False

    until(leased, limit_s=LEASE_LIMIT_S, message="no lease was ever handed out")


def test_the_router_diverts_its_lan_and_itself(panel, wiring):
    if wiring["lan"] is None:
        pytest.skip("this box serves no network to divert")
    put_proxy(panel, is_proxy_enabled=True, is_local_proxy_enabled=True)

    body = firewall()
    assert "tproxy" in body and 'iifname "lo"' in body
    assert f'"{wiring["lan"]}"' in body
    assert "server=127.0.0.1#15353" in dnsmasq_conf()

    put_proxy(panel, is_proxy_enabled=False, is_local_proxy_enabled=False)
    assert "tproxy" not in firewall()
    assert "server=127.0.0.1#15353" not in dnsmasq_conf()

    # Left on for the rest of the walk: what the modes after this do to a
    # diversion nobody switches off again is the thing worth watching.
    put_proxy(panel, is_proxy_enabled=True)
    assert "tproxy" in firewall()


# --- router, one wire ---------------------------------------------------------


def test_the_lan_moves_onto_a_tag(panel, wiring):
    """One-arm: the way in becomes a trunk, going out untagged and serving on
    a tag carved from the same wire."""
    if wiring["lan"] is not None:
        put_interface(panel, wiring["lan"], role="disabled")
    put_interface(panel, wiring["way_in"], role="split")
    name = f'{wiring["way_in"]}.{ONE_ARM_TAG}'
    status, answer = panel.call(
        "PUT",
        f"/network/interfaces/{name}",
        vlan_lan_body(wiring["way_in"], ONE_ARM_TAG, ONE_ARM_ADDRESS),
    )
    assert status == 200, answer
    view = panel.read("/network")
    exposed = [
        entry["settings"]["name"]
        for entry in view["interfaces"]
        if entry["settings"]["is_exposed"]
    ]
    if name not in exposed:
        put_options(panel, exposed_interfaces=exposed + [name])

    assert device_exists(name)
    assert ONE_ARM_ADDRESS in addresses_on(name)
    assert f"interface={name}" in dnsmasq_conf()
    assert masquerades_out_of(wiring["way_in"])
    # The trunk's untagged traffic is still the way out.
    assert "/" in addresses_on(wiring["way_in"])


def test_the_tag_hands_back_to_two_arms(panel, wiring):
    put_interface(panel, wiring["way_in"], role="wan")

    name = f'{wiring["way_in"]}.{ONE_ARM_TAG}'
    assert not device_exists(name)
    assert all(
        entry["settings"]["name"] != name
        for entry in panel.read("/network")["interfaces"]
    )
    if wiring["lan"] is not None:
        put_interface(panel, wiring["lan"], role="lan", lan=lan_body(LAN_ADDRESS))
        assert f'interface={wiring["lan"]}' in dnsmasq_conf()


# --- router, several ways out -------------------------------------------------


def test_a_second_way_out_joins_and_balances(panel, wiring):
    if wiring["wan2"] is None:
        pytest.skip("this box has no spare port for a second uplink")
    put_interface(panel, wiring["wan2"], role="wan")
    until(
        lambda: "/" in addresses_on(wiring["wan2"]),
        message="the second uplink never took a lease",
    )
    lines = panel.read("/network")["lines"]
    assert len(lines) == 2

    put_options(panel, uplink_policy="balance")
    until(
        lambda: "nexthop"
        in machine_state.run(["ip", "-4", "route", "show", "default"]),
        message="balancing never installed the multipath route",
    )

    put_interface(panel, wiring["wan2"], wan={"intent": "backup_only"})
    until(
        lambda: "nexthop"
        not in machine_state.run(["ip", "-4", "route", "show", "default"]),
        message="a backup uplink was left inside the multipath route",
    )

    put_options(panel, uplink_policy="failover")
    put_interface(panel, wiring["wan2"], role="disabled", wan={"intent": "auto"})
    assert "/" not in addresses_on(wiring["wan2"])


# --- router -> server ---------------------------------------------------------


def test_the_router_hands_back_to_a_server(panel, wiring):
    put_mode(panel, "server")

    until(
        lambda: machine_state.is_active(wiring["manager"]),
        message="the machine's own manager was never started again",
    )
    assert not STOOD_DOWN.exists()
    body = firewall()
    assert "masquerade" not in body
    assert "tproxy" not in body
    assert "fwmark" not in rules()
    # No address is taken off anything: the way in is still addressed.
    assert "/" in addresses_on(wiring["way_in"])
    assert LAN_ADDRESS not in machine_state.resolv_conf()
    assert "policy accept" in machine_state.run(
        ["nft", "list", "chain", "inet", "neutrino", "forward"]
    )


def test_the_diversion_follows_the_mode_with_nothing_retyped(panel):
    """Nobody has touched the Proxy page since the router served a network.

    The switch is the person's answer and it survives; what it does is the
    mode's, and a server forwards nobody — so the diversion is gone from the
    kernel while the answer is still on the page.
    """
    assert panel.read("/proxy")["is_proxy_enabled"]
    assert "tproxy" not in firewall()


# --- server -> router ---------------------------------------------------------


def test_a_server_takes_the_stack_straight_back(panel, wiring):
    put_mode(panel, "router")
    put_interface(panel, wiring["way_in"], role="wan")

    until(
        lambda: not machine_state.is_active(wiring["manager"]),
        message="taking the stack back never stood the manager down",
    )
    until(
        lambda: "/" in addresses_on(wiring["way_in"]),
        message="the uplink never took a lease on the way back in",
    )


# --- router -> side gateway ---------------------------------------------------


def test_the_router_becomes_a_side_gateway(panel, wiring):
    put_mode(panel, "side_gateway")

    until(
        lambda: machine_state.is_active(wiring["manager"]),
        message="the hand-back never started the manager again",
    )
    joined = settings_of(panel, wiring["way_in"])
    assert joined["role"] == "lan"
    assert joined["lan"]["upstream_gateway"]
    assert "masquerade" in firewall()


def test_the_diversion_comes_back_with_the_network_to_divert(panel):
    """The other half of it: a mode that forwards again is a mode where the
    switch means something, and the mode's own apply is what puts the rules
    back — no visit to the Proxy page, no second Apply."""
    assert panel.read("/proxy")["is_proxy_enabled"]
    assert "tproxy" in firewall()


# --- side gateway -> server ---------------------------------------------------


def test_the_side_gateway_returns_to_a_server(panel, wiring):
    put_mode(panel, "server")

    assert panel.read("/network")["mode"] == "server"
    assert settings_of(panel, wiring["way_in"])["role"] == "disabled"
    assert "masquerade" not in firewall()
    assert machine_state.is_active(wiring["manager"])
    # The proxy's answers survived the whole walk.
    assert panel.status("GET", "/proxy") == 200
    status, answer = panel.call("POST", "/proxy/apply")
    assert status == 200 and answer.get("is_applied"), answer
