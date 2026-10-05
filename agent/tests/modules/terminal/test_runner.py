"""The Terminal module's runner: always there, always running, holding the settings.

What these pin: the module is installed and active with nothing to
install; its validate answers the checks' codes; an apply holds the
settings a new shell reads; before any apply the settings are the kept
state's, and the defaults when there is none or it cannot be read; the
engine reports it ``running`` once the state applied it.
"""

import json

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.terminal.runner import TerminalModuleRunner


class Platform:
    os_name = "linux"

    def __init__(self, data_dir):
        self._data_dir = data_dir

    def agent_data_dir(self):
        return str(self._data_dir)


def runner_at(tmp_path, os_name="linux"):
    platform = Platform(tmp_path)
    platform.os_name = os_name
    return TerminalModuleRunner(platform=platform, log=lambda line: None)


def keep_state(tmp_path, config):
    (tmp_path / "desired.json").write_text(
        json.dumps(
            {
                "hash": "h",
                "modules": {"terminal": {"want": "running", "config": config}},
            }
        )
    )


def test_the_module_is_there_and_running_with_nothing_installed(tmp_path):
    runner = runner_at(tmp_path)

    observed = runner.observe({})

    assert observed["is_installed"] is True
    assert observed["is_active"] is True


def test_validate_answers_the_checks_codes(tmp_path):
    runner = runner_at(tmp_path)

    with pytest.raises(ModuleApplyError) as refused:
        runner.validate({"account": "", "shell_path": "/no/such/shell"})

    assert refused.value.code == "shell_program_unusable"
    assert (
        runner.command("validate", {"config": {"account": "nobody-here-xyz"}})["code"]
        == "account_unknown"
    )


def test_an_apply_holds_what_a_new_shell_reads(tmp_path):
    runner = runner_at(tmp_path)
    keep_state(tmp_path, {"account": "kept", "shell_path": ""})

    runner.apply({"account": "ann", "shell_path": "/bin/zsh"})

    assert runner.settings().to_dict() == {"account": "ann", "shell_path": "/bin/zsh"}


def test_before_any_apply_the_kept_state_says(tmp_path):
    keep_state(tmp_path, {"account": "ann", "shell_path": "/bin/zsh"})

    assert runner_at(tmp_path).settings().to_dict() == {
        "account": "ann",
        "shell_path": "/bin/zsh",
    }
    assert runner_at(tmp_path, "windows").settings().account == ""


@pytest.mark.parametrize("written", [None, "not json", {"account": 3}])
def test_no_kept_state_or_an_unreadable_one_is_the_defaults(tmp_path, written):
    if isinstance(written, dict):
        keep_state(tmp_path, written)
    elif written is not None:
        (tmp_path / "desired.json").write_text(written)

    assert runner_at(tmp_path).settings().to_dict() == {
        "account": "",
        "shell_path": "",
    }
