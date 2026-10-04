"""The dhcpcd configuration an uplink takes its lease with."""

from neutrino_hub.modules.router.dhcp_renderer import RouterDhcpRenderer


def directives(text: str) -> list:
    return [line.strip() for line in text.splitlines() if line.strip()]


def test_the_lease_is_asked_to_name_its_resolvers():
    """A DHCP server sends the resolver option only when the client asks for
    it. Without the request the lease names none, and dnsmasq falls back to
    the built-in resolvers whatever the upstream network offers."""
    rendered = directives(
        RouterDhcpRenderer(interface="enp1s0", route_metric=100).render()
    )

    assert "option domain_name_servers" in rendered


def test_no_hook_writes_the_resolvers_anywhere():
    rendered = RouterDhcpRenderer(interface="enp1s0", route_metric=100).render()

    nohook = next(line for line in directives(rendered) if line.startswith("nohook"))
    assert "resolv.conf" in nohook
    assert "openresolv" in nohook


def test_the_uplinks_metric_is_its_own():
    rendered = directives(
        RouterDhcpRenderer(interface="enp2s0", route_metric=110).render()
    )

    assert "interface enp2s0" in rendered
    assert "metric 110" in rendered
