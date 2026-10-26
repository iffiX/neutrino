"""``nclient rdp``: list and connect against a scripted client."""

import pytest

from neutrino_client.cli import rdp, wording


def test_list_prints_each_shared_desktop(running, capsys):
    running.state["services"][-1]["payload"]["attention"] = "rdp_nobody_seated"
    running.state["viewers"] = {"h1/rdp_d1": {"is_running": True}}

    assert rdp.main_list() == 0

    assert capsys.readouterr().out.strip() == (
        "lab-gpu  "
        + wording.word_code("rdp_nobody_seated")
        + "  "
        + wording.line("rdp_open")
    )


def test_connect_posts_connect_and_waits_for_the_viewer(running, capsys):
    reads = []

    def starting(state):
        reads.append(1)
        state["services"][-1]["job"] = "connecting" if len(reads) < 3 else ""

    running.on_state = starting

    assert rdp.main_connect("lab-gpu") == 0

    assert running.posts("/api/services/rdp") == [
        {"hub_id": "h1", "id": "rdp_d1", "action": "connect"}
    ]
    assert capsys.readouterr().out.strip() == "opening the viewer on lab-gpu"


def test_a_desktop_whose_viewer_runs_is_refused(running, capsys):
    running.state["viewers"] = {"h1/rdp_d1": {"is_running": True}}

    assert rdp.main_connect("lab-gpu") == 1
    assert running.posts("/api/services/rdp") == []
    assert capsys.readouterr().err.strip() == wording.word_code("rdp_viewer_open")


def test_a_failed_connect_prints_its_words(running, capsys):
    running.state["services"][-1]["last_error"] = {
        "code": "rdp_not_shared",
        "params": {},
    }

    assert rdp.main_connect("lab-gpu") == 1
    assert capsys.readouterr().err.strip() == wording.word_code("rdp_not_shared")


def test_a_machine_sharing_nothing_prints_the_ones_that_do(running, capsys):
    assert rdp.main_connect("build") == 1
    assert capsys.readouterr().err.strip() == (
        "no machine named build; there are: lab-gpu"
    )


@pytest.mark.parametrize(
    "call", [lambda: rdp.main_list(), lambda: rdp.main_connect("lab-gpu")]
)
def test_no_running_client_is_client_not_running(running, capsys, call):
    running.is_running = False

    assert call() == 1
    assert capsys.readouterr().err.strip() == wording.word_code("client_not_running")
