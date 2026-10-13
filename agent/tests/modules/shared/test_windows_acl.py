"""Access lists on Windows through icacls, with the tool faked.

What these pin: a path left to an account drops what it inherits and
grants the account its right, SYSTEM and the administrators full control,
each by its well-known SID, the grants reaching a directory's contents
when it is a tree; the Users group is granted read and run on a tree; a
refusal or a tool that does not finish is ``OSError``.
"""

import subprocess

import pytest

from neutrino_agent.modules.shared.subprocess_run import CommandResult
from neutrino_agent.modules.shared.windows_acl import (
    grant_account_alone,
    icacls,
    open_to_users,
)


class Icacls:
    def __init__(self, code=0, error=None):
        self.calls: list = []
        self.code = code
        self.error = error

    def __call__(self, argv, *, is_checked=True, **_):
        assert is_checked is False
        self.calls.append(list(argv))
        if self.error is not None:
            raise self.error
        return CommandResult(
            command=list(argv), exit_code=self.code, stdout="x", stderr=""
        )


def test_a_file_is_left_to_its_account_system_and_the_administrators():
    run = Icacls()

    grant_account_alone(run, "D:\\run\\ann.cmd", "ann", "R", is_tree=False)

    assert run.calls == [
        [
            "icacls.exe",
            "D:\\run\\ann.cmd",
            "/inheritance:r",
            "/grant:r",
            "ann:R",
            "*S-1-5-18:F",
            "*S-1-5-32-544:F",
        ]
    ]


def test_a_tree_s_grants_reach_what_it_holds():
    run = Icacls()

    grant_account_alone(run, "D:\\run_as\\ann", "ann", "M", is_tree=True)

    assert run.calls[0][4:] == [
        "ann:(OI)(CI)M",
        "*S-1-5-18:(OI)(CI)F",
        "*S-1-5-32-544:(OI)(CI)F",
    ]


def test_the_users_group_reads_and_runs_a_tree():
    run = Icacls()

    open_to_users(run, "D:\\state\\vscode")

    assert run.calls == [
        ["icacls.exe", "D:\\state\\vscode", "/grant", "*S-1-5-32-545:(OI)(CI)RX"]
    ]


def test_a_refusal_or_a_tool_that_does_not_finish_is_an_os_error():
    with pytest.raises(OSError, match="icacls refused D:\\\\x"):
        grant_account_alone(Icacls(5), "D:\\x", "ann", "R", is_tree=False)
    with pytest.raises(OSError, match="icacls exited 5"):
        open_to_users(Icacls(5), "D:\\x")
    with pytest.raises(OSError, match="did not finish"):
        icacls(Icacls(error=subprocess.TimeoutExpired("icacls.exe", 120)), ["D:\\x"])
