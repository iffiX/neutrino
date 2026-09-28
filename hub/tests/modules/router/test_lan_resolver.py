"""What a served interface leaves the box resolving with.

A gateway that comes up with an address, a route and nothing to ask a name of
cannot fetch its own geodata, install a module from a vendor, or run apt. It
showed on every VM in the lab except Arch, whose resolver happens to ship
compiled-in fallback servers.

Nothing else writes the file any more: the lease client's `resolv.conf` hook is
off, and on a machine whose resolver was `systemd-resolved` that daemon is
stopped in router mode.
"""

import pytest

from neutrino_hub.modules.router import resolver, routes
from neutrino_hub.modules.router.constants import (
    ROUTER_MODE_ROUTER,
    ROUTER_MODE_SERVER,
    ROUTER_RESOLVER_TO_FALLBACK,
    ROUTER_RESOLVER_TO_ORIGINAL,
    ROUTER_RESOLVER_TO_RESOLVED,
    ROUTER_ROLE_LAN,
)
from neutrino_hub.modules.router.interfaces import (
    RouterInterface,
    RouterLanSettings,
    RouterNetworkConfig,
)


@pytest.fixture(autouse=True)
def kept_original(tmp_path, monkeypatch):
    """Where the file found before the first write is kept."""
    path = tmp_path / "state" / "resolv.conf.original"
    monkeypatch.setattr(resolver, "ROUTER_RESOLVER_ORIGINAL_PATH", path)
    return path


class _Ran:
    def __init__(self, *, is_success: bool):
        self.is_success = is_success


@pytest.fixture
def is_resolved_enabled(monkeypatch):
    """Whether `systemctl is-enabled systemd-resolved` succeeds; False first."""
    state = {"is_enabled": False}
    monkeypatch.setattr(
        resolver,
        "run",
        lambda command, **keywords: _Ran(is_success=state["is_enabled"]),
    )
    return state


@pytest.fixture
def resolv_conf(tmp_path, monkeypatch):
    """A `/etc/resolv.conf` a test may write."""
    path = tmp_path / "resolv.conf"
    monkeypatch.setattr(resolver, "RESOLVER_PATH", path)
    return path


def test_a_served_interface_points_the_box_at_its_own_dnsmasq(resolv_conf):
    assert resolver.point_at("192.168.8.1")

    assert "nameserver 192.168.8.1" in resolv_conf.read_text()


def test_the_resolver_follows_the_address_rather_than_a_default(resolv_conf):
    resolver.point_at("192.168.8.1")

    assert resolver.point_at("10.9.0.1")
    assert "nameserver 10.9.0.1" in resolv_conf.read_text()
    assert "192.168.8.1" not in resolv_conf.read_text()


def test_writing_the_same_answer_twice_changes_nothing(resolv_conf):
    """The applier reports what it changed, and a file rewritten identically
    is a change nobody made."""
    resolver.point_at("192.168.8.1")

    assert not resolver.point_at("192.168.8.1")


def test_a_symlink_is_replaced_rather_than_written_through(resolv_conf, tmp_path):
    """On a machine using `systemd-resolved` this path is a link into /run.
    Writing through it puts our nameserver in a file that daemon rewrites —
    or, once it is stopped, under a directory that no longer exists."""
    target = tmp_path / "stub-resolv.conf"
    target.write_text("nameserver 127.0.0.53\n")
    resolv_conf.symlink_to(target)

    resolver.point_at("192.168.8.1")

    assert not resolv_conf.is_symlink()
    assert "nameserver 192.168.8.1" in resolv_conf.read_text()
    assert target.read_text() == "nameserver 127.0.0.53\n"


def test_a_file_somebody_else_wrote_is_never_handed_back(resolv_conf):
    """Handing back only undoes what this wrote. Anything else on the machine
    is somebody's arrangement and is left alone."""
    resolv_conf.write_text("nameserver 1.1.1.1\n")

    assert not resolver.hand_back()
    assert resolv_conf.read_text() == "nameserver 1.1.1.1\n"


def test_a_machine_the_hub_only_answers_on_keeps_its_own_resolver(monkeypatch):
    """server and side_gateway change nothing about how the machine resolves, exactly as
    it changes nothing about how it is addressed."""
    written = []
    monkeypatch.setattr(resolver, "point_at", lambda address: written.append(address))
    network = RouterNetworkConfig(
        mode=ROUTER_MODE_SERVER,
        interfaces=[
            RouterInterface(
                name="eth0",
                role="lan",
                lan=RouterLanSettings(address="192.168.8.1", prefix_len=24),
            )
        ],
    )

    applier = routes.RouterInterfaceApplier.__new__(routes.RouterInterfaceApplier)
    applier._network = network

    assert applier.apply_resolver() == []
    assert written == []


def test_a_gateway_serving_nothing_is_left_resolving_as_it_was(monkeypatch):
    """No served network means no dnsmasq of ours to point at."""
    written = []
    monkeypatch.setattr(resolver, "point_at", lambda address: written.append(address))
    network = RouterNetworkConfig(interfaces=[RouterInterface(name="eth0", role="wan")])

    applier = routes.RouterInterfaceApplier.__new__(routes.RouterInterfaceApplier)
    applier._network = network

    assert applier.apply_resolver() == []
    assert written == []


def test_saving_one_interface_still_points_the_box_at_its_own_dnsmasq(monkeypatch):
    """The panel gives a LAN its role one interface at a time, and that path
    used to end before the resolver step — so a router built from the page
    went on asking whatever its uplink handed it, while one built by a
    whole-network apply did not."""
    pointed: list = []
    monkeypatch.setattr(
        routes.resolver, "point_at", lambda address: pointed.append(address) or True
    )
    network = RouterNetworkConfig(
        mode=ROUTER_MODE_ROUTER,
        interfaces=[
            RouterInterface(
                name="eth0",
                role=ROUTER_ROLE_LAN,
                lan=RouterLanSettings(address="192.168.90.1", prefix_len=24),
            )
        ],
    )

    routes.RouterInterfaceApplier(network=network).apply_resolver()

    assert pointed == ["192.168.90.1"]


def test_a_file_netbird_holds_is_left_and_its_original_written(
    resolv_conf, tmp_path, monkeypatch
):
    """NetBird's resolver sits in front and forwards every other name to the
    servers in the copy it kept, so that copy is where the box's own
    resolver goes; the file NetBird wrote stays its own."""
    original = tmp_path / "resolv.conf.original.netbird"
    monkeypatch.setattr(resolver, "RESOLVER_NETBIRD_ORIGINAL", original)
    netbird_text = "# Generated by NetBird\nnameserver 100.88.78.218\n"
    resolv_conf.write_text(netbird_text)

    assert resolver.point_at("192.168.100.1") is True

    assert resolv_conf.read_text() == netbird_text
    assert original.read_text().endswith("nameserver 192.168.100.1\n")
    assert resolver.point_at("192.168.100.1") is False


# --- the file found before the first write ------------------------------------


def test_the_first_write_keeps_the_file_it_replaces(resolv_conf, kept_original):
    resolv_conf.write_text("nameserver 192.0.2.53\n")

    resolver.point_at("192.168.8.1")

    assert kept_original.read_text() == "nameserver 192.0.2.53\n"


def test_a_symlink_is_kept_as_the_same_symlink(resolv_conf, kept_original, tmp_path):
    stub = tmp_path / "stub-resolv.conf"
    stub.write_text("nameserver 127.0.0.53\n")
    resolv_conf.symlink_to(stub)

    resolver.point_at("192.168.8.1")

    assert kept_original.is_symlink()
    assert kept_original.readlink() == stub


def test_a_second_write_leaves_the_kept_file_alone(resolv_conf, kept_original):
    resolv_conf.write_text("nameserver 192.0.2.53\n")
    resolver.point_at("192.168.8.1")

    resolver.point_at("10.9.0.1")

    assert kept_original.read_text() == "nameserver 192.0.2.53\n"


def test_without_resolved_the_kept_file_is_put_back_and_deleted(
    resolv_conf, kept_original, is_resolved_enabled
):
    resolv_conf.write_text("nameserver 192.0.2.53\n")
    resolver.point_at("192.168.8.1")

    handed = resolver.hand_back(fallback_address="223.5.5.5")

    assert handed == ROUTER_RESOLVER_TO_ORIGINAL
    assert resolv_conf.read_text() == "nameserver 192.0.2.53\n"
    assert not kept_original.exists()


def test_a_kept_symlink_comes_back_as_the_same_symlink(
    resolv_conf, kept_original, is_resolved_enabled, tmp_path
):
    stub = tmp_path / "stub-resolv.conf"
    stub.write_text("nameserver 127.0.0.53\n")
    resolv_conf.symlink_to(stub)
    resolver.point_at("192.168.8.1")

    assert resolver.hand_back() == ROUTER_RESOLVER_TO_ORIGINAL

    assert resolv_conf.is_symlink()
    assert resolv_conf.readlink() == stub
    assert not kept_original.is_symlink()


def test_with_no_kept_file_and_no_resolved_the_fallback_is_written(
    resolv_conf, kept_original, is_resolved_enabled
):
    resolver.point_at("192.168.8.1")
    assert not kept_original.exists()

    handed = resolver.hand_back(fallback_address="223.5.5.5")

    assert handed == ROUTER_RESOLVER_TO_FALLBACK
    assert "nameserver 223.5.5.5" in resolv_conf.read_text()
    assert "192.168.8.1" not in resolv_conf.read_text()


def test_with_nothing_to_put_back_and_no_fallback_the_file_stays(
    resolv_conf, is_resolved_enabled
):
    resolver.point_at("192.168.8.1")

    assert resolver.hand_back() == ""
    assert "nameserver 192.168.8.1" in resolv_conf.read_text()


def test_resolved_comes_before_the_kept_file(
    resolv_conf, kept_original, is_resolved_enabled
):
    resolv_conf.write_text("nameserver 192.0.2.53\n")
    resolver.point_at("192.168.8.1")
    is_resolved_enabled["is_enabled"] = True

    handed = resolver.hand_back(fallback_address="223.5.5.5")

    assert handed == ROUTER_RESOLVER_TO_RESOLVED
    assert resolv_conf.readlink() == resolver.RESOLVER_RESOLVED_STUB
    assert not kept_original.exists()


def test_handing_back_passes_the_direct_resolver_as_the_fallback(monkeypatch):
    handed = {}

    def hand_back(**keywords):
        handed.update(keywords)
        return ROUTER_RESOLVER_TO_FALLBACK

    monkeypatch.setattr(routes.RouterRulesetApplier, "flush", lambda self: None)
    monkeypatch.setattr(routes.stack, "stand_up", list)
    monkeypatch.setattr(routes.resolver, "hand_back", hand_back)
    monkeypatch.setattr(
        routes,
        "read_config",
        lambda name: {"direct_dns": {"address": "223.5.5.5", "port": 53}},
    )

    changes = routes.hand_back(RouterNetworkConfig(mode=ROUTER_MODE_ROUTER))

    assert handed == {"fallback_address": "223.5.5.5"}
    assert changes[-1] == "name resolution points at the direct resolver 223.5.5.5"
