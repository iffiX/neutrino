"""The verbs every module runner answers, on a runner with no software.

What these pin: ``validate`` closes typed either way, and a refusal writes
one log line naming the module, the code and its params; ``journal``
answers the runner's own log, the units' journal by default, capped at the
newest lines; the agent's own lines about a module are the ones that
name it, from the file the last rotation left and then the current one;
they follow the module's own lines and take at most half the box when
there are any; and a source that cannot be read is one line in the
agent's log naming the module and the source, once until it reads again.
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


def test_the_agent_s_lines_read_the_rotated_file_first(tmp_path):
    log = tmp_path / "agent.log"
    (tmp_path / "agent.log.1").write_text("09:00 samba: created\n", encoding="utf-8")
    log.write_text("10:00 samba: unchanged\n10:01 vscode: running\n", encoding="utf-8")
    runner = PickyRunner(platform=LoggedPlatform(str(log)))

    assert runner._agent_log_lines(10) == [
        "09:00 samba: created",
        "10:00 samba: unchanged",
    ]
    assert runner._agent_log_lines(1) == ["10:00 samba: unchanged"]


def test_the_agent_s_lines_take_half_beside_the_module_s_own(tmp_path):
    log = tmp_path / "agent.log"
    log.write_text(
        "".join(f"10:0{n} samba: step {n}\n" for n in range(6)), encoding="utf-8"
    )
    runner = PickyRunner(platform=LoggedPlatform(str(log)))
    own = [f"event {n}" for n in range(6)]

    assert runner._with_agent_lines(own, 4) == [
        "event 4",
        "event 5",
        "10:04 samba: step 4",
        "10:05 samba: step 5",
    ]
    assert runner._with_agent_lines([], 3) == [
        "10:03 samba: step 3",
        "10:04 samba: step 4",
        "10:05 samba: step 5",
    ]


def test_a_source_that_cannot_be_read_is_warned_of_once():
    lines: list = []
    runner = picky_runner(lines)

    def refuse():
        raise OSError("gone")

    assert runner._read_source("C:\\logs\\ann.log", refuse) == []
    assert runner._read_source("C:\\logs\\ann.log", refuse) == []
    assert lines == ["samba: cannot read the log source C:\\logs\\ann.log: gone"]
    assert runner._read_source("C:\\logs\\ann.log", lambda: ["back"]) == ["back"]
    runner._read_source("C:\\logs\\ann.log", refuse)
    assert len(lines) == 2
