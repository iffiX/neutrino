"""The Terminal module's runner: always there, always running, holding the enabled accounts.

What these pin: the module is installed and active with nothing to
install; its validate answers the checks' codes, on Windows against the
accounts the machine lists; an apply holds the accounts a new shell reads;
before any apply the accounts are the kept state's, and none when there is
no kept state or it cannot be read.
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

    def human_accounts(self):
        return ["alice"]


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

    assert runner.verify({}) is True
    assert runner.is_active() is True


def test_validate_answers_the_checks_codes(tmp_path):
    runner = runner_at(tmp_path)

    with pytest.raises(ModuleApplyError) as refused:
        runner.validate({"accounts": [{"account": "nobody-here-xyz"}]})

    assert refused.value.code == "account_unknown"
    assert (
        runner.command(
            "validate", {"config": {"accounts": [{"account": "nobody-here-xyz"}]}}
        )["code"]
        == "account_unknown"
    )


def test_on_windows_validate_reads_the_machines_accounts(tmp_path):
    runner = runner_at(tmp_path, "windows")

    runner.validate({"accounts": [{"account": "alice", "password": "pw"}]})
    with pytest.raises(ModuleApplyError) as refused:
        runner.validate({"accounts": [{"account": "bob", "password": "pw"}]})

    assert refused.value.params == {"account": "bob"}


def test_an_apply_holds_what_a_new_shell_reads(tmp_path):
    runner = runner_at(tmp_path)
    keep_state(tmp_path, {"accounts": [{"account": "kept"}]})

    runner.apply({"accounts": [{"account": "ann", "shell_path": "/bin/zsh"}]})

    assert runner.settings().names() == ["ann"]
    assert runner.settings().accounts[0].shell_path == "/bin/zsh"


def test_before_any_apply_the_kept_state_says(tmp_path):
    keep_state(tmp_path, {"accounts": [{"account": "ann"}, {"account": "bob"}]})

    assert runner_at(tmp_path).settings().names() == ["ann", "bob"]


@pytest.mark.parametrize("written", [None, "not json", {"accounts": [{"account": 3}]}])
def test_no_kept_state_or_an_unreadable_one_enables_no_account(tmp_path, written):
    if isinstance(written, dict):
        keep_state(tmp_path, written)
    elif written is not None:
        (tmp_path / "desired.json").write_text(written)

    assert runner_at(tmp_path).settings().accounts == []
