"""The verbs every module runner answers, on a runner with no software.

What these pin: ``validate`` closes typed either way, and a refusal writes
one log line naming the module, the code and its params.
"""

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.base import ModuleRunner


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
