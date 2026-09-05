"""platforms.detect: the machine's tuple, and the class that answers for it.

Manifest keys run from most to least specific; the tuple is read from the
operating system's own facts, and an os the agent does not know gets the base
contract rather than a guess.
"""

import neutrino_agent.platforms.detect as detect_module
from neutrino_agent.platforms.base import AgentPlatform
from neutrino_agent.platforms.darwin import DarwinPlatform
from neutrino_agent.platforms.detect import detect_platform, platform_keys
from neutrino_agent.platforms.linux import LinuxPlatform
from neutrino_agent.platforms.windows import WindowsPlatform


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


def test_the_tuple_is_read_from_the_os_facts(monkeypatch, tmp_path):
    release = tmp_path / "os-release"
    monkeypatch.setattr(detect_module, "OS_RELEASE_PATH", str(release))

    release.write_text('ID=raspbian\nID_LIKE="debian"\n')
    monkeypatch.setattr(detect_module.sys, "platform", "linux")
    monkeypatch.setattr(detect_module.platform, "machine", lambda: "armv7l")
    assert detect_module.platform_tuple() == {
        "os": "linux",
        "family": "debian",
        "arch": "armhf",
    }

    release.write_text('ID=rocky\nID_LIKE="rhel centos fedora"\n')
    monkeypatch.setattr(detect_module.platform, "machine", lambda: "aarch64")
    assert detect_module.platform_tuple() == {
        "os": "linux",
        "family": "rhel",
        "arch": "arm64",
    }

    release.write_text("ID=alpine\n")
    assert detect_module.platform_tuple()["family"] == ""

    monkeypatch.setattr(detect_module.sys, "platform", "win32")
    monkeypatch.setattr(detect_module.platform, "machine", lambda: "AMD64")
    assert detect_module.platform_tuple() == {
        "os": "windows",
        "family": "",
        "arch": "amd64",
    }

    monkeypatch.setattr(detect_module.sys, "platform", "darwin")
    monkeypatch.setattr(detect_module.platform, "machine", lambda: "arm64")
    assert detect_module.platform_tuple() == {
        "os": "darwin",
        "family": "",
        "arch": "arm64",
    }


def test_each_os_is_answered_by_its_own_class(monkeypatch, tmp_path):
    release = tmp_path / "os-release"
    release.write_text("ID=debian\n")
    monkeypatch.setattr(detect_module, "OS_RELEASE_PATH", str(release))
    monkeypatch.setattr(detect_module.platform, "machine", lambda: "x86_64")

    for reported, expected in (
        ("linux", LinuxPlatform),
        ("linux2", LinuxPlatform),
        ("darwin", DarwinPlatform),
        ("win32", WindowsPlatform),
        ("freebsd13", AgentPlatform),
    ):
        monkeypatch.setattr(detect_module.sys, "platform", reported)
        platform = detect_platform()
        assert type(platform) is expected

    monkeypatch.setattr(detect_module.sys, "platform", "freebsd13")
    assert detect_platform().capabilities == frozenset()
    assert detect_module.platform_tuple()["os"] == "freebsd13"
