"""A volume's folder as the Podman machine names it, and back."""

import pytest

from neutrino_agent.modules.podman.machine_paths import (
    is_shared_source,
    split_volume,
    to_host_source,
    to_machine,
    to_machine_source,
)


@pytest.mark.parametrize(
    "volume, os_name, split",
    [
        ("C:\\data:/data", "windows", ("C:\\data", "/data")),
        ("C:\\data:/data:ro", "windows", ("C:\\data", "/data:ro")),
        ("webdata:/data", "windows", ("webdata", "/data")),
        ("C:\\data", "windows", ("C:\\data", "")),
        ("/Users/me:/data", "darwin", ("/Users/me", "/data")),
        ("C:\\data:/data", "darwin", ("C", "\\data:/data")),
    ],
)
def test_a_volume_splits_at_the_colon_after_a_windows_drive(volume, os_name, split):
    assert split_volume(volume, os_name=os_name) == split


@pytest.mark.parametrize(
    "source, os_name, is_shared",
    [
        ("C:\\data", "windows", True),
        ("z:/x", "windows", True),
        ("\\\\server\\share", "windows", False),
        ("/srv/data", "windows", False),
        ("/Users/me/site", "darwin", True),
        ("/Users", "darwin", True),
        ("/private/tmp", "darwin", True),
        ("/var/folders/ab", "darwin", True),
        ("/var/log", "darwin", False),
        ("/Usersx", "darwin", False),
        ("/srv/data", "linux", True),
    ],
)
def test_the_machine_reaches_a_drive_on_windows_and_the_shared_roots_on_macos(
    source, os_name, is_shared
):
    assert is_shared_source(source, os_name=os_name) is is_shared


@pytest.mark.parametrize(
    "source, machine",
    [
        ("C:\\data", "/mnt/c/data"),
        ("D:\\a b\\c\\", "/mnt/d/a b/c"),
        ("C:\\", "/mnt/c"),
        ("e:/x/y", "/mnt/e/x/y"),
        ("webdata", "webdata"),
    ],
)
def test_a_windows_folder_is_wsls_mount_of_its_drive(source, machine):
    assert to_machine_source(source, os_name="windows") == machine


def test_a_mac_folder_keeps_its_path_in_the_machine():
    assert to_machine("/Users/me/site:/site", os_name="darwin") == (
        "/Users/me/site:/site"
    )


def test_a_whole_volume_keeps_its_destination_and_options():
    assert to_machine("C:\\data:/data:ro", os_name="windows") == "/mnt/c/data:/data:ro"
    assert to_machine("webdata:/data", os_name="windows") == "webdata:/data"


@pytest.mark.parametrize(
    "machine, host",
    [
        ("/mnt/c/data", "C:\\data"),
        ("/mnt/d/a b/c", "D:\\a b\\c"),
        ("/mnt/c", "C:\\"),
        ("/var/lib/containers/storage/volumes/webdata/_data", None),
        ("/mnt/wsl/x", None),
    ],
)
def test_a_mount_reads_back_as_the_windows_folder(machine, host):
    expected = host if host is not None else machine

    assert to_host_source(machine, os_name="windows") == expected


def test_a_mount_on_a_mac_reads_back_as_it_is():
    assert to_host_source("/mnt/c/data", os_name="darwin") == "/mnt/c/data"
