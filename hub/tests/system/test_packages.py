"""What the package manager installs, and who says so.

The dependency field of every package is generated from one list in
`constants.py`, because the two used to be written separately and drifted: the
`.deb` declared five packages while the installer went on to fetch twelve at
runtime, and installing NetworkManager from a running installer is what once
took a gateway off the network until it was rebooted.
"""

import pytest

from neutrino_hub.system.constants import (
    SYSTEM_CHECKOUT_PACKAGES,
    SYSTEM_PACKAGE_NAMES,
    SYSTEM_RUNTIME_PACKAGES,
    SYSTEM_WIFI_PACKAGES,
)
from neutrino_hub.system.package_manager import packages_for

FAMILIES = tuple(SYSTEM_PACKAGE_NAMES)


@pytest.mark.parametrize("family", FAMILIES)
def test_every_family_spells_every_runtime_package(family):
    """A name nobody mapped is a name that family already spells our way."""
    named = packages_for(family, SYSTEM_RUNTIME_PACKAGES)

    assert len(named) == len(SYSTEM_RUNTIME_PACKAGES)
    assert all(name for name in named)


def test_the_families_disagree_only_where_they_were_measured_to():
    """Measured in containers on 2026-09-01. Debian is the family that splits
    a daemon from its binary, and the only one that spells the supplicant
    without an underscore."""
    debian = packages_for("debian", SYSTEM_RUNTIME_PACKAGES)
    rhel = packages_for("rhel", SYSTEM_RUNTIME_PACKAGES)
    arch = packages_for("arch", SYSTEM_RUNTIME_PACKAGES)

    # smbclient is the client tool the file-service probe runs; RHEL ships
    # it inside samba-client, measured in a fedora container.
    debian_only = {
        "iproute2",
        "dnsmasq-base",
        "dhcpcd-base",
        "wpasupplicant",
        "smbclient",
    }
    assert set(debian) - set(rhel) == debian_only
    assert set(rhel) - set(debian) == {
        "iproute",
        "dnsmasq",
        "dhcpcd",
        "wpa_supplicant",
        "samba-client",
    }
    assert set(debian) - set(arch) == {"dnsmasq-base", "dhcpcd-base", "wpasupplicant"}


def test_nothing_installed_as_a_dependency_manages_a_network():
    """A dependency lands before any of the hub's code runs, and on Debian
    installing a service starts it: NetworkManager pulled in that way took the
    interface on a machine the hub was only ever going to answer on."""
    managers = ("network-manager", "networkmanager", "NetworkManager", "netplan")
    for family in ("debian", "rhel", "arch"):
        named = packages_for(family, SYSTEM_RUNTIME_PACKAGES)
        assert not set(named) & set(managers)


def test_the_dnsmasq_debian_installs_brings_no_unit_with_it():
    """The packaged unit only competes with `neutrino_hub_dnsmasq` for port
    53; `dnsmasq-base` is the same binary without one."""
    assert "dnsmasq-base" in packages_for("debian", SYSTEM_RUNTIME_PACKAGES)
    assert "dnsmasq" not in packages_for("debian", SYSTEM_RUNTIME_PACKAGES)


def test_no_package_depends_on_a_system_python():
    """The whole point of carrying an interpreter is not needing theirs."""
    assert "python3-venv" in SYSTEM_CHECKOUT_PACKAGES
    assert "python3-venv" not in SYSTEM_RUNTIME_PACKAGES
    assert not any("python" in name for name in SYSTEM_RUNTIME_PACKAGES)


def test_a_checkout_package_a_family_builds_in_is_left_out():
    """RHEL and Arch ship venv inside the interpreter; asking for it fails."""
    assert packages_for("rhel", SYSTEM_CHECKOUT_PACKAGES) == []
    assert packages_for("arch", SYSTEM_CHECKOUT_PACKAGES) == []
    assert packages_for("debian", SYSTEM_CHECKOUT_PACKAGES) == ["python3-venv"]


def test_wifi_is_wanted_rather_than_needed():
    """A gateway with no radio routes perfectly well without hostapd."""
    assert SYSTEM_WIFI_PACKAGES == ("hostapd",)
    assert "hostapd" not in SYSTEM_RUNTIME_PACKAGES
