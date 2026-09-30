"""One EasyTier network's file: what it names, and the values it refuses.

The file is the hub's own shape less what only a hub does: it listens on
nothing, asks the network for an address, names its instance after the
network so ``easytier-cli -n`` selects it, and carries no RPC portal, which
is the daemon's flag.
"""

import pytest

from neutrino_client.core.easytier_config import (
    is_hostname,
    is_network_name,
    is_peer_uri,
    render_easytier_config,
    safe_hostname,
)

SECRET = "s3cret"  # scan: allow


def rendered(**overrides) -> str:
    values = {
        "network_name": "home",
        "network_secret": SECRET,
        "peer": "tcp://203.0.113.7:11010",
        "hostname": "box",
    }
    values.update(overrides)
    return render_easytier_config(**values)


def test_the_file_names_the_instance_the_network_and_the_peer():
    text = rendered()

    assert text.splitlines()[:4] == [
        'instance_name = "home"',
        'hostname = "box"',
        "dhcp = true",
        "listeners = []",
    ]
    assert '[network_identity]\nnetwork_name = "home"\n' in text
    assert f'network_secret = "{SECRET}"' in text
    assert '[[peer]]\nuri = "tcp://203.0.113.7:11010"' in text
    assert 'relay_network_whitelist = "home"' in text


def test_the_file_names_no_portal_no_device_and_no_export():
    text = rendered()

    for absent in ("rpc_portal", "dev_name", "proxy_network", "ipv4"):
        assert absent not in text


def test_a_secret_with_quotes_and_line_ends_stays_one_string():
    text = rendered(network_secret='a"b\\c\nd')

    assert 'network_secret = "a\\"b\\\\c\\nd"' in text  # scan: allow


@pytest.mark.parametrize(
    "overrides",
    [
        {"network_name": "../etc"},
        {"network_name": ""},
        {"peer": "file:///etc/passwd"},
        {"hostname": "a b"},
        {"network_secret": ""},
    ],
)
def test_a_value_the_file_may_not_carry_is_refused(overrides):
    with pytest.raises(ValueError):
        rendered(**overrides)


@pytest.mark.parametrize(
    "name, is_ok",
    [
        ("home", True),
        ("home.net-1_a", True),
        ("..", False),
        ("a/b", False),
        ("x" * 64, True),
        ("x" * 65, False),
        ("", False),
    ],
)
def test_network_names(name, is_ok):
    assert is_network_name(name) is is_ok


@pytest.mark.parametrize(
    "uri, is_ok",
    [
        ("tcp://203.0.113.7:11010", True),
        ("udp://hub.example:11010", True),
        ("wss://hub.example:443/", True),
        ("tcp://203.0.113.7", False),
        ("tcp://203.0.113.7:0", False),
        ("ring://x:1", False),
        ("tcp://u@h:1", False),
        ("tcp://h:1/path", False),
        ('tcp://h:1"', False),
        ("tcp://h:99999", False),
    ],
)
def test_peer_uris(uri, is_ok):
    assert is_peer_uri(uri) is is_ok


def test_a_hostname_is_cut_to_what_a_file_may_carry():
    assert safe_hostname("Alice's MacBook") == "Alice-s-MacBook"
    assert safe_hostname("") == "neutrino-client"
    assert is_hostname(safe_hostname("x" * 100))
