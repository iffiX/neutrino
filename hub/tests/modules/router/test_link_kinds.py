"""Which interfaces get a role, and which are somebody else's machinery.

Three kinds get a role — a wire, a radio, a cellular modem — with VLANs
because the gateway builds those itself. Everything else a machine carries is
somebody else's: a developer's laptop has docker's bridge and a container's
veth, an appliance has the overlay's tun, a car has a CAN adapter. What each
one is has to be decided from what the kernel says, because there may be no
network manager to ask.
"""

import pytest

from neutrino_hub.modules.router import link_status
from neutrino_hub.modules.router.link_status import (
    LINK_ARPHRD_ETHER,
    LINK_KIND_ETHERNET,
    LINK_KIND_MODEM,
    LINK_KIND_VLAN,
    LINK_KIND_WIFI,
    _kind_of,
    _signal_percent,
)

# A modem handing up bare IP: the address comes out of the bearer over QMI,
# so nothing here can put one on it.
ARPHRD_RAWIP = 519

# What the kernel calls hardware that is not a network port: a CAN adapter,
# an 802.15.4 radio, an InfiniBand card, a dialer's PPP session.
ARPHRD_CAN = 280
ARPHRD_PPP = 512
ARPHRD_IEEE802154 = 804
ARPHRD_INFINIBAND = 32


@pytest.fixture
def sysfs(tmp_path, monkeypatch):
    """A `/sys/class/net` a test can build interfaces in."""
    monkeypatch.setattr(link_status, "LINK_SYSFS_ROOT", tmp_path)

    def make(
        name: str, *, is_hardware: bool = True, is_radio: bool = False, arphrd=None
    ):
        directory = tmp_path / name
        directory.mkdir(parents=True, exist_ok=True)
        if is_hardware:
            (directory / "device").mkdir(exist_ok=True)
        if is_radio:
            (directory / "phy80211").mkdir(exist_ok=True)
        (directory / "type").write_text(
            str(LINK_ARPHRD_ETHER if arphrd is None else arphrd)
        )
        return name

    return make


def entry(name: str, info_kind: str | None = None) -> dict:
    """One entry of `ip -d -json link show`."""
    if info_kind is None:
        return {"ifname": name}
    return {"ifname": name, "linkinfo": {"info_kind": info_kind}}


# --- what gets a role ---


def test_a_wired_port_is_ethernet(sysfs):
    sysfs("enp1s0")

    assert _kind_of("enp1s0", entry("enp1s0")) == LINK_KIND_ETHERNET


def test_a_radio_is_wifi(sysfs):
    sysfs("wlp3s0", is_radio=True)

    assert _kind_of("wlp3s0", entry("wlp3s0")) == LINK_KIND_WIFI


def test_a_vlan_is_a_vlan_whatever_sysfs_holds(sysfs):
    assert _kind_of("enp1s0.10", entry("enp1s0.10", "vlan")) == LINK_KIND_VLAN


# --- modems, which are not ethernet however they present themselves ---


@pytest.mark.parametrize("name", ["wwan0", "wwp0s20f0u2i12"])
def test_a_cellular_card_speaking_ethernet_is_an_uplink(sysfs, name):
    """In MBIM or ECM mode a 4G card is a port that takes a lease, exactly
    like a wire. The name is all that separates the two, and what it changes
    is only what the card may be used for."""
    sysfs(name)

    assert _kind_of(name, entry(name)) == LINK_KIND_MODEM


def test_a_modem_handing_up_bare_ip_is_left_out(sysfs):
    """`qmi_wwan` in raw-IP mode takes no lease: its address comes out of the
    bearer over QMI. Showing a port nothing here can address is worse than
    not showing it."""
    sysfs("wwan0", arphrd=ARPHRD_RAWIP)

    assert _kind_of("wwan0", entry("wwan0")) is None


def test_a_phone_shared_over_usb_is_a_wired_port(sysfs):
    """USB tethering presents an ethernet device and is named for one. That
    the phone's own uplink is cellular is the phone's business: this end is a
    wire with DHCP behind it, and is indistinguishable from a USB adapter."""
    sysfs("enp0s20u1")

    assert _kind_of("enp0s20u1", entry("enp0s20u1")) == LINK_KIND_ETHERNET


# --- hardware that is not a network port ---


@pytest.mark.parametrize(
    "name,arphrd",
    [
        ("can0", ARPHRD_CAN),
        ("slcan0", ARPHRD_CAN),
        ("wpan0", ARPHRD_IEEE802154),
        ("ib0", ARPHRD_INFINIBAND),
        ("ppp0", ARPHRD_PPP),
    ],
)
def test_a_bus_is_not_offered_as_an_uplink(sysfs, name, arphrd):
    """A CAN adapter has a `device` and a hardware type of its own. Reading
    "not ethernet" as "cellular modem" would offer a car's bus as a way to the
    internet."""
    sysfs(name, arphrd=arphrd)

    assert _kind_of(name, entry(name)) is None


# --- what is somebody else's ---


@pytest.mark.parametrize(
    "name,info_kind",
    [
        ("docker0", "bridge"),
        ("podman0", "bridge"),
        ("virbr0", "bridge"),
        ("br-1a2b3c", "bridge"),
        ("vethf00d", "veth"),
        ("wt0", "tun"),
        ("wg0", "wireguard"),
        ("bond0", "bond"),
        ("vxlan0", "vxlan"),
        ("dummy0", "dummy"),
        ("gre0", "gre"),
    ],
)
def test_an_interface_the_kernel_made_gets_no_role(sysfs, name, info_kind):
    """Every synthesised interface names itself, so one rule covers the lot
    rather than a list of names that has to keep up with what people run."""
    assert _kind_of(name, entry(name, info_kind)) is None


def test_loopback_gets_no_role(sysfs):
    sysfs("lo", is_hardware=False)

    assert _kind_of("lo", entry("lo")) is None


@pytest.mark.parametrize("name", ["ppp0", "bnep0"])
def test_an_interface_with_no_hardware_behind_it_gets_no_role(sysfs, name):
    """A dialer's PPP session and Bluetooth tethering are both real links
    somebody may be using. Neither is a port with hardware behind it, and
    driving one halfway is worse than leaving it to whatever made it."""
    sysfs(name, is_hardware=False)

    assert _kind_of(name, entry(name)) is None


# --- signal ---


@pytest.mark.parametrize(
    "line,percent",
    [
        ("signal: -40 dBm", 100),
        ("signal: -50 dBm", 100),
        ("signal: -75 dBm", 50),
        ("signal: -100 dBm", 0),
        ("signal: -120 dBm", 0),
        ("signal:", None),
    ],
)
def test_strength_reads_the_way_a_person_expects_a_bar_to(line, percent):
    assert _signal_percent(line) == percent
