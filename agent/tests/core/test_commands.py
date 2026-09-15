"""The commands the hub opens: the agent's own verbs, and each module's own.

What these pin: a module's verb reaches its runner by the ``module`` field
with the lines it prints handed on, ``validate`` reaches every runner
without waiting on the state, a module this build has no runner for and a
verb this agent does not have both refuse ``verb_unknown``, a runner that
raises answers ``agent_internal`` and never drops the stream, the power and
reinstall verbs keep their answers, ``resize`` reaches the shell stream it
names, a process is ended with a term and then a kill against a real
child, and the remote desktop verbs reach their reader with the status
riding the result.
"""

import os
import signal
import subprocess
import time

from neutrino_agent.core import commands
from neutrino_agent.core.commands import AGENT_VERBS, DeviceOperator
from neutrino_agent.modules.base import ModuleRunner
from neutrino_agent.platforms.base import AgentPlatform


class FakeRunner(ModuleRunner):
    name = "samba"

    def __init__(self, *, error=None):
        super().__init__(platform=None, log=lambda message: None)
        self.calls: list = []
        self.validated: list = []
        self.error = error

    def validate(self, config):
        self.validated.append(config)

    def command(self, verb, args, on_line=None):
        if verb != "set_password":
            return super().command(verb, args, on_line)
        self.calls.append((verb, args))
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


# --- the agent's own verbs ---


def test_the_agent_verbs_are_the_seven_the_protocol_names():
    assert AGENT_VERBS == (
        "reboot",
        "shutdown",
        "reinstall",
        "resize",
        "kill",
        "remote_desktop_read",
        "remote_desktop_password_set",
    )


def test_a_power_verb_runs_through_the_platform():
    outcome = operator().run("agent", "shutdown", {})

    assert (outcome.exit_code, outcome.output) == (0, "poweroff\n")


def test_reinstall_reports_launched_or_the_refusal():
    launched = DeviceOperator(platform=PowerPlatform(), reinstall=lambda: {})
    refused = DeviceOperator(
        platform=PowerPlatform(),
        reinstall=lambda: {"code": "agent_package_missing", "params": {"target": "x"}},
    )

    assert launched.run("agent", "reinstall", {}).output == "reinstall launched\n"
    outcome = refused.run("agent", "reinstall", {})
    assert (outcome.exit_code, outcome.code) == (1, "agent_package_missing")
    assert outcome.params == {"target": "x"}


def test_without_a_reinstall_the_verb_is_unsupported():
    outcome = operator().run("agent", "reinstall", {})

    assert outcome.code == "unsupported_platform"


def test_resize_reaches_the_shell_stream_it_names():
    resized: list = []
    subject = DeviceOperator(
        platform=PowerPlatform(),
        resize=lambda stream_id, cols, rows: resized.append((stream_id, cols, rows))
        or stream_id == 2,
    )

    good = subject.run("agent", "resize", {"shell": 2, "cols": 120, "rows": 40})
    gone = subject.run("agent", "resize", {"shell": 8, "cols": 120, "rows": 40})
    bad = subject.run("agent", "resize", {"shell": 2, "cols": 0, "rows": "x"})

    assert (good.exit_code, good.code) == (0, "")
    assert (gone.exit_code, gone.code) == (1, "shell_unknown")
    assert gone.params == {"shell": 8}
    assert bad.code == "shell_unknown"
    assert resized == [(2, 120, 40), (8, 120, 40)]


def test_an_agent_verb_this_agent_does_not_know_is_verb_unknown():
    outcome = operator().run("agent", "run_command", {"line": "rm -rf /"})

    assert (outcome.exit_code, outcome.code) == (1, "verb_unknown")
    assert outcome.params == {"module": "agent", "verb": "run_command"}


# --- a module's verbs ---


def test_a_module_verb_reaches_its_runner_with_its_lines():
    runner = FakeRunner()
    lines: list = []

    outcome = operator(samba=runner).run(
        "samba", "set_password", {"name": "ann", "password": "x"}, lines.append
    )

    assert runner.calls == [("set_password", {"name": "ann", "password": "x"})]
    assert lines == ["line one"]
    assert (outcome.exit_code, outcome.output) == (0, "done\n")


def test_a_module_this_build_has_no_runner_for_is_verb_unknown():
    outcome = operator().run("samba", "set_password", {"name": "ann"})

    assert (outcome.exit_code, outcome.code) == (1, "verb_unknown")
    assert outcome.params == {"module": "samba", "verb": "set_password"}


def test_a_verb_the_module_does_not_have_is_verb_unknown():
    outcome = operator(samba=FakeRunner()).run("samba", "reticulate", {})

    assert outcome.code == "verb_unknown"
    assert outcome.params == {"module": "samba", "verb": "reticulate"}


def test_a_runner_that_raises_answers_agent_internal():
    outcome = operator(samba=FakeRunner(error=OSError("boom"))).run(
        "samba", "set_password", {}
    )

    assert (outcome.exit_code, outcome.code) == (1, "agent_internal")
    assert outcome.params == {"error": "OSError"}


def test_validate_reaches_the_runner_without_waiting_on_the_state():
    runner = FakeRunner()
    settled: list = []
    changed: list = []
    subject = DeviceOperator(
        platform=PowerPlatform(),
        module_runners={"samba": runner},
        settle=lambda timeout_s: settled.append(timeout_s) or False,
        on_module_changed=changed.append,
    )

    outcome = subject.run("samba", "validate", {"config": {"shares": []}})

    assert runner.validated == [{"shares": []}]
    assert (outcome.exit_code, outcome.code) == (0, "")
    assert settled == []
    assert changed == []


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


def test_kill_ends_a_real_child():
    child = subprocess.Popen(["sleep", "30"])

    outcome = device_operator().run("agent", "kill", {"pid": child.pid})

    assert child.wait(timeout=5) == -signal.SIGTERM
    assert (outcome.exit_code, outcome.code) == (0, "")


def test_kill_kills_what_ignores_the_term(monkeypatch):
    monkeypatch.setattr(commands, "AGENT_KILL_GRACE_S", 0.2)
    child = subprocess.Popen(["sh", "-c", "trap '' TERM; sleep 30"])
    time.sleep(0.2)

    outcome = device_operator().run("agent", "kill", {"pid": child.pid})

    assert child.wait(timeout=5) == -signal.SIGKILL
    assert (outcome.exit_code, outcome.code) == (0, "")
    assert outcome.output == f"killed {child.pid}\n"


def test_kill_of_a_missing_pid_is_typed():
    child = subprocess.Popen(["true"])
    child.wait()

    outcome = device_operator().run("agent", "kill", {"pid": child.pid})

    assert outcome.code == "process_missing"
    assert outcome.params == {"pid": child.pid}


def test_kill_refuses_pid_one_and_itself():
    for pid in (0, 1, os.getpid(), "x"):
        outcome = device_operator().run("agent", "kill", {"pid": pid})
        assert outcome.code == "kill_failed"


def test_remote_desktop_read_closes_with_its_result():
    reader = FakeRemoteDesktop()

    outcome = device_operator(reader).run(
        "agent", "remote_desktop_read", {"product": "anydesk"}
    )

    assert outcome.exit_code == 0
    assert outcome.result == {
        "product": "anydesk",
        "is_installed": True,
        "session_id": "1",
    }
    assert reader.calls == [("status", "anydesk")]


def test_remote_desktop_password_set_reaches_the_reader_and_not_the_output():
    reader = FakeRemoteDesktop()

    outcome = device_operator(reader).run(
        "agent",
        "remote_desktop_password_set",
        {"product": "teamviewer", "password": "pw-1"},
    )

    assert reader.calls == [("password", "teamviewer", "pw-1")]
    assert (outcome.exit_code, outcome.output) == (0, "set\n")


def test_a_remote_desktop_product_outside_the_two_is_refused_typed():
    outcome = device_operator().run("agent", "remote_desktop_read", {"product": "vnc"})

    assert outcome.code == "product_unknown"
    assert outcome.params == {"product": "vnc"}


def test_a_reader_that_raises_answers_agent_internal():
    class Broken:
        def status(self, product):
            raise OSError("boom")

    outcome = device_operator(Broken()).run(
        "agent", "remote_desktop_read", {"product": "anydesk"}
    )

    assert outcome.code == "agent_internal"
    assert outcome.params == {"error": "OSError"}


# --- module verbs wait for the desired state ---


def test_a_module_verb_settles_the_desired_state_first():
    order = []
    runner = FakeRunner()
    subject = DeviceOperator(
        platform=PowerPlatform(),
        module_runners={"samba": runner},
        settle=lambda timeout_s: order.append(("settle", timeout_s)) or True,
    )

    outcome = subject.run("samba", "set_password", {"name": "test", "password": "x"})

    assert order and order[0][0] == "settle" and order[0][1] > 0
    assert outcome.code == ""


def test_a_state_that_never_settles_refuses_the_verb_typed():
    runner = FakeRunner()
    subject = DeviceOperator(
        platform=PowerPlatform(),
        module_runners={"samba": runner},
        settle=lambda timeout_s: False,
    )

    outcome = subject.run("samba", "set_password", {"name": "test", "password": "x"})

    assert (outcome.exit_code, outcome.code) == (1, "state_not_settled")
    assert outcome.params == {"module": "samba"}
    assert runner.calls == []


def test_a_module_verb_that_succeeded_reports_its_module_again():
    changed = []
    subject = DeviceOperator(
        platform=PowerPlatform(),
        module_runners={"samba": FakeRunner()},
        on_module_changed=changed.append,
    )

    subject.run("samba", "set_password", {"name": "test", "password": "x"})

    assert changed == ["samba"]


class RefusingRunner(FakeRunner):
    def command(self, verb, args, on_line=None):
        return {"exit_code": 1, "code": "user_unknown", "params": {}, "output": ""}


def test_a_module_verb_that_failed_reports_nothing_again():
    changed = []
    subject = DeviceOperator(
        platform=PowerPlatform(),
        module_runners={"samba": RefusingRunner()},
        on_module_changed=changed.append,
    )

    subject.run("samba", "set_password", {"name": "test", "password": "x"})

    assert changed == []
