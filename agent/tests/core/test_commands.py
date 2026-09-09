"""The commands the hub sends: the agent's own, and each module's own.

What these pin: a module action reaches its runner by prefix with the
lines it prints handed on, a module this build has no runner for refuses
typed, a runner that raises answers ``agent_internal`` and never drops the
stream, and the power and reinstall actions keep their answers.
"""

from neutrino_agent.core.commands import (
    MODULE_ACTIONS,
    SUPPORTED_ACTIONS,
    DeviceOperator,
)
from neutrino_agent.platforms.base import AgentPlatform


class FakeRunner:
    def __init__(self, *, error=None):
        self.calls: list = []
        self.error = error

    def command(self, action, args, on_line=None):
        self.calls.append((action, args))
        if self.error is not None:
            raise self.error
        if on_line is not None:
            on_line("line one")
        return {"exit_code": 0, "code": "", "params": {}, "output": "done\n"}


class PowerPlatform(AgentPlatform):
    os_name = "linux"

    def power(self, action):
        return 0, f"{action}\n"


def operator(**runners) -> DeviceOperator:
    return DeviceOperator(platform=PowerPlatform(), module_runners=runners)


def test_every_module_action_is_a_supported_action():
    for actions in MODULE_ACTIONS.values():
        for action in actions:
            assert action in SUPPORTED_ACTIONS


def test_a_module_action_reaches_its_runner_with_its_lines():
    samba = FakeRunner()
    lines: list = []

    outcome = operator(samba=samba).run(
        "samba_set_password", {"name": "ann", "password": "x"}, lines.append
    )

    assert samba.calls == [("samba_set_password", {"name": "ann", "password": "x"})]
    assert lines == ["line one"]
    assert (outcome.exit_code, outcome.code, outcome.output) == (0, "", "done\n")


def test_each_prefix_lands_on_its_own_runner():
    runners = {name: FakeRunner() for name in MODULE_ACTIONS}
    held = operator(**runners)

    for module, actions in MODULE_ACTIONS.items():
        for action in actions:
            held.run(action, {})
        assert [call[0] for call in runners[module].calls] == list(actions)


def test_a_module_this_build_has_no_runner_for_refuses_typed():
    outcome = operator().run("zfs_scan", {})

    assert outcome.exit_code == 1
    assert outcome.code == "unsupported_action"
    assert outcome.params == {"action": "zfs_scan"}


def test_a_runner_that_raises_answers_agent_internal():
    outcome = operator(gitea=FakeRunner(error=KeyError("boom"))).run("gitea_admin", {})

    assert outcome.exit_code == 1
    assert outcome.code == "agent_internal"
    assert outcome.params == {"error": "KeyError"}


def test_the_power_actions_still_answer():
    outcome = operator().run("reboot", {})

    assert outcome.exit_code == 0
    assert outcome.output == "reboot\n"


def test_an_unknown_action_is_a_typed_refusal():
    outcome = operator().run("run_command", {"command": "rm -rf /"})

    assert outcome.code == "unsupported_action"
