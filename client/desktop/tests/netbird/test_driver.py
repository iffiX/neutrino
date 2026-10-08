"""NetBird's driver in the client.

The driver runs on the scripted platform of the overlay tests. Pinned here:
NetBird's join carries the setup key, the management URL and
``--disable-dns``, and refuses without running while the daemon is on
another network; the hub is seen at its address or by its name; two hubs on
one management URL are one network; the hub's host is its own address, then
an address of the binding inside NetBird's network, then its name.
"""

import json

import pytest

from neutrino_client.core.overlay import overlay_hub_host, overlay_key
from neutrino_client.exceptions import OverlayControlError
from neutrino_client.netbird.driver import (
    OverlayNetbirdDriver,
    netbird_management_key,
)
from tests.core.test_overlay import NETBIRD, ScriptedPlatform

KEY = NETBIRD["setup_key"]


def netbird_status(url="https://nb.example:443", is_connected=True, peers=()):
    return json.dumps(
        {
            "management": {"url": url, "connected": is_connected},
            "netbirdIp": "100.64.0.7/16",
            "peers": {"details": list(peers)},
        }
    )


def drivers(tmp_path):
    """NetBird's driver over one scripted platform."""
    platform = ScriptedPlatform(tmp_path)
    return OverlayNetbirdDriver(platform=platform), None, platform


def test_the_hubs_address_is_its_own_then_a_url_inside_the_network_then_its_name():
    urls = ["https://192.168.10.1:8443", "https://100.88.92.30:8443"]
    netbird = dict(NETBIRD, hub_address="100.88.92.31")

    assert overlay_hub_host(netbird, urls) == "100.88.92.31"
    assert overlay_hub_host(NETBIRD, urls) == "100.88.92.30"
    assert overlay_hub_host(NETBIRD, urls[:1]) == "hub.nb.example"
    assert overlay_hub_host(dict(NETBIRD, fqdn=""), urls[:1]) == ""


def test_a_netbird_join_carries_the_key_the_url_and_no_dns(tmp_path):
    netbird, _easytier, platform = drivers(tmp_path)
    platform.answer("netbird", "status", stdout=netbird_status(is_connected=False))

    netbird.join(NETBIRD, "box")

    ups = [args for binary, args in platform.runs if args[0] == "up"]
    assert ups == [
        [
            "up",
            "--setup-key",
            KEY,
            "--management-url",
            "https://nb.example:443",
            "--disable-dns",
        ]
    ]


def test_a_daemon_on_another_network_is_refused_and_left_alone(tmp_path):
    netbird, _easytier, platform = drivers(tmp_path)
    platform.answer(
        "netbird", "status", stdout=netbird_status(url="https://api.netbird.io:443")
    )

    with pytest.raises(OverlayControlError) as refused:
        netbird.join(NETBIRD, "box")

    assert refused.value.code == "overlay_other_network"
    assert refused.value.params == {"network": "nb.example"}
    assert all(args[0] != "up" for _binary, args in platform.runs)


def test_a_connected_daemon_reads_on_with_its_address_and_the_hub_seen(tmp_path):
    netbird, _easytier, platform = drivers(tmp_path)
    platform.answer(
        "netbird",
        "status",
        stdout=netbird_status(
            peers=[{"fqdn": "hub.nb.example", "status": "Connected"}]
        ),
    )

    status = netbird.status(NETBIRD)

    assert (status["is_on"], status["address"], status["is_hub_seen"]) == (
        True,
        "100.64.0.7",
        True,
    )


def test_two_hubs_on_one_management_url_are_one_network():
    other = dict(NETBIRD, management_url="https://NB.example:443/", fqdn="o")

    assert overlay_key(NETBIRD) == overlay_key(other)


def test_a_daemon_that_does_not_answer_is_daemon_down(tmp_path):
    netbird, _easytier, platform = drivers(tmp_path)
    platform.answer(
        "netbird",
        "status",
        returncode=1,
        stderr="failed to connect to daemon error: context deadline exceeded",
    )

    with pytest.raises(OverlayControlError) as refused:
        netbird.status(NETBIRD)

    assert refused.value.code == "overlay_daemon_down"


def test_a_daemon_that_needs_login_reads_off(tmp_path):
    netbird, _easytier, platform = drivers(tmp_path)
    platform.answer("netbird", "status", stdout="Daemon status: NeedsLogin\n")

    assert netbird.status(NETBIRD)["is_on"] is False


def test_a_leave_is_netbird_down(tmp_path):
    netbird, _easytier, platform = drivers(tmp_path)

    netbird.leave(NETBIRD)

    assert ("netbird", ["down"]) in platform.runs


def test_the_default_management_url_is_netbirds_own():
    assert netbird_management_key("") == "https://api.netbird.io:443"
    assert netbird_management_key("http://nb.lan") == "http://nb.lan:80"


def test_the_hub_is_seen_by_netbird_at_its_address_or_by_its_name(tmp_path):
    netbird, _easytier, platform = drivers(tmp_path)
    platform.answer(
        "netbird",
        "status",
        stdout=netbird_status(
            peers=[
                {
                    "fqdn": "x.nb.example",
                    "netbirdIp": "100.88.92.30/16",
                    "status": "Connected",
                },
                {"fqdn": "hub.nb.example", "status": "Connecting"},
            ]
        ),
    )

    assert netbird.status(dict(NETBIRD, hub_address="100.88.92.30"))["is_hub_seen"]
    assert not netbird.status(NETBIRD)["is_hub_seen"]
    assert netbird.status(NETBIRD)["network"] == "100.64.0.0/10"


def test_the_peers_are_the_connected_ones_by_address_or_name(tmp_path):
    netbird, _easytier, platform = drivers(tmp_path)
    platform.answer(
        "netbird",
        "status",
        stdout=netbird_status(
            peers=[
                {
                    "fqdn": "x.nb.example",
                    "netbirdIp": "100.88.92.30/16",
                    "status": "Connected",
                },
                {"fqdn": "hub.nb.example", "status": "Connected"},
                {
                    "fqdn": "idle.nb.example",
                    "netbirdIp": "100.88.1.1",
                    "status": "Idle",
                },
            ]
        ),
    )

    assert netbird.status(NETBIRD)["peers"] == ["100.88.92.30", "hub.nb.example"]


def test_a_daemon_off_the_network_names_no_peers(tmp_path):
    netbird, _easytier, platform = drivers(tmp_path)
    platform.answer(
        "netbird",
        "status",
        stdout=netbird_status(
            is_connected=False,
            peers=[{"fqdn": "x", "netbirdIp": "100.88.92.30", "status": "Connected"}],
        ),
    )

    assert netbird.status(NETBIRD)["peers"] == []
