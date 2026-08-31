"""How the panel password is taken, on the two paths `setup` and `reset` share.

The password is never an argument, so the only ways in are a prompt and one
line of standard input. Both refuse what cannot be used before anything is
written.
"""

import io

import pytest

from neutrino_hub.cli.password import (
    PASSWORD_MIN_LENGTH,
    PasswordRefused,
    read_new_password,
)


def test_a_password_read_from_standard_input_is_not_asked_for_twice(monkeypatch):
    """An unattended install has nobody to answer a second prompt."""
    monkeypatch.setattr("sys.stdin", io.StringIO("a-long-enough-password\n"))

    assert read_new_password(is_stdin=True) == "a-long-enough-password"


def test_a_short_password_is_refused_before_anything_is_written(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("short\n"))

    with pytest.raises(PasswordRefused, match=str(PASSWORD_MIN_LENGTH)):
        read_new_password(is_stdin=True)


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
