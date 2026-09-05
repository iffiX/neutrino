"""The platform contract: advertised capabilities, honest refusals.

A platform says what it has; invoking what it lacks answers
``unsupported_platform``, never a guess.
"""

import pytest

from neutrino_agent.platforms.base import AgentPlatform, PlatformUnsupportedError
from neutrino_agent.platforms.darwin import DarwinPlatform
from neutrino_agent.platforms.linux import LinuxPlatform
from neutrino_agent.platforms.windows import WindowsPlatform


def test_the_base_platform_advertises_nothing():
    assert AgentPlatform().capabilities == frozenset()


def test_each_platform_advertises_its_capability_set():
    assert LinuxPlatform().capabilities == frozenset(
        {
            "accounts",
            "account_files",
            "run_as",
            "control_socket",
            "agent_service",
            "power",
            "metrics",
            "packages",
            "openssh",
            "shares",
        }
    )
    assert DarwinPlatform().capabilities == frozenset(
        {
            "accounts",
            "account_files",
            "run_as",
            "control_socket",
            "packages",
            "openssh",
        }
    )
    assert WindowsPlatform().capabilities == frozenset(
        {"account_files", "packages", "openssh"}
    )


def test_only_linux_advertises_shares_so_far():
    assert LinuxPlatform().has_capability("shares")
    for platform in (DarwinPlatform(), WindowsPlatform()):
        assert not platform.has_capability("shares")


def test_an_absent_capability_is_refused_not_guessed():
    with pytest.raises(PlatformUnsupportedError) as caught:
        WindowsPlatform().run_as_account("bob", ["id"])
    assert caught.value.code == "unsupported_platform"
    with pytest.raises(PlatformUnsupportedError):
        AgentPlatform().read_host_metrics()
    with pytest.raises(PlatformUnsupportedError):
        DarwinPlatform().power("reboot")
    with pytest.raises(PlatformUnsupportedError):
        WindowsPlatform().human_accounts()
    with pytest.raises(PlatformUnsupportedError):
        DarwinPlatform().is_share_attached(location="/mnt/share")


def test_base_file_operations_refuse_without_run_as():
    with pytest.raises(PlatformUnsupportedError):
        AgentPlatform().read_account_file(account="alice", relative="f")
