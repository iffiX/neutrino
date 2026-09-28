"""The overlay's join material, read from what the box stores and runs.

NetBird hands its kept setup key, its management plane and the hub's overlay
name; EasyTier its network name, its secret and the uplink address its engine
listens on. No overlay, no kept key, no network, no address and a locked
vault each read as none.
"""

import pytest

from neutrino_hub.modules.easytier.config import EasyTierConfig
from neutrino_hub.modules.easytier.ops import EASYTIER_CONFIG_NAME
from neutrino_hub.modules.netbird.config import NetbirdConfig, write_stored
from neutrino_hub.modules.netbird.ops import NetbirdState
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig
from neutrino_hub.utils.json_file import write_config
from neutrino_hub.web import channel_overlay
from tests.conftest import unlock_vault

SETUP_KEY = "A1B2C3D4-0000-4000-8000-000000000000"  # scan: allow


class FakeRuntime:
    def __init__(self, provider: str):
        overlays = [] if provider == "none" else [{"provider": provider}]
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
    def survey(self) -> NetbirdState:
        return NetbirdState(is_installed=True, fqdn="hub.netbird.cloud")


@pytest.fixture
def box(monkeypatch, tmp_path):
    """An open vault, config/ under tmp, a fake daemon and two addresses."""
    unlock_vault(monkeypatch, tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", config_dir)
    monkeypatch.setattr(channel_overlay, "NetbirdStatusReader", FakeReader)
    addresses = {"enp1s0": "192.168.100.1/24", "enp2s0": "203.0.113.7/24"}
    monkeypatch.setattr(channel_overlay, "device_addresses", lambda: dict(addresses))
    return addresses


def keep_setup_key(management_url: str = "") -> None:
    config = NetbirdConfig()
    config.set_setup_key(SETUP_KEY, management_url)
    write_stored(config)


def store_network() -> None:
    config = EasyTierConfig(network_name="neutrino-1234")
    config.set_secret("a-network-secret")
    write_config(EASYTIER_CONFIG_NAME, config.to_dict())


def test_netbird_hands_its_key_its_plane_and_the_hubs_name(box):
    keep_setup_key("https://nb.example.org")

    material = channel_overlay.overlay_material(FakeRuntime("netbird"))

    assert material == {
        "provider": "netbird",
        "setup_key": SETUP_KEY,
        "management_url": "https://nb.example.org",
        "fqdn": "hub.netbird.cloud",
    }


def test_netbird_without_a_kept_key_is_none(box):
    assert channel_overlay.overlay_material(FakeRuntime("netbird")) is None


def test_easytier_hands_its_name_its_secret_and_the_uplinks_address(box):
    store_network()

    material = channel_overlay.overlay_material(FakeRuntime("easytier"))

    assert material == {
        "provider": "easytier",
        "network_name": "neutrino-1234",
        "network_secret": "a-network-secret",
        "peer": "tcp://203.0.113.7:11010",
    }


def test_easytier_without_a_network_is_none(box):
    assert channel_overlay.overlay_material(FakeRuntime("easytier")) is None


def test_easytier_with_no_address_to_dial_is_none(box):
    store_network()
    box.clear()

    assert channel_overlay.overlay_material(FakeRuntime("easytier")) is None


def test_no_overlay_is_none_whatever_is_stored(box):
    keep_setup_key()
    store_network()

    assert channel_overlay.overlay_material(FakeRuntime("none")) is None


def test_a_locked_vault_is_none(box, monkeypatch, tmp_path):
    keep_setup_key()
    store_network()
    monkeypatch.setattr(
        "neutrino_hub.utils.constants.UTILS_STATE_ROOT", tmp_path / "nowhere"
    )

    assert channel_overlay.overlay_material(FakeRuntime("netbird")) is None
    assert channel_overlay.overlay_material(FakeRuntime("easytier")) is None
