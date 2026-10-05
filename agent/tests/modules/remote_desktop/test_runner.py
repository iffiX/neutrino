"""The Remote desktop module: one switch handed to the desktop host, and
running while the copy listens."""

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.remote_desktop.config import RemoteDesktopConfig
from neutrino_agent.modules.remote_desktop.runner import RemoteDesktopModuleRunner
from neutrino_agent.platforms.base import AgentPlatform


class FakeHost:
    def __init__(self):
        self.switches = []
        self.is_listening = False

    def set_switch(self, is_enabled):
        self.switches.append(is_enabled)

    def is_running(self):
        return self.is_listening


class Linux(AgentPlatform):
    os_name = "linux"


class Mac(AgentPlatform):
    os_name = "darwin"


@pytest.fixture()
def runner():
    made = RemoteDesktopModuleRunner(platform=Linux(), log=lambda message: None)
    made.host = FakeHost()
    made.bind_host(made.host)
    return made


def test_the_switch_reaches_the_host(runner):
    runner.apply({"is_enabled": True})
    runner.apply({"is_enabled": False})
    runner.apply({})

    assert runner.host.switches == [True, False, False]


@pytest.mark.parametrize(
    "data, expected",
    [({"is_enabled": True}, True), ({"is_enabled": "yes"}, False), (None, False)],
)
def test_only_a_true_switch_reads_as_on(data, expected):
    assert RemoteDesktopConfig.from_dict(data).is_enabled is expected


def test_the_module_is_always_there_and_active_while_the_copy_listens(runner):
    observed = runner.observe({})
    assert observed["is_installed"] is True
    assert observed["is_active"] is False

    runner.host.is_listening = True

    assert runner.observe({})["is_active"] is True


def test_a_runner_with_no_host_yet_refuses_with_a_code():
    unbound = RemoteDesktopModuleRunner(platform=Linux(), log=lambda message: None)

    with pytest.raises(ModuleApplyError) as raised:
        unbound.apply({"is_enabled": True})

    assert raised.value.code == "rdp_takeover_failed"
    assert unbound.is_active() is False


def test_its_journal_is_rustdesks_unit_on_linux_only(runner):
    mac = RemoteDesktopModuleRunner(platform=Mac(), log=lambda message: None)

    assert runner.journal_units() == ["rustdesk.service"]
    assert mac.journal_units() == []
