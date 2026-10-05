"""A router resolves its own names at its own dnsmasq, served network or not.

network.md: router mode replaces `/etc/resolv.conf`, and the file names the
first served network's address, or `127.0.0.1` on a router that serves no
network. The lifecycle walk sets the box up as a router with `"lan": []`, and
this file runs first in the phase after that setup, so it sees the box the
setup left.
"""

import time

import pytest

import machine_state

SETTLE_LIMIT_S = 60.0
LOOPBACK_RESOLVER = "127.0.0.1"


def expected_resolver(view: dict) -> str:
    """The address the resolver file names for this network view."""
    for entry in view["interfaces"]:
        settings = entry["settings"]
        if settings["role"] == "lan" and settings["lan"]["address"]:
            return settings["lan"]["address"]
    return LOOPBACK_RESOLVER


def test_a_router_names_its_own_dnsmasq_and_resolves(panel):
    view = panel.read("/hub/network")
    if view["mode"] != "router":
        pytest.skip("only router mode writes the box's resolver file")
    wanted = f"nameserver {expected_resolver(view)}"
    deadline = time.monotonic() + SETTLE_LIMIT_S
    while wanted not in machine_state.resolv_conf().splitlines():
        assert time.monotonic() < deadline, (
            f"/etc/resolv.conf does not name {wanted}: "
            f"{machine_state.resolv_conf()!r}"
        )
        time.sleep(1.0)

    assert machine_state.run(["getent", "hosts", "deb.debian.org"]).strip() != ""
