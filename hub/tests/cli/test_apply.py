"""What `nhub apply` renders: the hub's own components and nothing hosted."""

from neutrino_hub.cli import apply


def test_the_components_are_the_hubs_own():
    """A device hosts the file share, the git server, the containers and the
    storage from its desired state; the hub renders none of them."""
    assert apply.COMPONENTS == (
        "router",
        "xray",
        "dnsmasq",
        "cliproxyapi",
        "easytier",
    )
