"""How the panel password is taken, on the two paths `setup` and `reset` share.

The password is never an argument, so the only ways in are a prompt and one
line of standard input. Both refuse what cannot be used before anything is
written.
"""

import io

import pytest

from neutrino_hub.cli.password import PasswordRefused, read_new_password
from neutrino_hub.utils.passwords import PASSWORDS_MASTER_RULES, PASSWORDS_PANEL_RULES


def test_a_password_read_from_standard_input_is_not_asked_for_twice(monkeypatch):
    """An unattended install has nobody to answer a second prompt."""
    monkeypatch.setattr("sys.stdin", io.StringIO("a-long-enough-password\n"))

    assert read_new_password(is_stdin=True) == "a-long-enough-password"


def test_a_short_password_is_refused_before_anything_is_written(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("short\n"))

    with pytest.raises(PasswordRefused, match=str(PASSWORDS_PANEL_RULES.min_length)):
        read_new_password(is_stdin=True)


def test_a_passphrase_missing_a_class_is_refused_with_what_it_lacks(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("all-lowercase-and-long\n"))

    with pytest.raises(PasswordRefused, match="uppercase"):
        read_new_password(is_stdin=True, rules=PASSWORDS_MASTER_RULES)


def test_a_passphrase_meeting_the_master_rules_is_taken(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("A-vault-passphrase-16!\n"))

    accepted = read_new_password(is_stdin=True, rules=PASSWORDS_MASTER_RULES)

    assert accepted == "A-vault-passphrase-16!"  # scan: allow


def test_two_prompts_that_disagree_are_refused(monkeypatch):
    monkeypatch.setattr(
        "getpass.getpass", _answering("a-long-enough-password", "a-different-password")
    )

    with pytest.raises(PasswordRefused, match="do not match"):
        read_new_password()


def test_two_prompts_that_agree_give_the_password(monkeypatch):
    monkeypatch.setattr(
        "getpass.getpass",
        _answering("a-long-enough-password", "a-long-enough-password"),
    )

    assert read_new_password() == "a-long-enough-password"


def _answering(*answers: str):
    """A getpass that gives each answer in turn."""
    remaining = iter(answers)

    def prompt(_message: str) -> str:
        return next(remaining)

    return prompt
