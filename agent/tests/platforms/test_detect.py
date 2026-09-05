"""platforms.detect: the machine's tuple, and the class that answers for it.

The tuple is read from the operating system's own facts, and an os the agent
does not know gets the base contract rather than a guess. Turning a tuple
into a manifest key is not here and must not come back: the hub resolves
every platform table, which is what leaves this package nothing to download.
"""

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
