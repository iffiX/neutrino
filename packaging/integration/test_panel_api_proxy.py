"""Every operation the Proxy page offers, and the edges around them.

The nodes named here are servers nobody can reach, which is what these need:
the checks are about the list and the switch, never about traffic arriving
anywhere.
"""

import pytest

SHARE_LINK = "ss://YWVzLTI1Ni1nY206c2VjcmV0@203.0.113.10:5800#audit"  # scan: allow
SECOND_LINK = "ss://YWVzLTI1Ni1nY206c2VjcmV0@203.0.113.11:5800#audit2"  # scan: allow
# More direct domains than anybody would type.
CROWD_DOMAIN_COUNT = 1000


def routing_body(panel, **over) -> dict:
    """The routing options as they are now, with some of them changed."""
    body = dict(panel.read("/hub/proxy"))
    body.update(over)
    return body


def node_ids(panel) -> list:
    """Every node in the list."""
    return [node["id"] for node in panel.read("/hub/proxy/node")["nodes"]]


def is_proxy_on(panel) -> bool:
    """Whether the master switch is on."""
    return panel.read("/hub/proxy")["is_proxy_enabled"]


@pytest.fixture(scope="module")
def empty_list(panel):
    """A box with no exit node at all."""
    for node_id in node_ids(panel):
        panel.call("POST", "/hub/proxy/node/remove", {"node_id": node_id})
    return panel


# --- the exit-node list -------------------------------------------------------


def test_deleting_the_last_node_switches_the_proxy_off(empty_list, panel):
    """Left on, the next Apply fails on a configuration that cannot be
    rendered, and the page says nothing about the switch that fixes it."""
    assert node_ids(panel) == []
    assert not is_proxy_on(panel)


def test_applying_a_box_with_no_nodes_succeeds(empty_list, panel):
    """This used to fail for ever, with the one thing that fixed it hidden."""
    assert panel.status("POST", "/hub/proxy/apply") == 200


def test_the_switch_cannot_be_turned_on_with_an_empty_list(empty_list, panel):
    body = routing_body(panel, is_proxy_enabled=True)

    assert panel.status("POST", "/hub/proxy/set", body) == 400


@pytest.mark.parametrize("link", ["hello", ""])
def test_a_link_that_is_not_one_is_refused(empty_list, panel, link):
    assert panel.status("POST", "/hub/proxy/node/add", {"link": link}) == 400


def test_a_node_is_added_once(empty_list, panel):
    assert panel.status("POST", "/hub/proxy/node/add", {"link": SHARE_LINK}) == 200
    assert panel.status("POST", "/hub/proxy/node/add", {"link": SHARE_LINK}) == 400
    assert panel.status("POST", "/hub/proxy/node/add", {"link": SECOND_LINK}) == 200
    assert len(node_ids(panel)) == 2


def test_one_of_two_disabled_leaves_the_switch_as_it_was(panel):
    """Only emptying the list flips it: that state cannot be rendered, and one
    node standing is a proxy that still works."""
    was_on = is_proxy_on(panel)
    node_id = node_ids(panel)[0]

    assert (
        panel.status(
            "POST", "/hub/proxy/node/set", {"node_id": node_id, "name": "renamed"}
        )
        == 200
    )
    assert (
        panel.status(
            "POST",
            "/hub/proxy/node/set",
            {"node_id": node_id, "is_enabled": False},
        )
        == 200
    )
    assert is_proxy_on(panel) == was_on


def test_a_node_that_is_not_there_is_a_404(panel):
    assert (
        panel.status(
            "POST",
            "/hub/proxy/node/set",
            {"node_id": "nosuchnode", "is_enabled": True},
        )
        == 404
    )
    assert (
        panel.status("POST", "/hub/proxy/node/remove", {"node_id": "nosuchnode"}) == 404
    )


@pytest.mark.parametrize(
    "settings",
    [
        {"probe_interval_s": 0},
        {"probe_interval_s": 5},
        {"probe_interval_s": 4000},
        {"probe_url": "example.com"},
        {"reference_url": "example.com"},
    ],
)
def test_measurement_settings_the_hub_cannot_keep_are_refused(panel, settings):
    body = dict(
        {
            "probe_url": "https://example.com",
            "reference_url": "http://example.net",
            "probe_interval_s": 60,
        },
        **settings,
    )

    assert panel.status("POST", "/hub/proxy/balancer/set", body) == 400


def test_the_list_empties_again(panel):
    for node_id in node_ids(panel):
        panel.call("POST", "/hub/proxy/node/remove", {"node_id": node_id})

    assert node_ids(panel) == []


# --- an earlier build's listeners ---------------------------------------------


def test_a_body_naming_a_listener_stores_and_opens_none(panel):
    body = routing_body(panel, socks_ports=[{"port": 1080, "is_proxied": False}])

    assert panel.status("POST", "/hub/proxy/set", body) == 200
    assert "socks_ports" not in panel.read("/hub/proxy")


# --- the routing lists --------------------------------------------------------


def test_a_thousand_direct_domains_are_all_kept(panel):
    domains = [f"domain:host{index}.example" for index in range(CROWD_DOMAIN_COUNT)]
    body = routing_body(panel, direct_domains=domains)

    assert panel.status("POST", "/hub/proxy/set", body) == 200
    assert len(panel.read("/hub/proxy")["direct_domains"]) == CROWD_DOMAIN_COUNT


@pytest.mark.parametrize(
    "lists",
    [
        {"direct_ips": ["192.0.2.300"]},
        {"direct_ips": ["cn"]},
        {"direct_ips": [""]},
        {"direct_domains": ["regexp:(unclosed"]},
    ],
)
def test_a_direct_list_xray_will_not_load_is_refused(panel, lists):
    """xray refuses the whole configuration over one of these, so accepting it
    is a page that saves and then fails every Apply after it."""
    body = routing_body(panel, **lists)

    assert panel.status("POST", "/hub/proxy/set", body) == 400


def test_the_direct_lists_can_be_emptied(panel):
    body = routing_body(panel, direct_domains=[], direct_ips=[])

    assert panel.status("POST", "/hub/proxy/set", body) == 200


@pytest.mark.parametrize(
    "resolver",
    [{"address": "not.an.address", "port": 53}, {"address": "223.5.5.5", "port": 0}],
)
def test_a_resolver_that_cannot_be_asked_is_refused(panel, resolver):
    body = routing_body(panel, direct_dns=[resolver])

    assert panel.status("POST", "/hub/proxy/set", body) == 400


def test_an_empty_remote_list_is_refused(panel):
    body = routing_body(panel, remote_dns=[])

    assert panel.status("POST", "/hub/proxy/set", body) == 400


def test_both_resolver_lists_keep_several_rows_in_order(panel):
    rows = [{"address": "8.8.8.8", "port": 53}, {"address": "1.1.1.1", "port": 53}]
    before = dict(panel.read("/hub/proxy"))
    body = routing_body(panel, remote_dns=rows, direct_dns=rows[::-1])

    try:
        assert panel.status("POST", "/hub/proxy/set", body) == 200
        saved = panel.read("/hub/proxy")
        assert saved["remote_dns"] == rows
        assert saved["direct_dns"] == rows[::-1]
    finally:
        assert panel.status("POST", "/hub/proxy/set", before) == 200


def test_applying_with_nothing_to_apply_succeeds(panel):
    assert panel.status("POST", "/hub/proxy/apply") == 200
