"""What the ZFS verbs accept, refused typed before any tool runs."""

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.zfs.config import (
    validate_dataset_path,
    validate_mountpoint,
    validate_pool_name,
    validate_tunables,
    validate_vdev,
)


def code_of(check, *args) -> str:
    with pytest.raises(ModuleApplyError) as refused:
        check(*args)
    return refused.value.code


@pytest.mark.parametrize("name", ["", "Tank", "1st", "a b", "x" * 31, "a\nb"])
def test_a_pool_name_off_the_charset_is_refused(name):
    assert code_of(validate_pool_name, name) == "pool_name_invalid"


@pytest.mark.parametrize("name", ["mirror", "raidz1", "spare", "log", "cache"])
def test_a_name_zpool_means_something_by_is_refused(name):
    assert code_of(validate_pool_name, name) == "pool_name_reserved"


def test_a_sound_pool_name_passes():
    validate_pool_name("tank-01")


def test_a_layout_needs_its_disks():
    validate_vdev("single", ["/dev/disk/by-id/a"])
    validate_vdev("mirror", ["a", "b"])
    validate_vdev("raidz1", ["a", "b", "c"])
    assert code_of(validate_vdev, "raidz2", ["a", "b", "c"]) == "layout_disk_count"
    assert code_of(validate_vdev, "single", ["a", "b"]) == "layout_disk_count"
    assert code_of(validate_vdev, "raidz9", ["a"]) == "layout_unknown"


@pytest.mark.parametrize("path", ["nfs/home", "data", "a-b/c_d"])
def test_a_sound_dataset_path_passes(path):
    validate_dataset_path(path)


@pytest.mark.parametrize("path", ["", "Home", "a//b", "a/", "../x", "a b"])
def test_a_dataset_path_off_the_charset_is_refused(path):
    assert code_of(validate_dataset_path, path) == "dataset_name_invalid"


def test_tunables_must_be_offered_ones():
    validate_tunables("zstd", "128K")
    assert code_of(validate_tunables, "gzip", "128K") == "compression_unknown"
    assert code_of(validate_tunables, "lz4", "3K") == "recordsize_unknown"


def test_a_mountpoint_is_absolute_and_off_the_operating_system():
    validate_mountpoint(None)
    validate_mountpoint("/srv/data")
    assert code_of(validate_mountpoint, "srv/data") == "mountpoint_invalid"
    assert code_of(validate_mountpoint, "/") == "mountpoint_invalid"
    assert code_of(validate_mountpoint, "/srv/../etc") == "mountpoint_invalid"
    assert code_of(validate_mountpoint, "/usr/local") == "mountpoint_forbidden"
    assert code_of(validate_mountpoint, "/etc") == "mountpoint_forbidden"
