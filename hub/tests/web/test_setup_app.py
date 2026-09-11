"""The wizard a browser answers, and the token that is all that guards it.

`nhub setup` serves this before there is a password to ask for, so the token
the terminal printed is the whole of the access control. Everything else here
is a transport: the browser posts the same answers document `--stdin` takes,
and the terminal says whether it can be used.
"""

import pytest
from fastapi.testclient import TestClient

from neutrino_hub.web.setup_app import WebSetupSession, create_setup_app

CONTEXT = {
    "interfaces": [{"name": "eth0", "is_wired": True}],
    "modes": [{"key": "server"}],
    "services": [],
    "defaults": {"address": "192.168.8.1"},
}
ANSWERS = {"password": "12345678", "network": {"mode": "server", "lan": ["eth0"]}}


@pytest.fixture
def session():
    return WebSetupSession(context=CONTEXT)


@pytest.fixture
def client(session):
    return TestClient(create_setup_app(session))


def test_the_questions_need_the_token_the_terminal_printed(client):
    assert client.get("/api/setup/context").status_code == 403
    assert client.get("/api/setup/context?token=guessed").status_code == 403


def test_the_token_opens_the_questions(client, session):
    answer = client.get(f"/api/setup/context?token={session.token}").json()

    assert answer["modes"] == [{"key": "server"}]
    assert answer["interfaces"][0]["name"] == "eth0"


def test_answers_reach_the_terminal_that_is_waiting(client, session):
    posted = client.post(f"/api/setup/answers?token={session.token}", json=ANSWERS)

    assert posted.status_code == 202
    assert session.wait(0.1) == ANSWERS
    assert posted.json()["state"] == "running"


def test_answers_need_the_token_too(client, session):
    assert (
        client.post("/api/setup/answers?token=guessed", json=ANSWERS).status_code == 403
    )
    assert session.wait(0.01) == {}


def test_a_refused_document_sends_the_browser_back_to_the_questions(client, session):
    client.post(f"/api/setup/answers?token={session.token}", json=ANSWERS)
    session.reject("'network' needs a 'mode'")

    state = client.get(f"/api/setup/state?token={session.token}").json()

    assert state["state"] == "rejected"
    assert state["message"] == "'network' needs a 'mode'"
    # And the wait is open again, so the next post is picked up.
    assert session.wait(0.01) == {}


def test_a_step_moves_in_place_rather_than_twice(client, session):
    session.step("systemd_units", "running")
    session.step("systemd_units", "done", "wrote 5")

    steps = client.get(f"/api/setup/state?token={session.token}").json()["steps"]

    assert steps == [
        {
            "id": "systemd_units",
            "params": {},
            "status": "done",
            "note": "wrote 5",
        }
    ]


def test_a_step_named_once_per_module_keeps_a_line_each(client, session):
    """Two installs are two rows: the id is the same and the module is not."""
    session.step("install_module", "done", params={"name": "netbird"})
    session.step("install_module", "running", params={"name": "cliproxyapi"})

    steps = client.get(f"/api/setup/state?token={session.token}").json()["steps"]

    assert [step["params"]["name"] for step in steps] == ["netbird", "cliproxyapi"]


def test_finishing_says_where_the_panel_will_be(client, session):
    session.step("start_services", "running")
    session.finish(panel_url="http://192.168.8.1:8080")

    state = client.get(f"/api/setup/state?token={session.token}").json()

    assert state["state"] == "done"
    assert state["panel_url"] == "http://192.168.8.1:8080"
    # A step still running when the panel takes over never finished.
    assert state["steps"][0]["status"] == "failed"


def test_a_route_nobody_serves_is_missing_rather_than_the_app(client):
    """The page asks whether it is talking to a wizard or to a panel, and a
    shell served with a 200 on it answers neither."""
    assert client.get("/api/setup/nothing").status_code == 404


def test_a_port_already_taken_is_a_failure_rather_than_a_wait(session):
    """Something else on the panel's port would otherwise leave the terminal
    waiting for a browser that can never connect."""
    import socket

    from neutrino_hub.web.setup_app import WebSetupServer

    held = socket.socket()
    held.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    held.bind(("127.0.0.1", 0))
    held.listen(1)
    try:
        server = WebSetupServer(
            session=session, host="127.0.0.1", port=held.getsockname()[1]
        )
        assert not server.start()
    finally:
        held.close()


def test_it_serves_once_it_has_the_port(session):
    from neutrino_hub.web.setup_app import WebSetupServer

    server = WebSetupServer(session=session, host="127.0.0.1", port=0)
    try:
        assert server.start()
    finally:
        server.stop()
