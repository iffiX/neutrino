"""The commands the hub sends: the agent's own, and each module's own.

What these pin: a module action reaches its runner by prefix with the
lines it prints handed on, a module this build has no runner for refuses
typed, a runner that raises answers ``agent_internal`` and never drops the
stream, the power and reinstall actions keep their answers, a process is
ended with a term and then a kill against a real child, and the remote
desktop verbs reach their reader with the status riding the result.
"""

import os
import signal
import subprocess
import time

from neutrino_agent.core import commands
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


class NoRemoteDesktop:
    """Nothing is asked of the remote desktops in the module cases."""


def operator(**runners) -> DeviceOperator:
    return DeviceOperator(
        platform=PowerPlatform(),
        module_runners=runners,
        remote_desktop=NoRemoteDesktop(),
    )


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


# --- the device verbs ---


class FakeRemoteDesktop:
    def __init__(self):
        self.calls: list = []

    def status(self, product):
        self.calls.append(("status", product))
        return {"product": product, "is_installed": True, "session_id": "1"}

    def set_password(self, product, password):
        self.calls.append(("password", product, password))
        return {"exit_code": 0, "code": "", "params": {}, "output": "set\n"}


def device_operator(remote_desktop=None) -> DeviceOperator:
    return DeviceOperator(
        platform=PowerPlatform(), remote_desktop=remote_desktop or FakeRemoteDesktop()
    )


def test_the_device_verbs_are_supported_actions():
    for action in ("kill_process", "remote_desktop_status", "remote_desktop_password"):
        assert action in SUPPORTED_ACTIONS


def test_kill_process_ends_a_real_child():
    child = subprocess.Popen(["sleep", "30"])

    outcome = device_operator().run("kill_process", {"pid": child.pid})

    assert child.wait(timeout=5) == -signal.SIGTERM
    assert (outcome.exit_code, outcome.code) == (0, "")


def test_kill_process_kills_what_ignores_the_term(monkeypatch):
    monkeypatch.setattr(commands, "AGENT_KILL_GRACE_S", 0.2)
    child = subprocess.Popen(["sh", "-c", "trap '' TERM; sleep 30"])
    time.sleep(0.2)

    outcome = device_operator().run("kill_process", {"pid": child.pid})

    assert child.wait(timeout=5) == -signal.SIGKILL
    assert (outcome.exit_code, outcome.code) == (0, "")
    assert outcome.output == f"killed {child.pid}\n"


def test_kill_process_of_a_missing_pid_is_typed():
    child = subprocess.Popen(["true"])
    child.wait()

    outcome = device_operator().run("kill_process", {"pid": child.pid})

    assert outcome.code == "process_missing"
    assert outcome.params == {"pid": child.pid}


def test_kill_process_refuses_pid_one_and_itself():
    for pid in (0, 1, os.getpid(), "x"):
        outcome = device_operator().run("kill_process", {"pid": pid})
        assert outcome.code == "kill_failed"


def test_remote_desktop_status_closes_with_its_result():
    reader = FakeRemoteDesktop()

    outcome = device_operator(reader).run(
        "remote_desktop_status", {"product": "anydesk"}
    )

    assert outcome.exit_code == 0
    assert outcome.result == {
        "product": "anydesk",
        "is_installed": True,
        "session_id": "1",
    }
    assert reader.calls == [("status", "anydesk")]


def test_remote_desktop_password_reaches_the_reader_and_not_the_output():
    reader = FakeRemoteDesktop()

    outcome = device_operator(reader).run(
        "remote_desktop_password", {"product": "teamviewer", "password": "pw-1"}
    )

    assert reader.calls == [("password", "teamviewer", "pw-1")]
    assert (outcome.exit_code, outcome.output) == (0, "set\n")


def test_a_remote_desktop_product_outside_the_two_is_refused_typed():
    outcome = device_operator().run("remote_desktop_status", {"product": "vnc"})

    assert outcome.code == "product_unknown"
    assert outcome.params == {"product": "vnc"}


def test_a_reader_that_raises_answers_agent_internal():
    class Broken:
        def status(self, product):
            raise OSError("boom")

    outcome = device_operator(Broken()).run(
        "remote_desktop_status", {"product": "anydesk"}
    )

    assert outcome.code == "agent_internal"
    assert outcome.params == {"error": "OSError"}
