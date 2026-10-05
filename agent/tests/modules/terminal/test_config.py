"""The Terminal module's settings and the checks a shell open makes of them.

What these pin: both settings read as strings, absent and null as empty,
anything else refused ``config_invalid``; Windows drops the account; an
account the machine does not have is ``account_unknown``; a shell program
that is missing, relative, a directory or without an execute bit is
``shell_program_unusable``; both empty need nothing.
"""

import getpass

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.terminal.config import TerminalConfig


def test_absent_and_null_settings_are_the_defaults():
    config = TerminalConfig.from_dict({"account": None}, os_name="linux")

    assert config.to_dict() == {"account": "", "shell_path": ""}
    config.validate()


def test_a_setting_that_is_not_a_string_is_refused():
    with pytest.raises(ModuleApplyError) as refused:
        TerminalConfig.from_dict({"shell_path": 3}, os_name="linux")

    assert (refused.value.code, refused.value.params) == (
        "config_invalid",
        {"field": "shell_path"},
    )


def test_windows_takes_the_shell_program_alone():
    config = TerminalConfig.from_dict(
        {"account": "ann", "shell_path": "C:\\x.exe"}, os_name="windows"
    )

    assert config.to_dict() == {"account": "", "shell_path": "C:\\x.exe"}


def test_an_account_the_machine_lacks_is_unknown():
    with pytest.raises(ModuleApplyError) as refused:
        TerminalConfig(account="nobody-here-xyz").validate()

    assert (refused.value.code, refused.value.params) == (
        "account_unknown",
        {"account": "nobody-here-xyz"},
    )


@pytest.mark.parametrize("name", ["missing", "plain", "folder", "relative"])
def test_a_shell_program_that_cannot_run_is_unusable(tmp_path, name):
    plain = tmp_path / "plain"
    plain.write_text("#!/bin/sh\n")
    (tmp_path / "folder").mkdir()
    path = {
        "missing": str(tmp_path / "missing"),
        "plain": str(plain),
        "folder": str(tmp_path / "folder"),
        "relative": "bin/sh",
    }[name]

    with pytest.raises(ModuleApplyError) as refused:
        TerminalConfig(shell_path=path).validate()

    assert (refused.value.code, refused.value.params) == (
        "shell_program_unusable",
        {"path": path},
    )


def test_an_account_the_machine_has_and_a_program_it_runs_pass():
    TerminalConfig(account=getpass.getuser(), shell_path="/bin/sh").validate()
