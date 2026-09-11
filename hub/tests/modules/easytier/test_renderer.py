"""The configuration file the engine is run on.

Pure text in, pure text out. What is pinned here is the shape the engine
prints for the same flags, and the one value nobody chooses: the relay
whitelist, which the engine leaves open to every network unless it is told
otherwise.
"""

import pytest

from neutrino_hub.modules.easytier.config import EasyTierConfig
from neutrino_hub.modules.easytier.renderer import render_config


def rendered(**kwargs) -> str:
    config = EasyTierConfig(
        network_name=kwargs.pop("network_name", "neutrino-1234"), **kwargs
    )
    return render_config(config, secret="a-network-secret", hostname="neutrino")


def test_the_network_is_named_with_its_secret():
    text = rendered()

    assert "[network_identity]" in text
    assert 'network_name = "neutrino-1234"' in text
    assert 'network_secret = "a-network-secret"' in text


def test_the_box_answers_on_the_overlay_port():
    text = rendered()

    assert '"tcp://0.0.0.0:11010",' in text
    assert '"udp://0.0.0.0:11010",' in text


def test_this_box_carries_no_other_networks_traffic():
    """The engine relays for everybody unless it is told whom to relay for."""
    assert 'relay_network_whitelist = "neutrino-1234"' in rendered()


def test_the_tunnel_device_is_the_one_the_firewall_names():
    assert 'dev_name = "easytier"' in rendered()


def test_an_address_is_written_and_an_empty_one_is_left_to_the_engine():
    assert 'ipv4 = "10.0.0.1/24"' in rendered(address="10.0.0.1/24")
    assert "ipv4" not in rendered(address="")


def test_every_peer_and_network_gets_its_own_table():
    text = rendered(
        peers=["tcp://198.51.100.7:11010", "txt://network.example.com"],
        exported_networks=["192.168.100.0/24", "10.20.0.0/16"],
    )

    assert text.count("[[peer]]") == 2
    assert 'uri = "txt://network.example.com"' in text
    assert text.count("[[proxy_network]]") == 2
    assert 'cidr = "10.20.0.0/16"' in text


def test_the_boxs_own_name_is_used_when_the_configuration_names_none():
    assert 'hostname = "neutrino"' in rendered()
    assert 'hostname = "laptop"' in rendered(hostname="laptop")


def test_a_quote_cannot_end_a_value_early():
    config = EasyTierConfig(network_name="neutrino-1234", hostname='a"name')

    text = render_config(config, secret='a"secret\\', hostname="neutrino")

    assert 'hostname = "a\\"name"' in text
    assert 'network_secret = "a\\"secret\\\\"' in text  # scan: allow


def test_a_box_with_no_network_renders_nothing():
    with pytest.raises(ValueError):
        render_config(EasyTierConfig(), secret="", hostname="neutrino")
