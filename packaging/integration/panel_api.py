#!/usr/bin/env python3
"""Drive the panel's API the way a person drives the panel, and check what it does.

    panel_api.py <password> [section ...]

Run on the machine under test, as any user that can reach the panel on
loopback. It signs in, walks every operation each page offers — including the
edges nobody presses on purpose: deleting the last of something, adding far
more than anybody would, and sequences that leave one page's state stale in
another — and prints `ok` or `FAIL` per check. The exit status is the number
that failed.

Not a pytest suite, and deliberately outside `hub/tests`: every check here
needs a machine with the hub installed and running on it, which is what
`packaging/integration/` holds. The two shell matrices beside it prove the
install; this proves the panel on top of one.

Sections are independent and named on the command line. `network` reconfigures
the machine's interfaces and `services` installs nothing, so a run that is
interrupted leaves the box in whatever state the last applied step reached.
"""

import json
import sys
import time
import urllib.error
import urllib.request
from http.cookiejar import CookieJar

PANEL = "http://127.0.0.1:8080"
# How long a call that reconfigures the machine gets before it is a failure.
# Applying a mode rewrites the firewall and restarts dnsmasq; it is not fast.
TIMEOUT_S = 90

failures = 0
opener = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(CookieJar())
)


def call(method: str, path: str, body=None) -> tuple:
    """One API call.

    Args:
        method: HTTP method.
        path: Path under /api.
        body: Object to send as JSON, or None.

    Returns:
        The status code and the decoded answer, which is the error detail for
        a failure and None for an empty body.
    """
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        f"{PANEL}/api{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with opener.open(request, timeout=TIMEOUT_S) as answer:
            text = answer.read().decode()
            return answer.status, (json.loads(text) if text else None)
    except urllib.error.HTTPError as error:
        text = error.read().decode()
        try:
            return error.code, json.loads(text)
        except ValueError:
            return error.code, text
    except Exception as error:  # noqa: BLE001 - a dead socket is a result too
        return 0, str(error)


def check(name: str, got, want) -> None:
    global failures
    if got == want:
        print(f"  ok    {name:<52} {got}")
    else:
        print(f"  FAIL  {name:<52} got {got!r}, wanted {want!r}")
        failures += 1
    sys.stdout.flush()


def check_status(name: str, method: str, path: str, body, want: int):
    """One call, checked on its status alone.

    Returns:
        The answer, so a caller can look at what came back.
    """
    status, answer = call(method, path, body)
    check(name, status, want)
    return answer


def note(name: str, value) -> None:
    print(f"  --    {name:<52} {value}")
    sys.stdout.flush()


def section(title: str) -> None:
    print(f"\n== {title} ==")
    sys.stdout.flush()


# --- network -----------------------------------------------------------------


def network_section() -> None:
    """Every operation the Network page offers, and the edges around them."""
    section("network: what the page is drawn from")
    view = check_status("read", "GET", "/network", None, 200)
    if not isinstance(view, dict):
        return
    ports = [entry["settings"]["name"] for entry in view["interfaces"]]
    note("mode", view["mode"])
    note("interfaces", " ".join(ports))
    check(
        "every mode is offered",
        [mode["key"] for mode in view["modes"]],
        ["server", "side_gateway", "router"],
    )

    section("network: exposure")
    _exposure_cases(ports)

    section("network: the mode switch")
    _mode_cases(ports)

    section("network: one interface at a time")
    _interface_cases(ports)

    section("network: VLANs on a trunk")
    _vlan_cases(ports)

    section("network: the panel's own port")
    _panel_port_cases()


def options_body(**over) -> dict:
    _, view = call("GET", "/network")
    body = {
        "uplink_policy": view["uplink_policy"],
        "is_inter_lan_allowed": view["is_inter_lan_allowed"],
        "exposed_interfaces": [
            entry["settings"]["name"]
            for entry in view["interfaces"]
            if entry["settings"]["is_exposed"]
        ],
    }
    body.update(over)
    return body


def exposed_now() -> list:
    _, view = call("GET", "/network")
    return sorted(
        entry["settings"]["name"]
        for entry in view["interfaces"]
        if entry["settings"]["is_exposed"]
    )


def _exposure_cases(ports: list) -> None:
    check_status(
        "an interface this machine lacks is refused",
        "PUT",
        "/network",
        options_body(exposed_interfaces=["enp9s9"]),
        400,
    )
    check_status(
        "an unknown uplink policy is refused",
        "PUT",
        "/network",
        options_body(uplink_policy="round_robin"),
        400,
    )
    check_status(
        "every interface at once",
        "PUT",
        "/network",
        options_body(exposed_interfaces=ports),
        200,
    )
    check("all of them answer", exposed_now(), sorted(ports))
    check_status(
        "the same interface named twice",
        "PUT",
        "/network",
        options_body(exposed_interfaces=[ports[0], ports[0]]),
        200,
    )
    check("naming it twice exposes it once", exposed_now(), [ports[0]])
    check_status(
        "closing every interface",
        "PUT",
        "/network",
        options_body(exposed_interfaces=[]),
        200,
    )
    check("nothing answers on a wire", exposed_now(), [])
    # Put the machine back where it can be reached before moving on.
    call("PUT", "/network", options_body(exposed_interfaces=ports))


def _mode_cases(ports: list) -> None:
    _clean_slate(ports)
    # From a known shape, so the walk below means the same thing whatever the
    # machine was left as. Applying the mode it is already in is a no-op by
    # design — the panel cannot press Apply on an unchanged box — so a run
    # starting in the mode it wants to test would test nothing.
    call("PUT", "/network/mode", {"mode": "server"})
    for mode in ("side_gateway", "router", "server"):
        check_status(f"become a {mode}", "PUT", "/network/mode", {"mode": mode}, 200)
        _, view = call("GET", "/network")
        check(f"{mode} is what it is now", view["mode"], mode)
        if mode == "server":
            check(
                "a server holds no role",
                sorted(
                    {entry["settings"]["role"] for entry in view["interfaces"]}
                ),
                ["disabled"],
            )
        if mode == "side_gateway":
            joined = [
                entry
                for entry in view["interfaces"]
                if entry["settings"]["role"] == "lan"
            ]
            check("a side gateway joins one network", len(joined), 1)
            stored = joined[0]["settings"]["lan"]["address"]
            live = (joined[0]["link"]["ipv4_address"] or "").split("/")[0]
            check("and it holds the address it already had", stored, live)
    check_status(
        "a mode that is not one of them",
        "PUT",
        "/network/mode",
        {"mode": "one_arm_router"},
        400,
    )
    check_status(
        "the mode it is already in",
        "PUT",
        "/network/mode",
        {"mode": "server"},
        200,
    )


def interface_body(name: str, **over) -> dict:
    _, view = call("GET", "/network")
    for entry in view["interfaces"]:
        if entry["settings"]["name"] == name:
            body = dict(entry["settings"])
            for key, value in over.items():
                if isinstance(value, dict):
                    body[key] = dict(body.get(key, {}), **value)
                else:
                    body[key] = value
            return body
    return {}


def pristine(name: str) -> dict:
    """One interface as a machine that has never been configured has it."""
    return {
        "name": name,
        "role": "disabled",
        "is_exposed": False,
        "wan": {
            "method": "dhcp",
            "address": None,
            "prefix_len": 24,
            "gateway": None,
            "intent": "auto",
            "cloned_mac": None,
        },
        "lan": {
            "address": "",
            "prefix_len": 24,
            "is_dhcp_enabled": False,
            "dhcp_range_start": "",
            "dhcp_range_end": "",
            "dhcp_lease_time": "12h",
            "upstream_gateway": None,
        },
        "wifi": {"ssid": "", "ap_ssid": "", "ap_passphrase": "", "ap_band": "bg"},
        "vlan": None,
    }


def _clean_slate(ports: list) -> None:
    """Put every interface back to nothing before a section that checks one.

    A value refused today may already be stored from a run before it was
    refused, and a settings block is sent back whole — so one stale field
    fails every later save of that interface and every check after it reads as
    broken for the wrong reason.
    """
    call("PUT", "/network/mode", {"mode": "server"})
    for name in ports:
        call("PUT", f"/network/interfaces/{name}", pristine(name))


def _interface_cases(ports: list) -> None:
    _clean_slate(ports)
    check_status("become a router", "PUT", "/network/mode", {"mode": "router"}, 200)
    served = ports[-1]
    check_status(
        "a served network",
        "PUT",
        f"/network/interfaces/{served}",
        interface_body(
            served,
            role="lan",
            lan={
                "address": "192.168.77.1",
                "prefix_len": 24,
                "is_dhcp_enabled": True,
                "dhcp_range_start": "192.168.77.100",
                "dhcp_range_end": "192.168.77.200",
                "dhcp_lease_time": "12h",
                "upstream_gateway": None,
            },
        ),
        200,
    )
    for label, patch, want in (
        ("a prefix length of 0", {"lan": {"prefix_len": 0}}, 400),
        ("a prefix length of 33", {"lan": {"prefix_len": 33}}, 400),
        ("an address that is not one", {"lan": {"address": "not.an.address"}}, 400),
        (
            "a lease range outside the network",
            {"lan": {"dhcp_range_start": "10.9.9.1", "dhcp_range_end": "10.9.9.9"}},
            400,
        ),
        (
            "a lease range that runs backwards",
            {
                "lan": {
                    "dhcp_range_start": "192.168.77.200",
                    "dhcp_range_end": "192.168.77.100",
                }
            },
            400,
        ),
        (
            "the gateway inside its own lease range",
            {
                "lan": {
                    "dhcp_range_start": "192.168.77.1",
                    "dhcp_range_end": "192.168.77.200",
                }
            },
            400,
        ),
        (
            "an upstream router outside the network",
            {"lan": {"upstream_gateway": "10.0.0.1"}},
            400,
        ),
        (
            "an upstream router that is the box itself",
            {"lan": {"upstream_gateway": "192.168.77.1"}},
            400,
        ),
        ("a cloned MAC that is not a MAC", {"wan": {"cloned_mac": "hello"}}, 400),
        ("a lease time that is not one", {"lan": {"dhcp_lease_time": "forever"}}, 400),
        (
            "a lease time carrying a second directive",
            {"lan": {"dhcp_lease_time": "12h\nlog-queries=1"}},
            400,
        ),
    ):
        check_status(
            label, "PUT", f"/network/interfaces/{served}", interface_body(served, role="lan", **patch), want
        )
    check_status(
        "the name in the path and the body disagreeing",
        "PUT",
        f"/network/interfaces/{ports[0]}",
        interface_body(served),
        400,
    )
    check_status(
        "an interface this machine lacks",
        "PUT",
        "/network/interfaces/enp9s9",
        dict(interface_body(served), name="enp9s9"),
        400,
    )
    check_status(
        "removing a physical port",
        "DELETE",
        f"/network/interfaces/{served}",
        None,
        400,
    )
    check_status(
        "removing an interface that is not there",
        "DELETE",
        "/network/interfaces/enp9s9",
        None,
        404,
    )
    if len(ports) > 1:
        check_status(
            "a second network on a subnet the first already serves",
            "PUT",
            f"/network/interfaces/{ports[0]}",
            interface_body(
                ports[0],
                role="lan",
                lan={
                    "address": "192.168.77.9",
                    "prefix_len": 24,
                    "is_dhcp_enabled": False,
                    "dhcp_range_start": "",
                    "dhcp_range_end": "",
                    "dhcp_lease_time": "12h",
                    "upstream_gateway": None,
                },
            ),
            400,
        )


def _vlan_cases(ports: list) -> None:
    _clean_slate(ports)
    call("PUT", "/network/mode", {"mode": "router"})
    trunk = ports[-1]
    check_status(
        "split a port into a trunk",
        "PUT",
        f"/network/interfaces/{trunk}",
        interface_body(trunk, role="split"),
        200,
    )
    _, view = call("GET", "/network")
    mains = [
        entry["settings"]["name"]
        for entry in view["interfaces"]
        if entry["settings"].get("vlan") and entry["settings"]["vlan"]["id"] is None
    ]
    check("the untagged main appears with it", mains, [f"{trunk}.main"])
    for label, vlan_id, want in (
        ("a VLAN id of 0", 0, 400),
        ("a VLAN id of 4095", 4095, 400),
        ("a VLAN id of 1", 1, 200),
        ("a VLAN id of 4094", 4094, 200),
    ):
        check_status(
            label,
            "PUT",
            f"/network/interfaces/{trunk}.{vlan_id}",
            {
                "name": f"{trunk}.{vlan_id}",
                "role": "disabled",
                "is_exposed": False,
                "wan": {
                    "method": "dhcp",
                    "address": None,
                    "prefix_len": 24,
                    "gateway": None,
                    "intent": "auto",
                    "cloned_mac": None,
                },
                "lan": {
                    "address": "",
                    "prefix_len": 24,
                    "is_dhcp_enabled": False,
                    "dhcp_range_start": "",
                    "dhcp_range_end": "",
                    "dhcp_lease_time": "12h",
                    "upstream_gateway": None,
                },
                "wifi": {"ssid": "", "ap_ssid": "", "ap_passphrase": "", "ap_band": "bg"},
                "vlan": {"parent": trunk, "id": vlan_id},
            },
            want,
        )
    # Thirty of them, which nobody would type and the page allows.
    made = 0
    for vlan_id in range(100, 130):
        status, _ = call(
            "PUT",
            f"/network/interfaces/{trunk}.{vlan_id}",
            {
                "name": f"{trunk}.{vlan_id}",
                "role": "disabled",
                "is_exposed": False,
                "wan": {
                    "method": "dhcp",
                    "address": None,
                    "prefix_len": 24,
                    "gateway": None,
                    "intent": "auto",
                    "cloned_mac": None,
                },
                "lan": {
                    "address": "",
                    "prefix_len": 24,
                    "is_dhcp_enabled": False,
                    "dhcp_range_start": "",
                    "dhcp_range_end": "",
                    "dhcp_lease_time": "12h",
                    "upstream_gateway": None,
                },
                "wifi": {"ssid": "", "ap_ssid": "", "ap_passphrase": "", "ap_band": "bg"},
                "vlan": {"parent": trunk, "id": vlan_id},
            },
        )
        made += status == 200
    check("thirty VLANs on one trunk", made, 30)
    _, view = call("GET", "/network")
    devices = [
        entry["settings"]["name"]
        for entry in view["interfaces"]
        if entry["settings"].get("vlan")
    ]
    check("and every one of them is listed", len(devices), 33)
    # Exposure follows a VLAN that is removed: a name left in the set is one
    # the firewall would name and nft would refuse.
    call("PUT", "/network", options_body(exposed_interfaces=[f"{trunk}.1"]))
    check("a VLAN can be exposed", exposed_now(), [f"{trunk}.1"])
    check_status(
        "removing an exposed VLAN", "DELETE", f"/network/interfaces/{trunk}.1", None, 200
    )
    check("and it leaves the exposed set with it", exposed_now(), [])
    check_status(
        "removing the untagged main on its own",
        "DELETE",
        f"/network/interfaces/{trunk}.main",
        None,
        400,
    )
    check_status(
        "removing one VLAN", "DELETE", f"/network/interfaces/{trunk}.4094", None, 200
    )
    check_status(
        "leaving the trunk role",
        "PUT",
        f"/network/interfaces/{trunk}",
        interface_body(trunk, role="disabled"),
        200,
    )
    _, view = call("GET", "/network")
    left = [
        entry["settings"]["name"]
        for entry in view["interfaces"]
        if entry["settings"].get("vlan")
    ]
    check("and every VLAN on it goes with it", left, [])


def _panel_port_cases() -> None:
    settings = check_status("read the panel's port", "GET", "/settings", None, 200)
    if not isinstance(settings, dict):
        return
    note("panel port", settings["listen_port"])
    for label, port, want in (
        ("port 0", 0, 400),
        ("port 65536", 65536, 400),
        ("a negative port", -1, 400),
    ):
        check_status(label, "PUT", "/settings", {"listen_port": port}, want)
    check_status(
        "the port it is already on",
        "PUT",
        "/settings",
        {"listen_port": settings["listen_port"]},
        200,
    )


# --- proxy -------------------------------------------------------------------

# A node nobody can reach, which is what these need: the checks are about the
# list and the switch, never about traffic arriving anywhere.
SHARE_LINK = "ss://YWVzLTI1Ni1nY206c2VjcmV0@203.0.113.10:5800#audit"  # scan: allow
SECOND_LINK = "ss://YWVzLTI1Ni1nY206c2VjcmV0@203.0.113.11:5800#audit2"  # scan: allow


def proxy_section() -> None:
    section("proxy: what the page is drawn from")
    view = check_status("read", "GET", "/proxy", None, 200)
    nodes = check_status("read the nodes", "GET", "/proxy/nodes", None, 200)
    if not isinstance(view, dict) or not isinstance(nodes, dict):
        return
    note("proxy", "on" if view["is_proxy_enabled"] else "off")
    note("nodes", len(nodes["nodes"]))

    section("proxy: the exit-node list")
    _node_cases()

    section("proxy: the listeners")
    _socks_cases()

    section("proxy: the routing lists")
    _route_cases()


def routing_body(**over) -> dict:
    _, view = call("GET", "/proxy")
    body = dict(view)
    body.update(over)
    return body


def node_ids() -> list:
    _, view = call("GET", "/proxy/nodes")
    return [node["id"] for node in view["nodes"]]


def _node_cases() -> None:
    for node_id in node_ids():
        call("DELETE", f"/proxy/nodes/{node_id}")
    check("the list starts empty", node_ids(), [])
    check(
        "and the proxy is off with nothing to go out through",
        call("GET", "/proxy")[1]["is_proxy_enabled"],
        False,
    )
    check_status(
        "applying that state, which used to fail for ever",
        "POST",
        "/proxy/apply",
        None,
        200,
    )
    check_status(
        "the switch cannot be turned on with an empty list",
        "PUT",
        "/proxy",
        routing_body(is_proxy_enabled=True),
        400,
    )
    check_status("a link that is not one", "POST", "/proxy/nodes", {"link": "hello"}, 400)
    check_status("an empty link", "POST", "/proxy/nodes", {"link": ""}, 400)
    added = check_status("add a node", "POST", "/proxy/nodes", {"link": SHARE_LINK}, 201)
    check_status(
        "the same link twice", "POST", "/proxy/nodes", {"link": SHARE_LINK}, 400
    )
    check_status("add a second", "POST", "/proxy/nodes", {"link": SECOND_LINK}, 201)
    check("both are in the list", len(node_ids()), 2)
    was_on = call("GET", "/proxy")[1]["is_proxy_enabled"]
    if isinstance(added, dict):
        check_status(
            "rename one",
            "PUT",
            f"/proxy/nodes/{added['id']}",
            {"name": "renamed"},
            200,
        )
        check_status(
            "disable one",
            "PUT",
            f"/proxy/nodes/{added['id']}",
            {"is_enabled": False},
            200,
        )
        check(
            "one of two disabled leaves the switch as it was",
            call("GET", "/proxy")[1]["is_proxy_enabled"],
            was_on,
        )
    check_status(
        "a node that is not there",
        "PUT",
        "/proxy/nodes/nosuchnode",
        {"is_enabled": True},
        404,
    )
    check_status(
        "removing a node that is not there",
        "DELETE",
        "/proxy/nodes/nosuchnode",
        None,
        404,
    )
    check_status(
        "an unknown balancer strategy",
        "PUT",
        "/proxy/balancer",
        {"strategy": "coin_flip", "probe_url": "https://example.com", "probe_interval_s": 60},
        400,
    )
    check_status(
        "a probe interval of zero",
        "PUT",
        "/proxy/balancer",
        {"strategy": "leastPing", "probe_url": "https://example.com", "probe_interval_s": 0},
        400,
    )
    for node_id in node_ids():
        call("DELETE", f"/proxy/nodes/{node_id}")
    check("emptying the list again", node_ids(), [])


def _socks_cases() -> None:
    check_status(
        "one direct listener",
        "PUT",
        "/proxy",
        routing_body(socks_ports=[{"port": 1080, "is_proxied": False}]),
        200,
    )
    check(
        "which is what comes back",
        call("GET", "/proxy")[1]["socks_ports"],
        [{"port": 1080, "is_proxied": False}],
    )
    check_status(
        "two listeners on one port",
        "PUT",
        "/proxy",
        routing_body(
            socks_ports=[
                {"port": 1080, "is_proxied": False},
                {"port": 1080, "is_proxied": True},
            ]
        ),
        400,
    )
    check_status(
        "a port no listener can take",
        "PUT",
        "/proxy",
        routing_body(socks_ports=[{"port": 0, "is_proxied": False}]),
        400,
    )
    check_status(
        "a proxied listener with the proxy off",
        "PUT",
        "/proxy",
        routing_body(socks_ports=[{"port": 1081, "is_proxied": True}]),
        200,
    )
    check_status(
        "thirty listeners",
        "PUT",
        "/proxy",
        routing_body(
            socks_ports=[
                {"port": 2000 + index, "is_proxied": index % 2 == 0}
                for index in range(30)
            ]
        ),
        200,
    )
    check("all thirty are kept", len(call("GET", "/proxy")[1]["socks_ports"]), 30)
    check_status(
        "and none at all",
        "PUT",
        "/proxy",
        routing_body(socks_ports=[]),
        200,
    )
    check("which leaves nothing listening", call("GET", "/proxy")[1]["socks_ports"], [])


def _route_cases() -> None:
    check_status(
        "a thousand direct domains",
        "PUT",
        "/proxy",
        routing_body(direct_domains=[f"domain:host{index}.example" for index in range(1000)]),
        200,
    )
    check(
        "all of them are kept",
        len(call("GET", "/proxy")[1]["direct_domains"]),
        1000,
    )
    check_status(
        "an empty direct list",
        "PUT",
        "/proxy",
        routing_body(direct_domains=[], direct_ips=[]),
        200,
    )
    check_status(
        "a resolver that is not an address",
        "PUT",
        "/proxy",
        routing_body(direct_dns={"address": "not.an.address", "port": 53}),
        400,
    )
    check_status(
        "a resolver port of zero",
        "PUT",
        "/proxy",
        routing_body(direct_dns={"address": "223.5.5.5", "port": 0}),
        400,
    )
    check_status(
        "applying with nothing to apply",
        "POST",
        "/proxy/apply",
        None,
        200,
    )


# --- services ----------------------------------------------------------------


def services_section() -> None:
    section("services: what the page is drawn from")
    view = check_status("read", "GET", "/services", None, 200)
    if not isinstance(view, dict):
        return
    for entry in view["services"]:
        note(
            entry["name"],
            f"installed={entry['is_installed']} active={entry['is_active']} "
            f"core={entry.get('is_core')}",
        )
    optional = [entry for entry in view["services"] if not entry.get("is_core")]
    absent = [entry for entry in optional if not entry["is_installed"]]
    check("a fresh box has installed no optional module", len(absent), len(optional))

    section("services: acting on them")
    if absent:
        name = absent[0]["name"]
        check_status(
            f"enabling {name}, which is not installed",
            "POST",
            f"/services/{name}/action",
            {"action": "enable"},
            400,
        )
        check_status(
            f"starting {name}, which is not installed",
            "POST",
            f"/services/{name}/action",
            {"action": "start"},
            400,
        )
    check_status(
        "stopping a core unit",
        "POST",
        "/services/router/action",
        {"action": "stop"},
        400,
    )
    check_status(
        "disabling a core unit",
        "POST",
        "/services/web/action",
        {"action": "disable"},
        400,
    )
    check_status(
        "an action that is not one",
        "POST",
        "/services/router/action",
        {"action": "sing"},
        400,
    )
    check_status(
        "a service that is not one",
        "POST",
        "/services/nosuchmodule/action",
        {"action": "start"},
        404,
    )
    check_status(
        "the journal of a unit that is not installed",
        "GET",
        "/services/netbird/journal",
        None,
        200,
    )
    check_status(
        "the install plan of a module",
        "GET",
        "/services/samba/install_plan",
        None,
        200,
    )
    check_status(
        "the install plan of a module that is not one",
        "GET",
        "/services/nosuchmodule/install_plan",
        None,
        404,
    )


# --- devices -----------------------------------------------------------------


def devices_section() -> None:
    section("devices: what the page is drawn from")
    view = check_status("read", "GET", "/devices", None, 200)
    if not isinstance(view, dict):
        return
    note("devices", len(view["devices"]))

    section("devices: adding and forgetting")
    mac = "52:54:00:aa:bb:cc"
    check_status("add one", "PUT", f"/devices/{mac}", {"name": "audit"}, 200)
    check_status(
        "the same address again, which is how it is renamed",
        "PUT",
        f"/devices/{mac}",
        {"name": "renamed"},
        200,
    )
    _, view = call("GET", "/devices")
    stored = [entry for entry in view["devices"] if entry["mac_address"] == mac]
    check("one record, not two", len(stored), 1)
    check("and it took the new name", stored[0]["name"] if stored else None, "renamed")
    check_status(
        "the same address in capitals",
        "PUT",
        f"/devices/{mac.upper()}",
        {"name": "shouting"},
        200,
    )
    _, view = call("GET", "/devices")
    check(
        "which is the same device",
        len([e for e in view["devices"] if e["mac_address"] == mac]),
        1,
    )
    for label, address in (
        ("a name that is not an address", "hello"),
        ("an address one pair short", "52:54:00:aa:bb"),
        ("an address one pair long", "52:54:00:aa:bb:cc:dd"),
    ):
        check_status(label, "PUT", f"/devices/{address}", {"name": "no"}, 400)
    check_status(
        "an SSH key that is not stored",
        "PUT",
        f"/devices/{mac}",
        {"ssh": {"host": "10.0.0.5", "username": "me", "key_id": "nosuchkey"}},
        400,
    )
    check_status(
        "an action that is not one",
        "POST",
        f"/devices/{mac}/action",
        {"action": "sing"},
        400,
    )
    check_status(
        "installing the agent with no credentials",
        "POST",
        f"/devices/{mac}/action",
        {"action": "install_client"},
        409,
    )
    check_status("its features", "GET", f"/devices/{mac}/features", None, 200)
    features = call("GET", f"/devices/{mac}/features")[1]
    check("with no agent, none is online", features["is_agent_online"], False)
    section("devices: fifty of them")
    made = 0
    for index in range(50):
        code, _ = call(
            "PUT",
            f"/devices/52:54:00:00:{index // 16:02x}:{index % 16:02x}",
            {"name": f"crowd{index}"},
        )
        made += code == 200
    check("fifty devices", made, 50)
    _, view = call("GET", "/devices")
    crowd = [entry for entry in view["devices"] if entry["name"].startswith("crowd")]
    check("and every one is listed", len(crowd), 50)
    gone = 0
    for entry in crowd:
        code, _ = call("DELETE", f"/devices/{entry['mac_address']}")
        gone += code == 200
    check("forgetting all fifty", gone, 50)
    _, view = call("GET", "/devices")
    check(
        "leaves none of them",
        [e for e in view["devices"] if e["name"].startswith("crowd")],
        [],
    )

    section("devices: adding and forgetting")
    check_status("forget it", "DELETE", f"/devices/{mac}", None, 200)
    _, view = call("GET", "/devices")
    check(
        "and it is gone",
        [entry for entry in view["devices"] if entry["mac_address"] == mac],
        [],
    )


SECTIONS = {
    "network": network_section,
    "proxy": proxy_section,
    "services": services_section,
    "devices": devices_section,
}


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__.splitlines()[2].strip())
        return 2
    password = sys.argv[1]
    wanted = sys.argv[2:] or list(SECTIONS)

    status, answer = call("POST", "/auth/login", {"password": password})
    if status != 200 or not answer.get("is_authenticated"):
        print(f"  FAIL  could not sign in: {status} {answer}")
        return 1
    print(f"panel at {PANEL}, signed in")

    started = time.time()
    for name in wanted:
        if name not in SECTIONS:
            print(f"  FAIL  no section named {name!r}")
            return 1
        SECTIONS[name]()
    print(f"\n{failures} checks failed in {int(time.time() - started)}s")
    return failures


if __name__ == "__main__":
    sys.exit(main())
