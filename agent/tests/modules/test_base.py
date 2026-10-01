"""The verbs every module runner answers, on a runner with no software.

What these pin: ``validate`` closes typed either way, and a refusal writes
one log line naming the module, the code and its params; ``journal``
answers the runner's own log, the units' journal by default, capped at the
newest lines; and the agent's own lines about a module are the ones that
name it.
"""

import neutrino_agent.modules.base as base_module
from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.base import ModuleRunner
from neutrino_agent.platforms.base import AgentPlatform


class PickyRunner(ModuleRunner):
    """A module that refuses any configuration naming a relative path."""

    name = "samba"

    def validate(self, config: dict) -> None:
        path = config.get("path", "")
        if not path.startswith("/"):
            raise ModuleApplyError("share_path_relative", {"path": path})


def picky_runner(lines: list) -> PickyRunner:
    return PickyRunner(platform=None, log=lines.append)


def test_a_refused_validate_logs_its_code_and_params():
    lines: list = []

    outcome = picky_runner(lines).command("validate", {"config": {"path": "srv"}})

    assert (outcome["code"], outcome["params"]) == (
        "share_path_relative",
        {"path": "srv"},
    )
    assert lines == ["samba validate refused: share_path_relative path=srv"]


def test_an_accepted_validate_logs_nothing():
    lines: list = []

    outcome = picky_runner(lines).command("validate", {"config": {"path": "/srv"}})

    assert (outcome["exit_code"], outcome["code"]) == (0, "")
    assert lines == []


class LoggedPlatform(AgentPlatform):
    """A platform whose agent writes its log to one file."""

    def __init__(self, path):
        self._path = path

    def agent_log_path(self):
        return self._path


class FileLogRunner(ModuleRunner):
    """A module whose log is a list it was handed."""

    name = "samba"

    def __init__(self, lines, **kwargs):
        super().__init__(**kwargs)
        self._lines = lines

    def journal_text(self, lines):
        return list(self._lines)


def test_the_journal_verb_answers_the_runner_s_own_log_capped_at_the_newest():
    runner = FileLogRunner([f"line {n}" for n in range(5)], platform=None)

    outcome = runner.command("journal", {"lines": 2})

    assert (outcome["exit_code"], outcome["output"]) == (0, "line 3\nline 4")


def test_the_default_log_is_the_units_journal(monkeypatch):
    calls = []

    def units_journal(units, lines):
        calls.append((units, lines))
        return ["boot"]

    monkeypatch.setattr(base_module, "units_journal", units_journal)

    assert ModuleRunner(platform=None).journal_text(50) == ["boot"]
    assert calls == [([], 50)]


def test_the_agent_s_own_lines_are_the_ones_naming_the_module(tmp_path):
    log = tmp_path / "agent.log"
    log.write_text(
        "10:00 samba: created share media\n10:01 vscode: unchanged\n",
        encoding="utf-8",
    )
    runner = PickyRunner(platform=LoggedPlatform(str(log)))

    assert runner._agent_log_lines(10) == ["10:00 samba: created share media"]
    assert PickyRunner(platform=LoggedPlatform(""))._agent_log_lines(10) == []
