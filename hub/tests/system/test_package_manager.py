"""Choosing a package manager, and reading the versions it reports.

The version strings here are the ones the distributions actually print, read
off Debian 12, Ubuntu 22.04, Fedora 41 and Arch. A floor that a module writes
against upstream has to survive every way a distribution decorates one.
"""

import pytest

from neutrino_hub.system import machine
from neutrino_hub.system.package_manager import (
    AptPackageController,
    DnfPackageController,
    PacmanPackageController,
    current,
    is_version_at_least,
)
from neutrino_hub.utils.subprocess_run import CommandError

# What `podman` reports, per distribution, against the 4.4 floor Quadlet sets.
PODMAN_VERSIONS = {
    "4.3.1+ds1-8+deb12u1+b3": False,
    "3.4.4+ds1-1ubuntu1.22.04.3": False,
    "4.9": True,
    "5.6.2": True,
    "6.1.0-1": True,
}


@pytest.mark.parametrize("found,is_met", PODMAN_VERSIONS.items())
def test_the_quadlet_floor_reads_every_distributions_podman(found, is_met):
    assert is_version_at_least(found, "4.4") is is_met


def test_an_epoch_does_not_win_the_comparison():
    """`2:4.24.6-1` is samba on Arch; the epoch is the distribution's, not upstream's."""
    assert is_version_at_least("2:4.24.6-1", "4.15") is True
    assert is_version_at_least("1:6.15", "5.0") is True


def test_a_longer_floor_is_not_met_by_a_shorter_version():
    assert is_version_at_least("4.4", "4.4.1") is False
    assert is_version_at_least("4.4", "4.4") is True


def test_a_version_with_no_numbers_meets_nothing():
    """apt-cache prints `(none)` for a package the distribution does not have."""
    assert is_version_at_least("(none)", "4.4") is False
    assert is_version_at_least("", "4.4") is False


def test_the_upstream_part_ends_where_the_distribution_decoration_starts():
    """Ubuntu's `.22.04.` would otherwise be read as two more version fields."""
    assert is_version_at_least("3.4.4+ds1-1ubuntu1.22.04.3", "3.5") is False


@pytest.mark.parametrize(
    "family,expected",
    [
        ("debian", AptPackageController),
        ("rhel", DnfPackageController),
        ("arch", PacmanPackageController),
    ],
)
def test_each_family_gets_its_own_tool(monkeypatch, family, expected):
    monkeypatch.setattr(
        "neutrino_hub.system.package_manager.distribution_family", lambda: family
    )
    assert isinstance(current(), expected)


def test_an_unknown_distribution_is_refused_by_name(monkeypatch):
    """The report says what was found, so it is actionable rather than a shrug."""
    monkeypatch.setattr(
        "neutrino_hub.system.package_manager.distribution_family", lambda: ""
    )
    monkeypatch.setattr(
        "neutrino_hub.system.package_manager.distribution_name", lambda: "Plan 9"
    )
    with pytest.raises(CommandError, match="Plan 9"):
        current()


def test_a_derivative_lands_in_its_parents_family(tmp_path, monkeypatch):
    """ID_LIKE is what puts Linux Mint and Rocky where they belong."""
    release = tmp_path / "os-release"
    release.write_text(
        'ID=rocky\nID_LIKE="rhel centos fedora"\nPRETTY_NAME="Rocky Linux 9"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(machine, "OS_RELEASE_PATH", release)
    assert machine.distribution_family() == "rhel"
    assert machine.distribution_name() == "Rocky Linux 9"


def test_an_unreadable_os_release_is_no_family(tmp_path, monkeypatch):
    monkeypatch.setattr(machine, "OS_RELEASE_PATH", tmp_path / "absent")
    assert machine.distribution_family() == ""
    assert machine.distribution_name() == "unknown"


def test_a_module_names_the_distributions_it_installs_on(tmp_path, monkeypatch):
    release = tmp_path / "os-release"
    release.write_text('ID=arch\nPRETTY_NAME="Arch Linux"\n', encoding="utf-8")
    monkeypatch.setattr(machine, "OS_RELEASE_PATH", release)

    assert machine.require_distribution({"arch": ("podman",)}, "podman") == ("podman",)
    with pytest.raises(RuntimeError, match="Arch Linux"):
        machine.require_distribution({"debian": ("zfsutils-linux",)}, "ZFS")


def test_a_family_listed_as_unsupported_is_refused(tmp_path, monkeypatch):
    """`None` says the distribution was considered and has no such package."""
    release = tmp_path / "os-release"
    release.write_text('ID=fedora\nPRETTY_NAME="Fedora 41"\n', encoding="utf-8")
    monkeypatch.setattr(machine, "OS_RELEASE_PATH", release)
    with pytest.raises(RuntimeError, match="Fedora 41"):
        machine.require_distribution(
            {"debian": ("zfsutils-linux",), "rhel": None}, "ZFS"
        )
