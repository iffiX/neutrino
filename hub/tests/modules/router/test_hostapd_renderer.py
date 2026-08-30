"""Rendering the hostapd configuration for a radio serving a network.

Only keys that predate hostapd 2.0 are emitted, deliberately: this box is meant
to run on whatever the distribution ships, and an access point that fails to
start is a LAN that never appears.
"""

import pytest

from neutrino_hub.modules.router.hostapd_renderer import (
    DEFAULT_CHANNEL_2GHZ,
    DEFAULT_CHANNEL_5GHZ,
    RouterHostapdRenderer,
)

from tests.conftest import lan_entry, network_config


def interface(**wifi):
    settings = {"ap_ssid": "neutrino", "ap_passphrase": "hunter2hunter2", **wifi}
    return network_config(
        lan_entry("wlp3s0", address="192.168.101.1", **settings)
    ).interface("wlp3s0")


def directives(text: str) -> dict[str, str]:
    """Parse a rendered hostapd config into key/value pairs."""
    values = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, _, value = stripped.partition("=")
        values[key] = value
    return values


def test_the_radio_is_driven_directly_rather_than_through_a_helper():
    config = directives(RouterHostapdRenderer(interface=interface()).render())

    assert config["interface"] == "wlp3s0"
    assert config["driver"] == "nl80211"
    assert config["ssid"] == "neutrino"


def test_wpa2_is_the_only_thing_offered():
    """An access point with no passphrase is an open route into the LAN."""
    config = directives(RouterHostapdRenderer(interface=interface()).render())

    assert config["wpa"] == "2"
    assert config["wpa_key_mgmt"] == "WPA-PSK"
    assert config["rsn_pairwise"] == "CCMP"
    assert config["wpa_passphrase"] == "hunter2hunter2"


@pytest.mark.parametrize(
    ("band", "hw_mode", "channel"),
    [
        ("bg", "g", DEFAULT_CHANNEL_2GHZ),
        ("a", "a", DEFAULT_CHANNEL_5GHZ),
    ],
)
def test_each_band_picks_a_matching_mode_and_channel(band, hw_mode, channel):
    config = directives(
        RouterHostapdRenderer(interface=interface(ap_band=band)).render()
    )

    assert config["hw_mode"] == hw_mode
    assert config["channel"] == str(channel)


def test_a_known_regulatory_domain_is_declared():
    config = directives(
        RouterHostapdRenderer(interface=interface(), country_code="US").render()
    )

    assert config["country_code"] == "US"
    assert config["ieee80211d"] == "1"


def test_an_unknown_regulatory_domain_is_left_out_rather_than_guessed():
    """A wrong domain can put the radio on channels it may not legally use."""
    config = directives(
        RouterHostapdRenderer(interface=interface(), country_code=None).render()
    )

    assert "country_code" not in config


def test_the_address_file_carries_what_the_unit_needs():
    """hostapd does no addressing, and nothing else on this interface will."""
    rendered = RouterHostapdRenderer(interface=interface()).render_address()

    assert "AP_ADDRESS=192.168.101.1/24" in rendered


def test_nothing_newer_than_hostapd_2_0_is_relied_on():
    """The box is meant to run on whatever the distribution ships.

    Every key here has been in hostapd since well before 2.0, so a rendered
    config works on an older release just as well as the newest one.
    """
    established = {
        "interface",
        "driver",
        "ssid",
        "hw_mode",
        "channel",
        "country_code",
        "ieee80211d",
        "ieee80211n",
        "wmm_enabled",
        "auth_algs",
        "wpa",
        "wpa_key_mgmt",
        "rsn_pairwise",
        "wpa_passphrase",
        "ignore_broadcast_ssid",
    }
    config = directives(
        RouterHostapdRenderer(interface=interface(), country_code="US").render()
    )

    assert set(config) <= established
