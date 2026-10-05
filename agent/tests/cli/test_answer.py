"""``nagent answer``: any account runs a program on a terminal and answers it.

What these pin: the verb is not one root alone may run, since the agent runs
it as an account; the program after ``--`` gets the answer and Enter, its
drawing is printed, and its exit code is the command's; no program is 2.
"""

import sys

import pytest

from neutrino_agent.cli import answer, entry

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX terminals")

PROGRAM = (
    "import sys\n"
    "reply = input('Delete it? (y/N) ')\n"
    "print('got', reply)\n"
    "sys.exit(7 if reply == 'y' else 1)\n"
)


def test_any_account_may_run_it():
    assert "answer" not in entry.ROOT_COMMANDS


def test_the_program_after_the_dashes_is_answered_and_its_code_is_the_verb_s(
    monkeypatch, capsys
):
    monkeypatch.setattr(entry.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(
        entry.sys,
        "argv",
        [
            "nagent",
            "answer",
            "--prompt",
            "(y/N)",
            "--answer",
            "y",
            "--",
            sys.executable,
            "-c",
            PROGRAM,
        ],
    )

    assert entry.main() == 7
    assert "got y" in capsys.readouterr().out


def test_no_program_is_2(capsys):
    assert answer.main(prompt="(y/N)", answer="y", argv=[]) == 2
    assert "needs a program" in capsys.readouterr().err
