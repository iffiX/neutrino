"""``nclient hub``: list, join, leave and open against a scripted client.

``list`` numbers each hub and draws its state line as the Hubs page does:
the way in and the round trip while connected, the reason and countdown
while waiting. ``join`` posts the link, ``leave`` asks ``[y/N]`` unless
``--yes``, and ``open`` waits for the panel's job and words its failure.
Every verb with no running client prints ``client_not_running`` and exits 1.
"""

import time

import pytest

from neutrino_client.cli import hub, wording


def test_list_numbers_each_hub_with_its_state_line(running, capsys):
    running.state["hubs"][1]["next_round_at"] = time.time() + 30

    assert hub.main_list() == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split() == ["1", "home", "Connected", "·", "LAN", "·", "3", "ms"]
    assert lines[1].startswith("2  office  The hub did not answer · retrying in ")


def test_list_says_a_refused_join_and_a_client_too_old(running, capsys):
    running.state["hubs"][0].update(
        connection="waiting",
        wait_reason="join_refused",
        wait_code={"code": "ticket_spent", "params": {}},
    )
    running.state["hubs"][1].update(
        wait_reason="too_old",
        wait_code={"code": "protocol_too_old", "params": {}},
    )

    assert hub.main_list() == 0

    out = capsys.readouterr().out
    assert "Join refused · " + wording.word_code("ticket_spent") in out
    assert "Version too old · update the client" in out


def test_list_speaks_chinese_when_the_client_does(running, chinese, capsys):
    assert hub.main_list() == 0

    assert "已连接 · 局域网 · 3 ms" in capsys.readouterr().out


def test_list_says_no_hub_is_joined(running, capsys):
    running.state["hubs"] = []

    assert hub.main_list() == 0
    assert capsys.readouterr().out.strip() == wording.line("not_joined")


def test_join_posts_the_link_and_names_the_new_hub(running, capsys):
    after = dict(running.state)
    after["hubs"] = running.state["hubs"] + [
        {
            "hub_id": "",
            "hub_name": "",
            "binding_id": "p1",
            "gateway_url": "tcp://n:8443",
        }
    ]
    running.answers["/api/join"] = lambda body: (200, after)

    assert hub.main_join("neutrino://enroll/abc") == 0

    assert running.posts("/api/join") == [{"link": "neutrino://enroll/abc"}]
    assert capsys.readouterr().out.strip() == "joined tcp://n:8443; connecting"


def test_a_refused_link_prints_its_words_and_exits_1(running, capsys):
    refused = dict(running.state, error={"code": "link_unreadable", "params": {}})
    running.answers["/api/join"] = lambda body: (200, refused)

    assert hub.main_join("nonsense") == 1
    assert capsys.readouterr().err.strip() == wording.word_code("link_unreadable")


def test_join_asks_for_the_link_when_none_is_given(running, monkeypatch):
    monkeypatch.setattr(wording, "ask_text", lambda prompt: "neutrino://enroll/typed")

    assert hub.main_join("") == 0
    assert running.posts("/api/join") == [{"link": "neutrino://enroll/typed"}]


def test_leave_with_yes_asks_nothing(running, capsys):
    assert hub.main_leave("office", is_forced=True) == 0

    assert running.posts("/api/leave") == [{"hub_id": "h2"}]
    assert capsys.readouterr().out.strip() == "left office"


def test_leave_names_the_hub_by_its_number(running):
    assert hub.main_leave("1", is_forced=True) == 0
    assert running.posts("/api/leave") == [{"hub_id": "h1"}]


def test_leave_asks_first_and_a_no_changes_nothing(running, monkeypatch, capsys):
    asked = []
    monkeypatch.setattr(
        wording, "is_confirmed", lambda question: asked.append(question) or False
    )

    assert hub.main_leave("home") == 1
    assert running.posts("/api/leave") == []
    assert asked == [wording.line("leave_question", hub="home")]
    assert capsys.readouterr().out.strip() == "nothing changed"


def test_leave_of_a_hub_nobody_joined_prints_the_hubs_there_are(running, capsys):
    assert hub.main_leave("lab", is_forced=True) == 1

    assert capsys.readouterr().err.strip() == (
        "no hub named lab; there are: home, office"
    )


def test_open_waits_for_the_panel_and_says_it_opens(running, capsys):
    reads = []

    def opening(state):
        reads.append(1)
        state["hubs"][0]["jobs"]["is_opening_panel"] = len(reads) < 3

    running.on_state = opening

    assert hub.main_open("home") == 0
    assert running.posts("/api/panel/open") == [{"hub_id": "h1"}]
    assert len(reads) == 3
    assert capsys.readouterr().out.strip() == "opening the panel of home"


def test_open_words_the_failure_of_its_job(running, capsys):
    running.state["hubs"][0]["last_error"] = {
        "code": "permission_denied",
        "params": {"kind": "panel"},
    }

    assert hub.main_open("home") == 1
    assert capsys.readouterr().err.strip() == (
        "the hub gives this client no panel permission"
    )


def test_open_answered_with_a_refusal_exits_1(running, capsys):
    running.answers["/api/panel/open"] = lambda body: (
        403,
        {"code": "client_disabled", "params": {}},
    )

    assert hub.main_open("1") == 1
    assert capsys.readouterr().err.strip() == wording.word_code("client_disabled")


@pytest.mark.parametrize(
    "call",
    [
        lambda: hub.main_list(),
        lambda: hub.main_join("neutrino://enroll/x"),
        lambda: hub.main_leave("home", is_forced=True),
        lambda: hub.main_open("home"),
    ],
)
def test_no_running_client_is_client_not_running(running, capsys, call):
    running.is_running = False

    assert call() == 1
    assert capsys.readouterr().err.strip() == wording.word_code("client_not_running")
