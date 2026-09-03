"""Shared fixtures and builders for the test suite.

Two rules hold everywhere in ``tests/``.

**Nothing touches the real appliance.** No test reads ``config/``, reconfigures
an interface, or restarts a service. The pure layers are exercised directly,
and the layers that talk to the system are given a stub that answers from a
dictionary. A test suite that could take the gateway off the network would be
one nobody dares run on the gateway.

**Anything that shells out declares it.** The renderers are checked against the
real validators where that is possible unprivileged — ``dnsmasq --test`` is —
and marked ``needs_root`` where it is not, because ``nft -c`` needs to open a
netlink socket. Those skip with a reason rather than failing.
"""

import os
import secrets
import subprocess

import pytest

from neutrino_hub.modules.router.interfaces import RouterNetworkConfig
from neutrino_hub.modules.router.link_status import (
    LINK_KIND_ETHERNET,
    LINK_KIND_WIFI,
    LinkStatus,
)
from neutrino_hub.modules.router.uplink_plan import UplinkFacts


def pytest_collection_modifyitems(config, items):
    """Skip the tests that need privileges the current run does not have."""
    if os.geteuid() == 0:
        return
    skip = pytest.mark.skip(reason="needs root: `nft -c` cannot open netlink")
    for item in items:
        if "needs_root" in item.keywords:
            item.add_marker(skip)


def unlock_vault(monkeypatch, tmp_path) -> bytes:
    """Point the vault's state root at a fresh unlocked key under tmp_path.

    Args:
        monkeypatch: pytest's patcher.
        tmp_path: pytest's per-test directory.

    Returns:
        The data key the vault now seals with.
    """
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    data_key = secrets.token_bytes(32)
    (state / "vault.key").write_text(data_key.hex() + "\n")
    monkeypatch.setattr("neutrino_hub.utils.constants.UTILS_STATE_ROOT", state)
    return data_key


# --- Builders for configuration ---------------------------------------------


def wan_entry(
    name: str, *, intent: str = "auto", is_exposed: bool = False, **wan
) -> dict:
    """One WAN interface as it appears in ``config/router/network.json``.

    Closed by default, as the planner leaves an uplink: what this box listens
    on has no business answering the whole internet.
    """
    return {
        "name": name,
        "role": "wan",
        "is_exposed": is_exposed,
        "wan": {"intent": intent, **wan},
    }


def lan_entry(
    name: str,
    *,
    address: str,
    prefix_len: int = 24,
    is_dhcp_enabled: bool = True,
    is_exposed: bool = True,
    pool: tuple[str, str] | None = None,
    lease: str = "12h",
    **wifi,
) -> dict:
    """One LAN interface, with a DHCP pool derived from its address by default.

    Exposed by default, as the planner leaves a served network: it is where
    the panel, the leases and DNS are reached.
    """
    if pool is None:
        head = address.rsplit(".", 1)[0]
        pool = (f"{head}.100", f"{head}.200")
    return {
        "name": name,
        "role": "lan",
        "is_exposed": is_exposed,
        "lan": {
            "address": address,
            "prefix_len": prefix_len,
            "is_dhcp_enabled": is_dhcp_enabled,
            "dhcp_range_start": pool[0],
            "dhcp_range_end": pool[1],
            "dhcp_lease_time": lease,
        },
        "wifi": wifi,
    }


def network_config(
    *entries: dict, policy: str = "failover", **rest
) -> RouterNetworkConfig:
    """Build a parsed configuration from interface entries."""
    return RouterNetworkConfig.from_dict(
        {"interfaces": list(entries), "uplink_policy": policy, **rest}
    )


# --- Builders for live state ------------------------------------------------


def wired_facts(
    name: str,
    *,
    gateway: str | None = None,
    cidr: str | None = None,
    speed: int | None = 1000,
    is_carrying: bool = True,
) -> UplinkFacts:
    """What the system would say about a working wired uplink."""
    return UplinkFacts(
        name=name,
        medium=LINK_KIND_ETHERNET,
        is_carrying=is_carrying,
        gateway=gateway,
        cidr=cidr,
        speed_mbps=speed,
    )


def wireless_facts(
    name: str,
    *,
    gateway: str | None = None,
    cidr: str | None = None,
    speed: int | None = 300,
    is_carrying: bool = True,
) -> UplinkFacts:
    """What the system would say about an associated radio."""
    return UplinkFacts(
        name=name,
        medium=LINK_KIND_WIFI,
        is_carrying=is_carrying,
        gateway=gateway,
        cidr=cidr,
        speed_mbps=speed,
    )


def link(
    name: str,
    *,
    kind: str = LINK_KIND_ETHERNET,
    address: str | None = None,
    is_up: bool = True,
    gateway: str | None = None,
    is_ap_capable: bool = True,
    speed_mbps: int | None = 1000,
) -> LinkStatus:
    """One interface's live state, as the readers would report it."""
    return LinkStatus(
        name=name,
        kind=kind,
        is_present=True,
        is_up=is_up,
        ipv4_address=address,
        mac_address="aa:bb:cc:dd:ee:ff",
        speed_mbps=speed_mbps,
        is_ap_capable=is_ap_capable,
    )


class StubLinkStatus:
    """A :class:`RouterLinkStatus` that answers from a dictionary.

    Everything the network layer asks the system is routed through the real
    reader, so replacing it is enough to make the layers above it testable
    without a network — and without the chance of a test reconfiguring the
    machine it is running on.
    """

    def __init__(self, links: list[LinkStatus], gateways: dict[str, str] | None = None):
        """
        Args:
            links: The interfaces the box appears to have.
            gateways: Next hop per interface, for the ones that have one.
        """
        self._links = links
        self._gateways = gateways or {}

    def all_links(self) -> list[LinkStatus]:
        return list(self._links)

    def link(self, name: str) -> LinkStatus:
        for entry in self._links:
            if entry.name == name:
                return entry
        return LinkStatus(name=name)

    def gateway_for(self, name: str) -> str | None:
        return self._gateways.get(name)

    def default_gateway(self) -> str | None:
        return next(iter(self._gateways.values()), None)

    def default_routes(self) -> list[dict]:
        return [
            {"dev": name, "gateway": gateway, "metric": 100}
            for name, gateway in self._gateways.items()
        ]


def without_comments(rendered: str) -> str:
    """Strip the comment lines from a rendered artifact.

    The renderers explain themselves in the files they produce, and those
    explanations name the very things a test wants to assert are absent — the
    nft ruleset says "nothing to masquerade", the dnsmasq config says why it
    does not use bind-interfaces. Asserting against the raw text therefore
    matches prose instead of directives. Assert against this instead.

    Args:
        rendered: A rendered ruleset or configuration file.

    Returns:
        The same text with whole-line comments removed.
    """
    return "\n".join(
        line for line in rendered.splitlines() if not line.strip().startswith("#")
    )


# --- External validators ----------------------------------------------------


def validate_dnsmasq(config_text: str, tmp_path) -> None:
    """Run the real ``dnsmasq --test`` over a rendered config.

    Args:
        config_text: The rendered file.
        tmp_path: pytest's per-test directory.

    Raises:
        AssertionError: If dnsmasq rejects it, quoting what it said.
    """
    path = tmp_path / "neutrino.conf"
    path.write_text(config_text, encoding="utf-8")
    result = subprocess.run(
        ["dnsmasq", "--test", "-C", str(path)], capture_output=True, text=True
    )
    assert result.returncode == 0, (
        f"dnsmasq rejected the rendered config:\n"
        f"{result.stderr.strip() or result.stdout.strip()}\n\n{config_text}"
    )


def validate_nft(ruleset: str) -> None:
    """Run the real ``nft -c`` over a rendered ruleset.

    Args:
        ruleset: The rendered ruleset text.

    Raises:
        AssertionError: If nft rejects it, quoting what it said.
    """
    result = subprocess.run(
        ["nft", "-c", "-f", "-"], input=ruleset, capture_output=True, text=True
    )
    assert result.returncode == 0, (
        f"nft rejected the rendered ruleset:\n" f"{result.stderr.strip()}\n\n{ruleset}"
    )
