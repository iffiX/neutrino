"""``nclient ai``: show and set against a scripted client.

``show`` prints each tool's gateway address and whether it is the hub's;
``set`` is the chip turned on at the exit hub, the hub named making it the
exit first, waited for until the switch ends; a computer the agent is
installed on is refused ``ai_tools_managed``.
"""

import pytest

from neutrino_client.cli import ai, wording


def test_show_says_the_tools_are_their_own_while_off(running, capsys):
    assert ai.main_show() == 0

    assert capsys.readouterr().out.splitlines() == [
        "claude  -  its own",
        "codex   -  its own",
        "gemini  -  its own",
    ]


def test_show_names_the_forward_and_the_hub_while_on(running, capsys):
    running.state["ai"]["is_active"] = True
    running.state["services"][6]["forward"] = 20001
    running.state["exit_hub_id"] = "h1"

    assert ai.main_show() == 0

    assert capsys.readouterr().out.splitlines()[0] == (
        "claude  http://127.0.0.1:20001  the hub's (home)"
    )


def test_show_says_a_managed_computer_is_set_from_the_panel(running, capsys):
    running.state["ai"]["is_managed"] = True

    assert ai.main_show() == 0
    assert wording.word_code("ai_tools_managed") in capsys.readouterr().out


def test_set_points_the_tools_at_the_gateway_and_says_where(running, capsys):
    running.state["exit_hub_id"] = "h1"
    running.state["services"][6]["forward"] = 20001

    assert ai.main_set() == 0

    assert running.posts("/api/exit/set") == []
    assert running.posts("/api/services/ai") == [
        {
            "hub_id": "h1",
            "id": "ai",
            "is_enabled": True,
            "tool_configs": {"claude": {"default": "m1"}},
        }
    ]
    assert (
        capsys.readouterr().out.strip() == "the tools point at http://127.0.0.1:20001"
    )


def test_set_makes_the_gateways_hub_the_exit_first(running):
    assert ai.main_set() == 0

    assert running.posts("/api/exit/set") == [{"hub_id": "h1"}]


def test_set_waits_while_the_tools_switch(running):
    reads = []

    def switching(state):
        reads.append(1)
        state["ai"]["work"] = {"state": "working" if len(reads) < 3 else "idle"}

    running.state["exit_hub_id"] = "h1"
    running.on_state = switching

    assert ai.main_set() == 0
    assert len(reads) == 3


def test_set_on_a_managed_computer_is_refused(running, capsys):
    running.state["ai"]["is_managed"] = True

    assert ai.main_set() == 1
    assert running.posts("/api/services/ai") == []
    assert capsys.readouterr().err.strip() == wording.word_code("ai_tools_managed")


def test_a_switch_that_failed_prints_its_words(running, capsys):
    running.state["exit_hub_id"] = "h1"
    running.state["ai"].update(code="switch_failed", params={"detail": "no cc-switch"})

    assert ai.main_set() == 1
    assert capsys.readouterr().err.strip() == "no cc-switch"


def test_no_gateway_published_is_said(running, capsys):
    running.state["services"] = [
        row for row in running.state["services"] if row["type"] != "ai"
    ]

    assert ai.main_set() == 1
    assert capsys.readouterr().err.strip() == wording.line("ai_none")


@pytest.mark.parametrize("call", [lambda: ai.main_show(), lambda: ai.main_set()])
def test_no_running_client_is_client_not_running(running, capsys, call):
    running.is_running = False

    assert call() == 1
    assert capsys.readouterr().err.strip() == wording.word_code("client_not_running")
