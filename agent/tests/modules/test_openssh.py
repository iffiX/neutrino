"""The SSH server: enabled and disabled, never installed or removed."""

from neutrino_agent.modules.openssh import OpensshModuleReconciler
from neutrino_agent.platforms.base import AgentPlatform
from tests.conftest import discard


class SwitchPlatform(AgentPlatform):
    os_name = "linux"

    def __init__(self, *, is_running: bool):
        self.is_running = is_running
        self.calls: list = []

    def read_openssh_status(self, entry) -> bool:
        return self.is_running

    def enable_openssh(self, entry) -> None:
        self.calls.append("enable")
        self.is_running = True

    def disable_openssh(self, entry) -> None:
        self.calls.append("disable")
        self.is_running = False


def openssh_reconcile(platform, wish):
    subject = OpensshModuleReconciler(platform=platform, log=discard)
    return subject.reconcile(
        name="openssh_server",
        manifest={"kind": "openssh"},
        entry={"service": "ssh"},
        wanted=wish,
    )


def wanted(is_enabled: bool) -> dict:
    return {"is_enabled": is_enabled}


def test_openssh_is_enabled_when_asked():
    platform = SwitchPlatform(is_running=False)

    state = openssh_reconcile(platform, wanted(True))

    assert platform.calls == ["enable"]
    assert state["state"] == "enabled"


def test_openssh_is_disabled_when_asked():
    platform = SwitchPlatform(is_running=True)

    state = openssh_reconcile(platform, wanted(False))

    assert platform.calls == ["disable"]
    assert state["state"] == "disabled"


def test_openssh_already_converged_is_only_reported():
    platform = SwitchPlatform(is_running=True)

    state = openssh_reconcile(platform, wanted(True))

    assert platform.calls == []
    assert state["state"] == "enabled"


def test_openssh_undecided_is_reported_never_touched():
    platform = SwitchPlatform(is_running=False)

    state = openssh_reconcile(platform, None)

    assert platform.calls == []
    assert state["state"] == "disabled"
