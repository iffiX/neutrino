"""platforms.detect: the machine's tuple, and the class that answers for it.

The tuple is read from the operating system's own facts and names the OS
the way the client does. Each OS the agent knows is answered by its own
class, and any other gets the base contract, which claims nothing. Turning a
tuple into a manifest key is not here and must not come back: the hub
resolves every platform table, which is what leaves this package nothing to
download.
"""

import pytest

import neutrino_agent.platforms.detect as detect_module
from neutrino_agent.platforms.base import AgentPlatform
from neutrino_agent.platforms.darwin import DarwinPlatform
from neutrino_agent.platforms.detect import detect_platform
from neutrino_agent.platforms.linux import LinuxPlatform
from neutrino_agent.platforms.windows import WindowsPlatform


def test_the_agent_resolves_no_platform_tables():
    # The tuple travels up and the hub answers with conclusions; a key
    # function here would be a second place that decides what to install.
    assert not hasattr(detect_module, "platform_keys")


def test_the_tuple_is_read_from_the_os_facts(monkeypatch, tmp_path):
    release = tmp_path / "os-release"
    monkeypatch.setattr(detect_module, "OS_RELEASE_PATH", str(release))
    monkeypatch.setattr(detect_module.sys, "platform", "linux")
    monkeypatch.setattr(
        detect_module.os, "confstr", lambda name: "glibc 2.36", raising=False
    )

    release.write_text('ID=raspbian\nID_LIKE="debian"\n')
    monkeypatch.setattr(detect_module.platform, "machine", lambda: "armv7l")
    assert detect_module.platform_tuple() == {
        "os": "linux",
        "family": "debian",
        "arch": "armhf",
        "version": "2.36",
    }

    release.write_text('ID=rocky\nID_LIKE="rhel centos fedora"\n')
    monkeypatch.setattr(detect_module.platform, "machine", lambda: "aarch64")
    assert detect_module.platform_tuple() == {
        "os": "linux",
        "family": "rhel",
        "arch": "arm64",
        "version": "2.36",
    }

    release.write_text("ID=alpine\n")
    assert detect_module.platform_tuple()["family"] == ""


class WindowsVersion:
    build = 26100


def windows_version():
    return WindowsVersion()


@pytest.mark.parametrize(
    "reported, named, version",
    [
        ("win32", "windows", "26100"),
        ("darwin", "darwin", "15.3.1"),
        ("freebsd13", "freebsd13", ""),
    ],
)
def test_an_os_that_is_not_linux_is_named_as_the_client_names_it(
    monkeypatch, reported, named, version
):
    monkeypatch.setattr(detect_module.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(detect_module.sys, "platform", reported)
    monkeypatch.setattr(
        detect_module.sys, "getwindowsversion", windows_version, raising=False
    )
    monkeypatch.setattr(
        detect_module.platform, "mac_ver", lambda: ("15.3.1", ("", "", ""), "arm64")
    )

    assert detect_module.platform_tuple() == {
        "os": named,
        "family": "",
        "arch": "amd64",
        "version": version,
    }


def test_linux_without_glibc_reports_no_version(monkeypatch, tmp_path):
    release = tmp_path / "os-release"
    release.write_text("ID=alpine\n")
    monkeypatch.setattr(detect_module, "OS_RELEASE_PATH", str(release))
    monkeypatch.setattr(detect_module.sys, "platform", "linux")

    def no_confstr(name):
        raise ValueError(name)

    monkeypatch.setattr(detect_module.os, "confstr", no_confstr, raising=False)
    monkeypatch.setattr(detect_module.platform, "libc_ver", lambda: ("musl", "1.2"))

    assert detect_module.platform_tuple()["version"] == ""


def test_linux_falls_back_to_the_libc_python_reads(monkeypatch, tmp_path):
    release = tmp_path / "os-release"
    release.write_text("ID=debian\n")
    monkeypatch.setattr(detect_module, "OS_RELEASE_PATH", str(release))
    monkeypatch.setattr(detect_module.sys, "platform", "linux")
    monkeypatch.setattr(detect_module.os, "confstr", lambda name: "", raising=False)
    monkeypatch.setattr(detect_module.platform, "libc_ver", lambda: ("glibc", "2.28"))

    assert detect_module.platform_tuple()["version"] == "2.28"


def test_linux_is_answered_by_its_own_class(monkeypatch, tmp_path):
    release = tmp_path / "os-release"
    release.write_text("ID=debian\n")
    monkeypatch.setattr(detect_module, "OS_RELEASE_PATH", str(release))
    monkeypatch.setattr(detect_module.platform, "machine", lambda: "x86_64")

    for reported in ("linux", "linux2"):
        monkeypatch.setattr(detect_module.sys, "platform", reported)
        assert type(detect_platform()) is LinuxPlatform


@pytest.mark.parametrize(
    "reported, answering",
    [("win32", WindowsPlatform), ("darwin", DarwinPlatform)],
)
def test_windows_and_macos_are_answered_by_their_own_class(
    monkeypatch, reported, answering
):
    monkeypatch.setattr(detect_module.sys, "platform", reported)

    assert type(detect_platform()) is answering


def test_an_os_the_agent_does_not_know_gets_the_contract_that_claims_nothing(
    monkeypatch,
):
    monkeypatch.setattr(detect_module.sys, "platform", "freebsd13")

    detected = detect_platform()

    assert type(detected) is AgentPlatform
    assert detected.capabilities == frozenset()
