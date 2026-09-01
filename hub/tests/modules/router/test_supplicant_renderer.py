"""What a radio is told to join, and what it is never told.

The supplicant picks among the networks itself — it scans, sees which are in
range, and takes the highest priority of those. So what this renders is a list
and an order, never a decision about which network the box is on.
"""

import pytest

from neutrino_hub.modules.router.connections import (
    RouterConnection,
    RouterConnectionSet,
)
from neutrino_hub.modules.router.supplicant_renderer import RouterSupplicantRenderer


def render(*connections: RouterConnection, country_code: str | None = None) -> str:
    return RouterSupplicantRenderer(
        connections=RouterConnectionSet(connections=list(connections)),
        country_code=country_code,
    ).render()


def test_the_supplicant_may_never_write_back_over_the_file():
    """It is rendered from `config/`. A supplicant that saved into it would
    put a network somewhere the next render silently drops again."""
    assert "update_config=0" in render()


def test_the_control_socket_is_the_hub_s_own():
    """The machine's own supplicant may be running, and two in one directory
    is a collision that shows up as whichever started second failing."""
    assert "DIR=/run/neutrino/wpa_supplicant" in render()


def test_a_radio_with_nothing_to_join_still_gets_a_working_file():
    """The supplicant runs, finds nothing, and is there the moment somebody
    picks a network in the panel."""
    text = render()

    assert "ctrl_interface" in text
    assert "network={" not in text


def test_a_passphrase_is_quoted_and_a_derived_key_is_not():
    text = render(
        RouterConnection(ssid="typed", psk="hunter2hunter2"),
        RouterConnection(ssid="derived", psk="a" * 64),
    )

    assert '    psk="hunter2hunter2"' in text
    assert f"    psk={'a' * 64}" in text


@pytest.mark.parametrize("secret", ["0x" + "0" * 62, "1_" * 32])
def test_something_that_only_looks_like_a_key_is_quoted(secret):
    """``int(value, 16)`` accepts a `0x` prefix and underscores, so a
    passphrase of exactly the right length made of those would be written as a
    derived key and never associate."""
    assert f'psk="{secret}"' in render(RouterConnection(ssid="x", psk=secret))


def test_wpa3_carries_its_passphrase_and_requires_protected_frames():
    """SAE derives its key during the handshake, so a pre-derived one is no
    use, and it cannot associate without management frame protection."""
    text = render(RouterConnection(ssid="new", key_mgmt="SAE", psk="a-long-passphrase"))

    assert "    key_mgmt=SAE" in text
    assert "    ieee80211w=2" in text
    assert '    sae_password="a-long-passphrase"' in text  # scan: allow
    assert "psk=" not in text


def test_an_open_network_is_written_with_no_key_at_all():
    text = render(RouterConnection(ssid="cafe", key_mgmt="NONE"))

    assert "    key_mgmt=NONE" in text
    assert "psk" not in text


def test_a_hidden_network_is_probed_for_by_name():
    assert "    scan_ssid=1" in render(
        RouterConnection(ssid="quiet", psk="x" * 12, is_hidden=True)
    )


def test_a_network_whose_key_could_not_be_read_is_left_out():
    """The supplicant would take it, try it, and fail every time the network
    came into range — which reads as a radio that cannot connect rather than
    as a passphrase nobody has typed yet."""
    text = render(
        RouterConnection(ssid="known", psk="works-fine"),
        RouterConnection(ssid="in-the-keyring", psk=""),
    )

    assert "known" in text
    assert "in-the-keyring" not in text


def test_the_preferred_network_comes_first():
    text = render(
        RouterConnection(ssid="guest", psk="x" * 12, priority=1),
        RouterConnection(ssid="home", psk="x" * 12, priority=10),
    )

    assert text.index('ssid="home"') < text.index('ssid="guest"')


def test_two_renders_of_one_configuration_are_the_same_text():
    """A file that reshuffles between runs restarts the radio for nothing."""
    connections = [
        RouterConnection(ssid=name, psk="x" * 12) for name in ("b", "a", "c")
    ]

    assert render(*connections) == render(*reversed(connections))


def test_a_name_that_could_end_the_string_early_is_escaped():
    """An SSID may hold a quote or a backslash, and one that closed the string
    would put the rest of the name into the file as configuration."""
    text = render(RouterConnection(ssid='say "hi"\\', psk="x" * 12))

    assert '    ssid="say \\"hi\\"\\\\"' in text


def test_the_regulatory_domain_is_written_only_when_it_is_known():
    """A wrong domain hides the channels a network may be broadcasting on."""
    assert "country=GB" in render(country_code="GB")
    assert "country=" not in render()
