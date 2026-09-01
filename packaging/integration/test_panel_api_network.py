"""Every operation the Network page offers, and the edges around them.

These run in file order and each starts from where the last left the box: a
mode is applied, then interfaces are configured inside it, then a trunk is
split. Applying the mode a box is already in is a no-op by design, so a check
that did not know what came before it would test nothing.

The machine's interfaces are whatever it has. Nothing here names one.
"""

import pytest

MODES = ["server", "side_gateway", "router"]
# A network no lab uses, so a served address cannot collide with the one this
# is being read over.
SERVED_CIDR = "192.168.77.1"
SERVED_RANGE = ("192.168.77.100", "192.168.77.200")
# More VLANs than anybody would type, on one trunk.
CROWD_VLAN_IDS = range(100, 130)


@pytest.fixture(scope="module")
def ports(panel) -> list:
    """The interfaces this machine has, in the order the panel lists them."""
    view = panel.read("/network")
    return [entry["settings"]["name"] for entry in view["interfaces"]]


def pristine(name: str) -> dict:
    """One interface as a machine that has never been configured has it.

    Args:
        name: The interface's name.

    Returns:
        The settings block, every field at its default.
    """
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


def options_body(panel, **over) -> dict:
    """The page-wide options as they are now, with some of them changed."""
    view = panel.read("/network")
    body = {
        "uplink_policy": view["uplink_policy"],
        "is_inter_lan_allowed": view["is_inter_lan_allowed"],
        "exposed_interfaces": exposed_now(panel),
    }
    body.update(over)
    return body


def interface_body(panel, name: str, **over) -> dict:
    """One interface's settings as they are now, with some of them changed."""
    for entry in panel.read("/network")["interfaces"]:
        if entry["settings"]["name"] != name:
            continue
        body = dict(entry["settings"])
        for key, value in over.items():
            body[key] = (
                dict(body.get(key) or {}, **value) if isinstance(value, dict) else value
            )
        return body
    return {}


def exposed_now(panel) -> list:
    """Which interfaces the firewall lets in, sorted."""
    return sorted(
        entry["settings"]["name"]
        for entry in panel.read("/network")["interfaces"]
        if entry["settings"]["is_exposed"]
    )


def vlan_names(panel) -> list:
    """Every interface that rides on a trunk."""
    return [
        entry["settings"]["name"]
        for entry in panel.read("/network")["interfaces"]
        if entry["settings"].get("vlan")
    ]


def vlan_body(trunk: str, vlan_id: int) -> dict:
    """A tagged interface on a trunk, at its defaults."""
    name = f"{trunk}.{vlan_id}"
    return dict(pristine(name), vlan={"parent": trunk, "id": vlan_id})


def clean_slate(panel, ports: list) -> None:
    """Put every interface back to nothing.

    A value refused today may already be stored from a run before it was
    refused, and a settings block is sent back whole — so one stale field fails
    every later save of that interface and every check after it reads as broken
    for the wrong reason.
    """
    panel.call("PUT", "/network/mode", {"mode": "server"})
    for name in ports:
        panel.call("PUT", f"/network/interfaces/{name}", pristine(name))


# --- what the page is drawn from ---------------------------------------------


def test_the_page_reads(panel):
    view = panel.read("/network")

    assert view["interfaces"], "a machine with no interfaces is not a gateway"


def test_every_mode_is_offered(panel):
    view = panel.read("/network")

    assert [mode["key"] for mode in view["modes"]] == MODES


# --- exposure -----------------------------------------------------------------


def test_an_interface_this_machine_lacks_is_refused(panel):
    body = options_body(panel, exposed_interfaces=["enp9s9"])

    assert panel.status("PUT", "/network", body) == 400


def test_an_unknown_uplink_policy_is_refused(panel):
    body = options_body(panel, uplink_policy="round_robin")

    assert panel.status("PUT", "/network", body) == 400


def test_every_interface_can_answer_at_once(panel, ports):
    body = options_body(panel, exposed_interfaces=ports)

    assert panel.status("PUT", "/network", body) == 200
    assert exposed_now(panel) == sorted(ports)


def test_naming_one_twice_exposes_it_once(panel, ports):
    body = options_body(panel, exposed_interfaces=[ports[0], ports[0]])

    assert panel.status("PUT", "/network", body) == 200
    assert exposed_now(panel) == [ports[0]]


def test_every_interface_can_be_closed(panel, ports):
    """Which is a box nothing on a wire can reach. Allowed: the panel is also
    reachable over the overlay, and refusing it here would be the firewall
    deciding who may lock themselves out."""
    body = options_body(panel, exposed_interfaces=[])

    assert panel.status("PUT", "/network", body) == 200
    assert exposed_now(panel) == []

    panel.call("PUT", "/network", options_body(panel, exposed_interfaces=ports))


# --- the mode switch ----------------------------------------------------------


@pytest.mark.parametrize("mode", ["side_gateway", "router", "server"])
def test_the_box_becomes_each_mode(panel, ports, mode):
    if mode == "side_gateway":
        clean_slate(panel, ports)

    assert panel.status("PUT", "/network/mode", {"mode": mode}) == 200
    assert panel.read("/network")["mode"] == mode


def test_a_server_gives_no_port_a_role(panel):
    roles = {
        entry["settings"]["role"] for entry in panel.read("/network")["interfaces"]
    }

    assert sorted(roles) == ["disabled"]


def test_a_side_gateway_joins_one_network_and_keeps_its_address(panel, ports):
    clean_slate(panel, ports)
    panel.call("PUT", "/network/mode", {"mode": "side_gateway"})

    joined = [
        entry
        for entry in panel.read("/network")["interfaces"]
        if entry["settings"]["role"] == "lan"
    ]

    assert len(joined) == 1
    stored = joined[0]["settings"]["lan"]["address"]
    live = (joined[0]["link"]["ipv4_address"] or "").split("/")[0]
    assert stored == live, "the box took an address off the network it joined"


def test_a_mode_that_is_not_one_is_refused(panel):
    """One-arm is a layout the wizard offers, not a mode the box stores."""
    assert panel.status("PUT", "/network/mode", {"mode": "one_arm_router"}) == 400


def test_the_mode_it_is_already_in_is_accepted(panel):
    panel.call("PUT", "/network/mode", {"mode": "server"})

    assert panel.status("PUT", "/network/mode", {"mode": "server"}) == 200


# --- one interface at a time --------------------------------------------------


@pytest.fixture(scope="module")
def served(panel, ports) -> str:
    """A router with one served network on its last port."""
    clean_slate(panel, ports)
    assert panel.status("PUT", "/network/mode", {"mode": "router"}) == 200
    name = ports[-1]
    body = interface_body(
        panel,
        name,
        role="lan",
        lan={
            "address": SERVED_CIDR,
            "prefix_len": 24,
            "is_dhcp_enabled": True,
            "dhcp_range_start": SERVED_RANGE[0],
            "dhcp_range_end": SERVED_RANGE[1],
            "dhcp_lease_time": "12h",
            "upstream_gateway": None,
        },
    )
    assert panel.status("PUT", f"/network/interfaces/{name}", body) == 200
    return name


@pytest.mark.parametrize(
    "label,patch",
    [
        ("a prefix length of 0", {"lan": {"prefix_len": 0}}),
        ("a prefix length of 33", {"lan": {"prefix_len": 33}}),
        ("an address that is not one", {"lan": {"address": "not.an.address"}}),
        (
            "a lease range outside the network",
            {"lan": {"dhcp_range_start": "10.9.9.1", "dhcp_range_end": "10.9.9.9"}},
        ),
        (
            "a lease range that runs backwards",
            {
                "lan": {
                    "dhcp_range_start": SERVED_RANGE[1],
                    "dhcp_range_end": SERVED_RANGE[0],
                }
            },
        ),
        (
            "the gateway inside its own lease range",
            {
                "lan": {
                    "dhcp_range_start": SERVED_CIDR,
                    "dhcp_range_end": SERVED_RANGE[1],
                }
            },
        ),
        (
            "an upstream router outside the network",
            {"lan": {"upstream_gateway": "10.0.0.1"}},
        ),
        (
            "an upstream router that is the box itself",
            {"lan": {"upstream_gateway": SERVED_CIDR}},
        ),
        ("a cloned MAC that is not a MAC", {"wan": {"cloned_mac": "hello"}}),
        ("a lease time that is not one", {"lan": {"dhcp_lease_time": "forever"}}),
        (
            "a lease time carrying a second directive",
            {"lan": {"dhcp_lease_time": "12h\nlog-queries=1"}},
        ),
    ],
)
def test_a_served_network_refuses_what_it_cannot_serve(panel, served, label, patch):
    body = interface_body(panel, served, role="lan", **patch)

    assert panel.status("PUT", f"/network/interfaces/{served}", body) == 400


def test_the_name_in_the_path_must_be_the_name_in_the_body(panel, ports, served):
    body = interface_body(panel, served)

    assert panel.status("PUT", f"/network/interfaces/{ports[0]}", body) == 400


def test_an_interface_this_machine_lacks_cannot_be_configured(panel, served):
    body = dict(interface_body(panel, served), name="enp9s9")

    assert panel.status("PUT", "/network/interfaces/enp9s9", body) == 400


def test_a_physical_port_cannot_be_removed(panel, served):
    """It is a socket on the board. Only what the panel created comes off."""
    assert panel.status("DELETE", f"/network/interfaces/{served}") == 400


def test_removing_an_interface_that_is_not_there_is_a_404(panel):
    assert panel.status("DELETE", "/network/interfaces/enp9s9") == 404


def test_two_networks_cannot_serve_one_subnet(panel, ports, served):
    if len(ports) < 2:
        pytest.skip("this machine has one interface")
    body = interface_body(
        panel,
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
    )

    assert panel.status("PUT", f"/network/interfaces/{ports[0]}", body) == 400


# --- VLANs on a trunk ---------------------------------------------------------


@pytest.fixture(scope="module")
def trunk(panel, ports) -> str:
    """A router with its last port split into a trunk."""
    clean_slate(panel, ports)
    panel.call("PUT", "/network/mode", {"mode": "router"})
    name = ports[-1]
    body = interface_body(panel, name, role="split")
    assert panel.status("PUT", f"/network/interfaces/{name}", body) == 200
    return name


def test_splitting_a_port_brings_its_untagged_main(panel, trunk):
    mains = [
        entry["settings"]["name"]
        for entry in panel.read("/network")["interfaces"]
        if entry["settings"].get("vlan") and entry["settings"]["vlan"]["id"] is None
    ]

    assert mains == [f"{trunk}.main"]


@pytest.mark.parametrize("vlan_id,want", [(0, 400), (4095, 400), (1, 200), (4094, 200)])
def test_a_vlan_id_is_one_the_wire_can_carry(panel, trunk, vlan_id, want):
    body = vlan_body(trunk, vlan_id)

    assert panel.status("PUT", f"/network/interfaces/{trunk}.{vlan_id}", body) == want


def test_a_trunk_carries_more_vlans_than_anybody_would_type(panel, trunk):
    made = sum(
        panel.status(
            "PUT", f"/network/interfaces/{trunk}.{vlan_id}", vlan_body(trunk, vlan_id)
        )
        == 200
        for vlan_id in CROWD_VLAN_IDS
    )

    assert made == len(CROWD_VLAN_IDS)
    assert len(vlan_names(panel)) == len(CROWD_VLAN_IDS) + 3


def test_exposure_follows_a_vlan_that_is_removed(panel, trunk):
    """A name left in the exposed set is one the firewall would name and nft
    would refuse, which is the whole ruleset failing to load."""
    panel.call(
        "PUT", "/network", options_body(panel, exposed_interfaces=[f"{trunk}.1"])
    )
    assert exposed_now(panel) == [f"{trunk}.1"]

    assert panel.status("DELETE", f"/network/interfaces/{trunk}.1") == 200
    assert exposed_now(panel) == []


def test_the_untagged_main_cannot_be_removed_on_its_own(panel, trunk):
    assert panel.status("DELETE", f"/network/interfaces/{trunk}.main") == 400


def test_one_vlan_can_be_removed(panel, trunk):
    assert panel.status("DELETE", f"/network/interfaces/{trunk}.4094") == 200


def test_leaving_the_trunk_role_takes_every_vlan_with_it(panel, trunk):
    body = interface_body(panel, trunk, role="disabled")

    assert panel.status("PUT", f"/network/interfaces/{trunk}", body) == 200
    assert vlan_names(panel) == []


# --- the panel's own port -----------------------------------------------------


@pytest.mark.parametrize("port", [0, 65536, -1])
def test_a_port_the_panel_cannot_take_is_refused(panel, port):
    assert panel.status("PUT", "/settings", {"listen_port": port}) == 400


def test_the_port_it_is_already_on_is_accepted(panel):
    """Saving an unchanged port must not be a restart into nothing."""
    settings = panel.read("/settings")

    assert (
        panel.status("PUT", "/settings", {"listen_port": settings["listen_port"]})
        == 200
    )
