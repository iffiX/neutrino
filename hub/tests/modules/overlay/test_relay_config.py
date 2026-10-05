"""The relay's settings as config/overlay/relay.json stores them.

A missing file is a relay that is off and not configured, the address the
relay adds to ``urls`` puts an IPv6 host in brackets, and a host or account
that could reach the root command line as an option is refused.
"""

import pytest

from neutrino_hub.modules.overlay.relay_config import (
    OverlayRelayConfig,
    is_account_refused,
    is_host_refused,
    read_relay,
    write_relay,
)


@pytest.fixture
def config_dir(monkeypatch, tmp_path):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    return tmp_path


def test_a_box_with_no_file_has_a_relay_that_is_off(config_dir):
    relay = read_relay()

    assert relay == OverlayRelayConfig()
    assert relay.is_enabled is False
    assert relay.has_settings is False
    assert (relay.ssh_port, relay.public_port) == (22, 8443)


def test_what_is_written_reads_back(config_dir):
    written = OverlayRelayConfig(
        is_enabled=True,
        host="vps.example.org",
        ssh_port=2222,
        account="relay",
        key_id="k1",
        public_port=18443,
    )

    write_relay(written)

    assert read_relay() == written
    assert (config_dir / "overlay" / "relay.json").is_file()


def test_the_relay_is_configured_by_a_host_an_account_and_a_key():
    assert OverlayRelayConfig(host="h", account="a", key_id="k").has_settings
    assert not OverlayRelayConfig(host="h", account="a").has_settings
    assert not OverlayRelayConfig(host="h", key_id="k").has_settings
    assert not OverlayRelayConfig(account="a", key_id="k").has_settings


@pytest.mark.parametrize(
    ("host", "url"),
    [
        ("203.0.113.5", "https://203.0.113.5:18443"),
        ("vps.example.org", "https://vps.example.org:18443"),
        ("2001:db8::5", "https://[2001:db8::5]:18443"),
        ("", ""),
    ],
)
def test_the_address_puts_an_ipv6_host_in_brackets(host, url):
    assert OverlayRelayConfig(host=host, public_port=18443).url == url


@pytest.mark.parametrize("host", ["", "a b", "vps\t", "-oProxyCommand=x"])
def test_a_host_that_could_reach_the_command_line_as_an_option_is_refused(host):
    assert is_host_refused(host)


@pytest.mark.parametrize("account", ["", "re lay", "-l", "relay@vps"])
def test_an_account_that_could_split_or_hold_a_host_is_refused(account):
    assert is_account_refused(account)


def test_an_ordinary_host_and_account_pass():
    assert not is_host_refused("vps.example.org")
    assert not is_account_refused("relay")


def test_a_relay_with_a_login_is_configured_and_logs_in_with_its_password(
    config_dir,
):
    written = OverlayRelayConfig(host="h", account="a", login_id="l1")
    write_relay(written)

    assert read_relay() == written
    assert written.has_settings
    assert written.is_password_login
    assert not OverlayRelayConfig(host="h", account="a", key_id="k").is_password_login
