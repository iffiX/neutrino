"""Rendering the dnsmasq configuration for the networks the gateway serves.

Every case is checked against the real ``dnsmasq --test``, which runs
unprivileged. That matters here: the failure this file exists to prevent was a
config dnsmasq refused to start on, which took DHCP and DNS off the wired LAN
because of a mistake in the Wi-Fi half.
"""

from neutrino_hub.modules.router.dnsmasq_renderer import (
    NO_LAN_PLACEHOLDER_INTERFACE,
    RouterDnsmasqRenderer,
)

from tests.conftest import (
    lan_entry,
    network_config,
    validate_dnsmasq,
    wan_entry,
    without_comments,
)


def render(*entries) -> str:
    return RouterDnsmasqRenderer(network=network_config(*entries)).render()


def test_one_lan_serves_its_own_interface(tmp_path):
    config = render(lan_entry("enp1s0", address="192.168.100.1"))

    assert "interface=enp1s0" in config
    assert "dhcp-range=192.168.100.100,192.168.100.200,12h" in config
    assert "dhcp-option=tag:enp1s0,option:router,192.168.100.1" in config
    validate_dnsmasq(config, tmp_path)


def test_two_lans_each_get_their_own_pool_and_tag(tmp_path):
    """Tagging by interface is what stops a client being handed the wrong gateway.

    dnsmasq tags every request with the interface it arrived on, so the router
    and resolver options can be pinned per network. Without that, a client on
    the Wi-Fi could be told its gateway is the wired address.
    """
    config = render(
        lan_entry("enp1s0", address="192.168.100.1"),
        lan_entry("wlp3s0", address="192.168.101.1"),
    )

    assert "interface=enp1s0" in config
    assert "interface=wlp3s0" in config
    assert "dhcp-option=tag:enp1s0,option:router,192.168.100.1" in config
    assert "dhcp-option=tag:wlp3s0,option:router,192.168.101.1" in config
    validate_dnsmasq(config, tmp_path)


def test_no_address_is_named_alongside_its_interface(tmp_path):
    """The bug that stopped dnsmasq starting once there were two LANs.

    ``bind-interfaces`` opens one socket per named interface. A
    ``listen-address`` that sits on one of those interfaces asks for a second
    socket on the same address; with a single LAN it passes, and with two it
    fails outright on "Address already in use", taking the whole service down.
    """
    config = render(
        lan_entry("enp1s0", address="192.168.100.1"),
        lan_entry("wlp3s0", address="192.168.101.1"),
    )

    directives = without_comments(config)
    assert "listen-address" not in directives
    assert "bind-interfaces" not in directives
    assert "bind-dynamic" in directives
    validate_dnsmasq(config, tmp_path)


def test_a_lan_that_is_not_up_yet_does_not_stop_the_others(tmp_path):
    """A Wi-Fi access point exists only once the radio is up.

    Under ``bind-interfaces`` an interface that is not there yet stops dnsmasq
    starting at all. ``bind-dynamic`` tolerates it, so one radio failing to come
    up cannot darken the wired LAN.
    """
    config = render(
        lan_entry("enp1s0", address="192.168.100.1"),
        lan_entry("wlan_not_present", address="192.168.199.1"),
    )

    assert "bind-dynamic" in config
    validate_dnsmasq(config, tmp_path)


def test_dhcp_can_be_turned_off_while_dns_keeps_serving(tmp_path):
    config = render(lan_entry("enp1s0", address="192.168.100.1", is_dhcp_enabled=False))

    assert "dhcp-range" not in without_comments(config)
    assert "interface=enp1s0" in config
    validate_dnsmasq(config, tmp_path)


def test_a_box_serving_nothing_still_refuses_to_answer_the_uplink(tmp_path):
    """dnsmasq with no interface named listens on all of them, uplink included.

    Naming an interface that does not exist is how it is told to serve nothing
    at all, which is very different from serving everything.
    """
    config = render(wan_entry("enp2s0"))

    assert f"interface={NO_LAN_PLACEHOLDER_INTERFACE}" in config
    assert "dhcp-range" not in without_comments(config)
    validate_dnsmasq(config, tmp_path)


def test_the_only_upstream_is_the_local_xray_inbound(tmp_path):
    """The whole point of the DNS path: no query leaves by the uplink in clear."""
    config = render(lan_entry("enp1s0", address="192.168.100.1"))

    assert "no-resolv" in config
    assert "server=127.0.0.1#15353" in config
    assert config.count("server=") == 1
    validate_dnsmasq(config, tmp_path)


def test_queries_go_through_xray_while_the_proxy_is_on(tmp_path):
    config = RouterDnsmasqRenderer(
        network=network_config(lan_entry("enp1s0", address="192.168.100.1")),
        routing={"is_proxy_enabled": True},
    ).render()

    assert "server=127.0.0.1#15353" in config
    validate_dnsmasq(config, tmp_path)


def test_queries_go_direct_while_the_proxy_is_off(tmp_path):
    """Resolving through xray for traffic that is not going there is worse twice.

    The answer would come from an exit node the traffic never touches, and the
    LAN would lose DNS entirely whenever xray was stopped — which is a likely
    thing to do while the proxy is deliberately off.
    """
    config = RouterDnsmasqRenderer(
        network=network_config(lan_entry("enp1s0", address="192.168.100.1")),
        routing={
            "is_proxy_enabled": False,
            "direct_dns": {"address": "223.5.5.5", "port": 53},
        },
    ).render()

    assert "server=223.5.5.5#53" in config
    assert "15353" not in without_comments(config)
    validate_dnsmasq(config, tmp_path)
