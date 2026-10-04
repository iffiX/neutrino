"""The proxy's two resolver lists, and how a file written before them reads."""

import pytest

from neutrino_hub.modules.xray.resolvers import (
    direct_resolvers,
    read_resolvers,
    with_resolver_lists,
)

NETWORK = [{"address": "192.168.1.1", "port": 53}]


# --- a file written before the lists ------------------------------------------


def test_a_direct_resolver_left_at_the_former_default_follows_the_network():
    routing = {"direct_dns": {"address": "223.5.5.5", "port": 53}}

    assert read_resolvers(routing, "direct_dns") == []
    assert direct_resolvers(routing, NETWORK) == NETWORK


def test_a_direct_resolver_a_person_changed_is_kept():
    routing = {"direct_dns": {"address": "119.29.29.29", "port": 5353}}

    assert read_resolvers(routing, "direct_dns") == [
        {"address": "119.29.29.29", "port": 5353}
    ]
    assert direct_resolvers(routing, NETWORK) == [
        {"address": "119.29.29.29", "port": 5353}
    ]


@pytest.mark.parametrize("value", [{}, {"address": ""}, None])
def test_an_empty_direct_resolver_follows_the_network(value):
    routing = {"direct_dns": value}

    assert read_resolvers(routing, "direct_dns") == []
    assert direct_resolvers(routing, NETWORK) == NETWORK


def test_a_remote_resolver_from_before_the_lists_is_kept_whatever_it_is():
    routing = {"remote_dns": {"address": "1.1.1.1", "port": 53}}

    assert read_resolvers(routing, "remote_dns") == [{"address": "1.1.1.1", "port": 53}]


# --- the lists ----------------------------------------------------------------


def test_the_lists_keep_their_order_and_their_ports():
    routing = {
        "remote_dns": [
            {"address": "8.8.8.8", "port": 53},
            {"address": "1.1.1.1", "port": 5353},
        ],
        "direct_dns": [{"address": "119.29.29.29"}, {"address": "223.5.5.5"}],
    }

    assert read_resolvers(routing, "remote_dns") == [
        {"address": "8.8.8.8", "port": 53},
        {"address": "1.1.1.1", "port": 5353},
    ]
    assert read_resolvers(routing, "direct_dns") == [
        {"address": "119.29.29.29", "port": 53},
        {"address": "223.5.5.5", "port": 53},
    ]


def test_a_list_holding_the_former_default_is_kept():
    routing = {"direct_dns": [{"address": "223.5.5.5", "port": 53}]}

    assert direct_resolvers(routing, NETWORK) == [{"address": "223.5.5.5", "port": 53}]


@pytest.mark.parametrize("routing", [{}, {"remote_dns": []}])
def test_a_remote_list_that_names_none_reads_as_the_default(routing):
    assert read_resolvers(routing, "remote_dns") == [{"address": "1.1.1.1", "port": 53}]


def test_the_page_reads_both_fields_as_lists():
    routing = {
        "is_proxy_enabled": True,
        "remote_dns": {"address": "9.9.9.9", "port": 53},
        "direct_dns": {"address": "223.5.5.5", "port": 53},
    }

    assert with_resolver_lists(routing) == {
        "is_proxy_enabled": True,
        "remote_dns": [{"address": "9.9.9.9", "port": 53}],
        "direct_dns": [],
    }
