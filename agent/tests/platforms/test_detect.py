"""platforms.detect produces manifest keys from most to least specific."""

from neutrino_agent.platforms.detect import platform_keys


def test_keys_most_specific_first_with_family():
    info = {"os": "linux", "family": "debian", "arch": "amd64"}
    assert platform_keys(info) == [
        "linux-debian-amd64",
        "linux-debian",
        "linux-amd64",
        "linux",
    ]


def test_keys_without_family():
    info = {"os": "windows", "family": "", "arch": "amd64"}
    assert platform_keys(info) == ["windows-amd64", "windows"]


def test_raspberry_pi_armhf():
    info = {"os": "linux", "family": "debian", "arch": "armhf"}
    keys = platform_keys(info)
    assert keys[0] == "linux-debian-armhf"
    assert "linux" in keys
