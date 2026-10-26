"""The Terminal module's enabled accounts and the checks a shell open makes of them.

What these pin: the accounts read in order, each field a string, absent and
null as empty, anything else refused ``config_invalid``, an account named
twice ``account_duplicate``; the open's account or the first one is chosen,
no account is ``terminal_account_missing`` and one the module does not
enable ``account_not_enabled``; an account the machine does not have is
``account_unknown``; a shell program that is missing, relative, a directory
or without an execute bit is ``shell_program_unusable``; on Windows an
account with no login is ``credential_missing`` and the account list the
machine reports decides which accounts exist.
"""

import getpass

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.terminal.config import TerminalAccount, TerminalConfig

ME = getpass.getuser()


def refusal(call) -> tuple:
    with pytest.raises(ModuleApplyError) as refused:
        call()
    return refused.value.code, refused.value.params


def test_the_accounts_read_in_order_with_their_shells_and_logins():
    config = TerminalConfig.from_dict(
        {
            "accounts": [
                {"account": "ann", "shell_path": "/bin/zsh", "password": ""},
                {"account": "bob", "shell_path": None},
            ]
        }
    )

    assert config.names() == ["ann", "bob"]
    assert config.to_dict() == {
        "accounts": [
            {"account": "ann", "shell_path": "/bin/zsh", "password": ""},
            {"account": "bob", "shell_path": "", "password": ""},
        ]
    }


@pytest.mark.parametrize("raw", [None, {}, {"accounts": None}, "not a dict"])
def test_nothing_named_enables_no_account(raw):
    assert TerminalConfig.from_dict(raw).accounts == []


@pytest.mark.parametrize(
    "raw, params",
    [
        ({"accounts": "ann"}, {"field": "accounts"}),
        ({"accounts": ["ann"]}, {"field": "accounts"}),
        ({"accounts": [{"account": ""}]}, {"field": "account"}),
        ({"accounts": [{"account": "ann", "shell_path": 3}]}, {"field": "shell_path"}),
        ({"accounts": [{"account": "ann", "password": 3}]}, {"field": "password"}),
    ],
)
def test_a_list_that_does_not_read_is_refused(raw, params):
    assert refusal(lambda: TerminalConfig.from_dict(raw)) == ("config_invalid", params)


def test_an_account_named_twice_is_refused():
    raw = {"accounts": [{"account": "ann"}, {"account": "ann"}]}

    assert refusal(lambda: TerminalConfig.from_dict(raw)) == (
        "account_duplicate",
        {"account": "ann"},
    )


def test_the_open_chooses_among_the_enabled_accounts():
    config = TerminalConfig(accounts=[TerminalAccount("ann"), TerminalAccount("bob")])

    assert config.chosen("").account == "ann"
    assert config.chosen("bob").account == "bob"
    assert refusal(lambda: config.chosen("eve")) == (
        "account_not_enabled",
        {"account": "eve"},
    )
    assert refusal(lambda: TerminalConfig().chosen("")) == (
        "terminal_account_missing",
        {},
    )


def test_an_account_the_machine_lacks_is_unknown():
    config = TerminalConfig(accounts=[TerminalAccount("nobody-here-xyz")])

    assert refusal(lambda: config.validate(os_name="linux")) == (
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
    config = TerminalConfig(accounts=[TerminalAccount(ME, shell_path=path)])

    assert refusal(lambda: config.validate(os_name="linux")) == (
        "shell_program_unusable",
        {"path": path},
    )


def test_an_account_the_machine_has_and_a_program_it_runs_pass():
    TerminalConfig(accounts=[TerminalAccount(ME, shell_path="/bin/sh")]).validate(
        os_name="linux"
    )


def test_on_windows_the_machines_list_and_the_login_decide(tmp_path):
    shell = tmp_path / "pwsh.exe"
    shell.write_bytes(b"MZ")
    known = ["alice"]

    TerminalConfig(accounts=[TerminalAccount("alice", str(shell), "pw")]).validate(
        os_name="windows", known_accounts=known
    )
    assert refusal(
        lambda: TerminalConfig(accounts=[TerminalAccount("bob", "", "pw")]).validate(
            os_name="windows", known_accounts=known
        )
    ) == ("account_unknown", {"account": "bob"})
    assert refusal(
        lambda: TerminalConfig(accounts=[TerminalAccount("alice")]).validate(
            os_name="windows", known_accounts=known
        )
    ) == ("credential_missing", {"account": "alice"})
