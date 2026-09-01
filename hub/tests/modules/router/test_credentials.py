"""Reading the wireless networks a machine already knew.

Real file shapes, because these are somebody else's formats and the only way
to know they parse is to parse them. Every fixture here is what the manager
named actually writes.
"""

import pytest

from neutrino_hub.modules.router.constants import (
    ROUTER_KEY_MGMT_NONE,
    ROUTER_KEY_MGMT_PSK,
    ROUTER_KEY_MGMT_SAE,
)
from neutrino_hub.modules.router.credentials import RouterCredentialReader

# A keyfile `nmcli` produces: the passphrase is in the file, and `psk-flags=0`
# says so.
NM_WITH_KEY = """[connection]
id=home
uuid=8f1a0000-0000-4000-8000-000000000001
type=wifi

[wifi]
mode=infrastructure
ssid=home-5g

[wifi-security]
key-mgmt=wpa-psk
psk=hunter2hunter2
psk-flags=0

[ipv4]
method=auto
"""

# The same network on a desktop: the passphrase is in the login keyring and
# the file has none. `psk-flags=1` is the only thing that says so.
NM_AGENT_OWNED = """[connection]
id=office
type=wifi

[wifi]
ssid=office-wifi
hidden=true

[wifi-security]
key-mgmt=wpa-psk
psk-flags=1
"""

NM_ENTERPRISE = """[connection]
id=campus
type=wifi

[wifi]
ssid=eduroam

[wifi-security]
key-mgmt=wpa-eap

[802-1x]
eap=peap;
identity=somebody
"""

NM_ETHERNET = """[connection]
id=Wired connection 1
type=ethernet

[ethernet]

[ipv4]
method=auto
"""

NM_WPA3 = """[connection]
id=new-router
type=wifi

[wifi]
ssid=home-wpa3

[wifi-security]
key-mgmt=sae
psk=a-long-enough-passphrase
psk-flags=0
"""

IWD_PSK = """[Security]
PreSharedKey=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
Passphrase=cafe-guest-2024

[Settings]
AutoConnect=true
"""

WPA_SUPPLICANT = """ctrl_interface=DIR=/run/wpa_supplicant GROUP=netdev
update_config=1
country=GB

network={
    ssid="pi-home"
    psk="raspberry-pi-key"
    key_mgmt=WPA-PSK
}

network={
    ssid="hidden-one"
    scan_ssid=1
    psk=fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210
}

network={
    ssid="cafe"
    key_mgmt=NONE
}
"""

# Exactly what `netplan generate` wrote on Ubuntu 24.04 for one ordinary
# network, captured rather than written from memory. Two things here broke a
# parser that had only ever seen files people wrote: the `P"..."` printf form
# around the name, and a key management naming three schemes at once.
NETPLAN_RENDERED = """ctrl_interface=/run/wpa_supplicant

network={
  ssid=P"probe-ssid"
  key_mgmt=WPA-PSK WPA-PSK-SHA256 SAE
  ieee80211w=1
  psk="probe-passphrase-123"
}
"""


@pytest.fixture
def stores(tmp_path):
    """The four directories a reader is pointed at, all empty to start."""
    directories = tuple(
        tmp_path / name
        for name in ("system-connections", "iwd", "wpa_supplicant", "netplan")
    )
    for directory in directories:
        directory.mkdir(parents=True)
    return directories


def reader_for(stores) -> RouterCredentialReader:
    nm, iwd, wpa, netplan = stores
    return RouterCredentialReader(
        nm_dirs=(nm,), iwd_dir=iwd, wpa_dir=wpa, netplan_dir=netplan
    )


# --- NetworkManager ---


def test_a_passphrase_in_the_file_is_read(stores):
    nm = stores[0]
    (nm / "home.nmconnection").write_text(NM_WITH_KEY)

    found = reader_for(stores).read_all()

    assert len(found) == 1
    assert found[0].ssid == "home-5g"
    assert found[0].key_mgmt == ROUTER_KEY_MGMT_PSK
    assert found[0].psk == "hunter2hunter2"
    assert found[0].source == "inherited:networkmanager"


def test_a_passphrase_in_the_keyring_is_a_network_with_no_secret(stores):
    """`psk-flags=1` means the desktop holds it. The network is still one
    somebody joined, so it is recorded and the panel asks once."""
    nm = stores[0]
    (nm / "office.nmconnection").write_text(NM_AGENT_OWNED)

    found = reader_for(stores).read_all()

    assert len(found) == 1
    assert found[0].ssid == "office-wifi"
    assert found[0].psk == ""
    assert not found[0].has_secret
    assert found[0].is_hidden


def test_wpa3_is_carried_over_as_sae(stores):
    nm = stores[0]
    (nm / "new.nmconnection").write_text(NM_WPA3)

    found = reader_for(stores).read_all()

    assert found[0].key_mgmt == ROUTER_KEY_MGMT_SAE


def test_an_enterprise_network_is_not_imported(stores):
    """Its SSID with no way to authenticate would be a network in the list
    that can never be joined."""
    nm = stores[0]
    (nm / "campus.nmconnection").write_text(NM_ENTERPRISE)

    assert reader_for(stores).read_all() == []


def test_a_wired_connection_is_not_a_wireless_network(stores):
    nm = stores[0]
    (nm / "wired.nmconnection").write_text(NM_ETHERNET)

    assert reader_for(stores).read_all() == []


def test_a_file_that_is_not_a_keyfile_is_not_an_error(stores):
    """The directory is somebody else's and may hold anything."""
    nm = stores[0]
    (nm / "README").write_text("not ini at all\x00\xff")
    (nm / "home.nmconnection").write_text(NM_WITH_KEY)

    assert len(reader_for(stores).read_all()) == 1


# --- iwd ---


def test_iwd_names_the_network_in_the_filename(stores):
    iwd = stores[1]
    (iwd / "cafe-guest.psk").write_text(IWD_PSK)

    found = reader_for(stores).read_all()

    assert found[0].ssid == "cafe-guest"
    assert found[0].psk.startswith("0123456789abcdef")
    assert found[0].source == "inherited:iwd"


def test_an_open_network_iwd_holds_needs_no_key(stores):
    iwd = stores[1]
    (iwd / "airport.open").write_text("[Settings]\nAutoConnect=true\n")

    found = reader_for(stores).read_all()

    assert found[0].key_mgmt == ROUTER_KEY_MGMT_NONE
    assert found[0].has_secret


# --- wpa_supplicant ---


def test_every_network_block_is_read(stores):
    """The store Raspberry Pi OS wrote for years, and already the format the
    hub renders."""
    wpa = stores[2]
    (wpa / "wpa_supplicant.conf").write_text(WPA_SUPPLICANT)

    found = {item.ssid: item for item in reader_for(stores).read_all()}

    assert set(found) == {"pi-home", "hidden-one", "cafe"}
    assert found["pi-home"].psk == "raspberry-pi-key"
    assert found["hidden-one"].is_hidden
    assert found["hidden-one"].psk.startswith("fedcba")
    assert found["cafe"].key_mgmt == ROUTER_KEY_MGMT_NONE


# --- netplan ---


def test_what_netplan_renders_is_read_as_one_ordinary_network(stores):
    """netplan keeps the passphrase in its own YAML and renders it in this
    format, which is why reading it needs no YAML parser."""
    netplan = stores[3]
    (netplan / "wpa-wlan0.conf").write_text(NETPLAN_RENDERED)

    found = reader_for(stores).read_all()

    assert len(found) == 1
    assert found[0].ssid == "probe-ssid"
    assert found[0].psk == "probe-passphrase-123"
    assert found[0].source == "inherited:netplan"


def test_a_name_in_the_printf_form_is_not_read_with_its_prefix(stores):
    """`P"..."` is how wpa_supplicant marks a printf-escaped string, and
    taking the P as part of the name gets a network nothing can join."""
    netplan = stores[3]
    (netplan / "wpa-wlan0.conf").write_text(NETPLAN_RENDERED)

    assert reader_for(stores).read_all()[0].ssid == "probe-ssid"


def test_a_key_management_naming_several_schemes_is_still_a_psk_network(stores):
    """Read as a single value it matches nothing and the network is dropped as
    enterprise, silently. Taken as PSK it associates with an access point in
    either WPA2 or WPA3 transition mode."""
    netplan = stores[3]
    (netplan / "wpa-wlan0.conf").write_text(NETPLAN_RENDERED)

    assert reader_for(stores).read_all()[0].key_mgmt == ROUTER_KEY_MGMT_PSK


# --- across stores ---


def test_the_store_that_has_the_key_wins(stores):
    """A machine that moved from one manager to another may hold the same
    network in both, with the passphrase in only one of them."""
    nm, iwd = stores[0], stores[1]
    (nm / "office.nmconnection").write_text(NM_AGENT_OWNED)
    (iwd / "office-wifi.psk").write_text(IWD_PSK)

    found = reader_for(stores).read_all()

    assert len(found) == 1
    assert found[0].ssid == "office-wifi"
    assert found[0].has_secret


def test_a_machine_with_no_stores_at_all_reads_nothing(tmp_path):
    """Every directory is somebody else's and none has to exist."""
    reader = RouterCredentialReader(
        nm_dirs=(tmp_path / "none",),
        iwd_dir=tmp_path / "gone",
        wpa_dir=tmp_path / "no",
        netplan_dir=tmp_path / "never",
    )

    assert reader.read_all() == []
