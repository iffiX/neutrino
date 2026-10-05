"""``nagent step-down``: the drop's order, and a program run in its place.

What these pin: the account's group becomes the only supplementary group,
then the group, then the user, in that order; the program replaces the
process; a refusal of any step or of the program is said and exits 126;
no program, or root as the account, is refused before anything drops.
"""

from neutrino_agent.cli import step_down


class Calls:
    def __init__(self, failing=""):
        self.made = []
        self.failing = failing

    def __getattr__(self, name):
        def step(*args):
            self.made.append((name, *args))
            if name == self.failing:
                raise PermissionError(1, "Operation not permitted")

        return step


def patched(monkeypatch, failing=""):
    calls = Calls(failing)
    for name in ("setgroups", "setgid", "setuid", "execv"):
        monkeypatch.setattr(step_down.os, name, getattr(calls, name))
    return calls


def test_the_drop_is_groups_then_group_then_user_then_the_program(monkeypatch):
    calls = patched(monkeypatch)

    step_down.main(uid=502, gid=20, argv=["/usr/bin/osascript", "-e", "x"])

    assert calls.made == [
        ("setgroups", [20]),
        ("setgid", 20),
        ("setuid", 502),
        ("execv", "/usr/bin/osascript", ["/usr/bin/osascript", "-e", "x"]),
    ]


def test_a_refused_step_is_said_and_runs_nothing(monkeypatch, capsys):
    calls = patched(monkeypatch, failing="setuid")

    assert step_down.main(uid=502, gid=20, argv=["/usr/bin/true"]) == 126
    assert [made[0] for made in calls.made] == ["setgroups", "setgid", "setuid"]
    assert "Operation not permitted" in capsys.readouterr().err


def test_no_program_and_root_are_refused_before_any_drop(monkeypatch):
    calls = patched(monkeypatch)

    assert step_down.main(uid=502, gid=20, argv=[]) == 2
    assert step_down.main(uid=0, gid=0, argv=["/usr/bin/true"]) == 2
    assert calls.made == []
