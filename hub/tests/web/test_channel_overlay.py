"""The overlays' join material, read from what the box stores and runs.

NetBird hands its kept setup key, its management plane and the hub's overlay
name; EasyTier in manual mode its network name, its secret and the uplink
address its engine listens on, and in console mode the console's address and
secure mode; both EasyTier shapes name the hub's own overlay address. No
overlay, no kept key, no network, no address, no console address and a
locked vault each read as none. Two overlays running hand two objects,
NetBird's first.
"""

import pytest

from neutrino_hub import edition
from neutrino_hub.modules.easytier.config import EasyTierConfig
from neutrino_hub.modules.easytier.ops import EASYTIER_CONFIG_NAME, EasyTierInstance
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig
from neutrino_hub.utils.json_file import write_config
from neutrino_hub.web import channel_overlay
from tests.conftest import unlock_vault

SETUP_KEY = "A1B2C3D4-0000-4000-8000-000000000000"  # scan: allow
CONSOLE = "tcp://et-web.console.easytier.net:22020/etk_example"  # scan: allow


class FakeRuntime:
    def __init__(self, *providers: str):
        overlays = [
            {"provider": provider} for provider in providers if provider != "none"
        ]
        self._network = RouterNetworkConfig.from_dict(
            {
                "mode": "router",
                "interfaces": [
                    {
                        "name": "enp1s0",
                        "role": "lan",
                        "lan": {"address": "192.168.100.1", "prefix_len": 24},
                    },
                    {"name": "enp2s0", "role": "wan"},
                ],
                "overlays": overlays,
            }
        )

    def network(self) -> RouterNetworkConfig:
        return self._network


class FakeReader:
    def survey(self):
        from neutrino_hub.modules.netbird.ops import NetbirdState

        return NetbirdState(
            is_installed=True, fqdn="hub.netbird.cloud", netbird_ip="100.88.0.1/16"
        )


@pytest.fixture
def box(monkeypatch, tmp_path):
    """An open vault, config/ under tmp, a fake daemon and two addresses."""
    unlock_vault(monkeypatch, tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", config_dir)
    if edition.has_feature("netbird"):
        monkeypatch.setattr(
            "neutrino_hub.modules.netbird.overlay_part.NetbirdStatusReader", FakeReader
        )
    monkeypatch.setattr(channel_overlay, "EasyTierStatusReader", FakeInstances)
    addresses = {"enp1s0": "192.168.100.1/24", "enp2s0": "203.0.113.7/24"}
    monkeypatch.setattr(channel_overlay, "device_addresses", lambda: dict(addresses))
    return addresses


def keep_setup_key(management_url: str = "") -> None:
    from neutrino_hub.modules.netbird.config import NetbirdConfig, write_stored

    config = NetbirdConfig()
    config.set_setup_key(SETUP_KEY, management_url)
    write_stored(config)


def store_network(address: str = "") -> None:
    config = EasyTierConfig(network_name="neutrino-1234", address=address)
    config.set_secret("a-network-secret")
    write_config(EASYTIER_CONFIG_NAME, config.to_dict())


def store_console(address: str = CONSOLE, *, is_secure_mode: bool = True) -> None:
    config = EasyTierConfig(mode="console", is_secure_mode=is_secure_mode)
    if address:
        config.set_config_server(address)
    write_config(EASYTIER_CONFIG_NAME, config.to_dict())


class FakeInstances:
    """An engine running the console's network at one address."""

    addresses: list = []

    def instances(self) -> list:
        return [
            EasyTierInstance(
                instance_name="",
                network_name="home",
                address=address,
                hostname="neutrino",
            )
            for address in FakeInstances.addresses
        ]


def material_of(runtime) -> "dict | None":
    """The one overlay's material, None when it has none."""
    materials = channel_overlay.overlay_materials(runtime)
    assert len(materials) <= 1
    return materials[0] if materials else None


@pytest.mark.feature("netbird")
def test_two_overlays_hand_two_objects_netbird_first(box):
    keep_setup_key()
    store_network()

    materials = channel_overlay.overlay_materials(FakeRuntime("easytier", "netbird"))

    assert [material["provider"] for material in materials] == ["netbird", "easytier"]


@pytest.mark.feature("netbird")
def test_an_overlay_with_nothing_to_join_is_left_out_of_two(box):
    store_network()

    materials = channel_overlay.overlay_materials(FakeRuntime("netbird", "easytier"))

    assert [material["provider"] for material in materials] == ["easytier"]


@pytest.mark.feature("netbird")
def test_netbird_hands_its_key_its_plane_and_the_hubs_name(box):
    keep_setup_key("https://nb.example.org")

    material = material_of(FakeRuntime("netbird"))

    assert material == {
        "provider": "netbird",
        "setup_key": SETUP_KEY,
        "management_url": "https://nb.example.org",
        "fqdn": "hub.netbird.cloud",
        "hub_address": "100.88.0.1",
    }


@pytest.mark.feature("netbird")
def test_netbird_without_a_kept_key_is_none(box):
    assert material_of(FakeRuntime("netbird")) is None


def test_easytier_hands_its_name_its_secret_and_the_uplinks_address(box):
    store_network("10.0.0.1/24")

    material = material_of(FakeRuntime("easytier"))

    assert material == {
        "provider": "easytier",
        "mode": "manual",
        "network_name": "neutrino-1234",
        "network_secret": "a-network-secret",
        "peer": "tcp://203.0.113.7:11010",
        "hub_address": "10.0.0.1",
    }


def test_a_manual_network_with_no_address_names_no_hub_address(box):
    store_network()

    material = material_of(FakeRuntime("easytier"))

    assert material["hub_address"] == ""


def test_the_console_hands_its_address_secure_mode_and_the_hubs_address(box):
    store_console()
    FakeInstances.addresses = ["10.126.126.1/24"]

    material = material_of(FakeRuntime("easytier"))

    assert material == {
        "provider": "easytier",
        "mode": "console",
        "config_server": CONSOLE,
        "is_secure_mode": True,
        "hub_address": "10.126.126.1",
    }


def test_the_console_before_the_engine_reports_names_no_hub_address(box):
    store_console(is_secure_mode=False)
    FakeInstances.addresses = []

    material = material_of(FakeRuntime("easytier"))

    assert material["hub_address"] == ""
    assert material["is_secure_mode"] is False


def test_the_console_with_no_address_is_none(box):
    store_console("")

    assert material_of(FakeRuntime("easytier")) is None


def test_easytier_without_a_network_is_none(box):
    assert material_of(FakeRuntime("easytier")) is None


def test_easytier_with_no_address_to_dial_is_none(box):
    store_network()
    box.clear()

    assert material_of(FakeRuntime("easytier")) is None


@pytest.mark.feature("netbird")
def test_no_overlay_is_none_whatever_is_stored(box):
    keep_setup_key()
    store_network()

    assert material_of(FakeRuntime("none")) is None


@pytest.mark.feature("netbird")
def test_a_locked_vault_is_none(box, monkeypatch, tmp_path):
    keep_setup_key()
    store_network()
    monkeypatch.setattr(
        "neutrino_hub.utils.constants.UTILS_STATE_ROOT", tmp_path / "nowhere"
    )

    assert material_of(FakeRuntime("netbird")) is None
    assert material_of(FakeRuntime("easytier")) is None


def test_a_locked_vault_hides_the_console_address(box, monkeypatch, tmp_path):
    store_console()
    monkeypatch.setattr(
        "neutrino_hub.utils.constants.UTILS_STATE_ROOT", tmp_path / "nowhere"
    )

    assert material_of(FakeRuntime("easytier")) is None
