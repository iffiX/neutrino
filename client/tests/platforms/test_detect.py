"""platforms.detect: the machine's tuple, and the class that answers for it.

macOS is refused outright: the client does not run there yet.
"""

import pytest

import neutrino_client.platforms.detect as detect_module
from neutrino_client.platforms.base import ClientPlatform, PlatformUnsupportedError
from neutrino_client.platforms.detect import detect_platform
from neutrino_client.platforms.linux import LinuxPlatform
from neutrino_client.platforms.windows import WindowsPlatform


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


def test_each_os_is_answered_by_its_own_class(monkeypatch, tmp_path):
    release = tmp_path / "os-release"
    release.write_text("ID=debian\n")
    monkeypatch.setattr(detect_module, "OS_RELEASE_PATH", str(release))
    monkeypatch.setattr(detect_module.platform, "machine", lambda: "x86_64")

    for reported, expected in (
        ("linux", LinuxPlatform),
        ("linux2", LinuxPlatform),
        ("win32", WindowsPlatform),
        ("freebsd13", ClientPlatform),
    ):
        monkeypatch.setattr(detect_module.sys, "platform", reported)
        assert type(detect_platform()) is expected


def test_macos_is_refused_typed(monkeypatch):
    monkeypatch.setattr(detect_module.sys, "platform", "darwin")
    monkeypatch.setattr(detect_module.platform, "machine", lambda: "arm64")

    with pytest.raises(PlatformUnsupportedError) as caught:
        detect_platform()

    assert caught.value.code == "unsupported_platform"
    assert detect_module.platform_tuple()["os"] == "darwin"
