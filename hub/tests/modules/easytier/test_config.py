"""What a network is, and what the panel refuses to store as one.

The secret is the whole of the network's security: it admits a node and keys
the traffic. So the sealing is pinned here, and so is every refusal that keeps
a name, an address or a peer from reaching the engine as something it would
read differently than it looks.
"""

import pytest

from neutrino_hub.modules.easytier.config import (
    EasyTierConfig,
    generated_address,
    generated_name,
    generated_secret,
    validate_address,
    validate_name,
    validate_network,
    validate_peer,
)
from tests.conftest import unlock_vault


@pytest.fixture
def vault(monkeypatch, tmp_path):
    """A box whose vault is open, so a secret can be sealed."""
    return unlock_vault(monkeypatch, tmp_path)


def test_the_secret_is_sealed_and_comes_back(vault):
    config = EasyTierConfig(network_name="neutrino-1234")
    config.set_secret("a-network-secret")

    assert config.secret() == "a-network-secret"
    assert "a-network-secret" not in str(config.to_dict())
    assert config.is_configured


def test_a_stored_network_survives_a_round_trip(vault):
    config = EasyTierConfig(
        network_name="neutrino-1234",
        address="10.0.0.1/24",
        peers=["tcp://198.51.100.7:11010"],
        exported_networks=["192.168.100.0/24"],
    )
    config.set_secret("a-network-secret")

    parsed = EasyTierConfig.from_dict(config.to_dict())

    assert parsed.network_name == "neutrino-1234"
    assert parsed.address == "10.0.0.1/24"
    assert parsed.peers == ["tcp://198.51.100.7:11010"]
    assert parsed.exported_networks == ["192.168.100.0/24"]
    assert parsed.secret() == "a-network-secret"


def test_a_box_with_no_network_is_not_configured():
    assert not EasyTierConfig().is_configured
    assert EasyTierConfig().secret() == ""


def test_an_empty_secret_is_refused(vault):
    with pytest.raises(ValueError):
        EasyTierConfig().set_secret("")


# --- generation -------------------------------------------------------------


def test_a_generated_network_is_its_own():
    assert generated_name() != generated_name()
    assert generated_secret() != generated_secret()
    assert len(generated_secret()) >= 24


def test_the_generated_address_is_the_one_a_joining_machine_lands_beside():
    """The engine's own automatic addressing starts there, so a machine that
    joins with nothing but `--dhcp` is on the same network as this box."""
    assert generated_address(["192.168.100.0/24"]) == "10.0.0.1/24"


def test_a_box_already_on_that_network_is_given_another():
    address = generated_address(["10.0.0.1/24"])

    assert address != "10.0.0.1/24"
    assert address.startswith("10.")
    assert address.endswith("/24")


# --- refusals ---------------------------------------------------------------


@pytest.mark.parametrize("name", ["neutrino-1234", "home_net", "a"])
def test_a_name_the_whitelist_can_carry_is_taken(name):
    validate_name(name)


@pytest.mark.parametrize("name", ["", "two words", "star*", "a" * 65, "semi;colon"])
def test_a_name_that_could_hide_in_a_whitelist_is_refused(name):
    with pytest.raises(ValueError):
        validate_name(name)


@pytest.mark.parametrize("address", ["", "10.0.0.1/24", "10.13.2.9/16"])
def test_an_address_with_its_prefix_is_taken(address):
    validate_address(address)


@pytest.mark.parametrize("address", ["10.0.0.1", "not-an-address", "fd00::1/64"])
def test_an_address_the_engine_would_not_take_is_refused(address):
    with pytest.raises(ValueError):
        validate_address(address)


@pytest.mark.parametrize(
    "uri",
    [
        "tcp://198.51.100.7:11010",
        "udp://198.51.100.7:11010",
        "wss://relay.example.com:11012",
        "https://discovery.example.com/peer",
        "txt://network.example.com",
    ],
)
def test_an_address_the_engine_dials_is_taken(uri):
    validate_peer(uri)


@pytest.mark.parametrize(
    "uri", ["", "198.51.100.7:11010", "tcp://198.51.100.7", "ftp://example.com"]
)
def test_an_address_the_engine_would_not_dial_is_refused(uri):
    with pytest.raises(ValueError):
        validate_peer(uri)


def test_a_network_is_taken_and_the_whole_internet_is_not():
    validate_network("192.168.100.0/24")
    with pytest.raises(ValueError):
        validate_network("0.0.0.0/0")
    with pytest.raises(ValueError):
        validate_network("not-a-network")
