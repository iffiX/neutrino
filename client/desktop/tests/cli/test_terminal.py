"""``nclient terminal``: choose the machine, attach both ways, say how it ended.

The resident is scripted: its state, its two kept connections and its
answers. Pinned: a machine named by id or name, a hub to tell two apart, the
exit statuses 0 closed, 1 refused, 2 not offered, the keys carried up and
the output carried down, and a resize going up as a request.
"""

import pytest

from neutrino_client.cli import terminal, wording
from neutrino_client.control import client

STATE = {
    "hubs": [
        {"hub_id": "h1", "hub_name": "home", "gateway_url": "https://h"},
        {"hub_id": "h2", "hub_name": "office", "gateway_url": "https://o"},
    ],
    "terminals": {
        "machines": [
            {"hub_id": "h1", "device_id": "d1", "name": "lepton", "is_online": True},
            {"hub_id": "h2", "device_id": "d2", "name": "lepton", "is_online": True},
            {"hub_id": "h2", "device_id": "d3", "name": "muon", "is_online": True},
        ],
        "sessions": [],
    },
}


class Kept:
    """One kept connection: what it hands back, and what it was sent."""

    def __init__(self, chunks=()):
        self.chunks = list(chunks)
        self.sent = []
        self.is_closed = False

    def read(self, size):
        return self.chunks.pop(0) if self.chunks else b""

    def send(self, data):
        self.sent.append(data)

    def close(self):
        self.is_closed = True


class FakeTerm:
    def __init__(self, keys=()):
        self.keys = list(keys)
        self.written = []
        self.resize = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def read(self):
        return self.keys.pop(0) if self.keys else b""

    def write(self, data):
        self.written.append(data)

    def on_resize(self, callback):
        self.resize = callback


class FakePlatform:
    def __init__(self, term):
        self.term = term

    def control_socket_path(self):
        return "/run/x.sock"

    def raw_terminal(self):
        return self.term


@pytest.fixture
def resident(monkeypatch):
    script = {
        "upgrades": [],
        "answers": {"/api/terminal/attach": (101, {"terminal_id": "t1"})},
        "requests": [],
        "result": {"exit_code": 0},
        "keys": Kept(),
        "output": Kept([b"$ ", b"bye"]),
    }
    monkeypatch.setattr(wording, "read_state", lambda: STATE)

    def upgrade(*, socket_path, path, body):
        script["upgrades"].append((path, body))
        if path == "/api/terminal/output":
            return 101, {"terminal_id": "t1"}, script["output"]
        status, reply = script["answers"][path]
        return status, reply, script["keys"] if status == 101 else None

    def request(method, path, body=None):
        script["requests"].append((path, body))
        if path == "/api/terminal/result":
            return 200, script["result"]
        return 200, {}

    monkeypatch.setattr(client, "upgrade", upgrade)
    monkeypatch.setattr(wording, "request", request)
    return script


def test_a_machine_by_name_on_the_hub_named_is_attached_and_carried(resident):
    term = FakeTerm(keys=[b"ls\n"])

    status = terminal.main("lepton", hub="office", platform=FakePlatform(term))

    assert status == terminal.EXIT_CLOSED
    path, body = resident["upgrades"][0]
    assert path == "/api/terminal/attach"
    assert (body["hub_id"], body["device_id"]) == ("h2", "d2")
    assert body["cols"] > 0 and body["rows"] > 0
    assert resident["upgrades"][1] == ("/api/terminal/output", {"terminal_id": "t1"})
    assert term.written == [b"$ ", b"bye"]
    assert resident["keys"].is_closed and resident["output"].is_closed


def test_a_machine_by_id_needs_no_hub(resident):
    assert terminal.main("d3", platform=FakePlatform(FakeTerm())) == 0
    assert resident["upgrades"][0][1]["session_id"] == ""


def test_a_session_named_is_attached_to_again(resident):
    status = terminal.main("d3", session_id="kept-1", platform=FakePlatform(FakeTerm()))

    assert status == 0
    assert resident["upgrades"][0][1]["session_id"] == "kept-1"


def test_a_session_the_machine_no_longer_keeps_is_exit_1_in_words(resident, capsys):
    resident["answers"]["/api/terminal/attach"] = (
        400,
        {"code": "session_unknown", "params": {"session_id": "kept-1"}},
    )

    status = terminal.main("d3", session_id="kept-1", platform=FakePlatform(FakeTerm()))

    assert status == terminal.EXIT_REFUSED
    assert "no longer keeps this session" in capsys.readouterr().err


def test_one_name_on_two_hubs_is_refused_as_ambiguous(resident, capsys):
    assert terminal.main("lepton", platform=FakePlatform(FakeTerm())) == 2
    assert "home" in capsys.readouterr().err


def test_a_machine_nobody_offers_is_exit_2(resident, capsys):
    assert terminal.main("tau", platform=FakePlatform(FakeTerm())) == 2
    assert resident["upgrades"] == []


def test_a_refused_attach_is_exit_1_in_words(resident, capsys):
    resident["answers"]["/api/terminal/attach"] = (
        403,
        {"code": "permission_denied", "params": {"kind": "terminal"}},
    )

    assert terminal.main("d1", platform=FakePlatform(FakeTerm())) == 1
    assert "terminal" in capsys.readouterr().err


def test_a_shell_the_hub_refused_after_the_open_is_exit_1(resident, capsys):
    resident["result"] = {"code": "agent_offline", "params": {"device": "d1"}}

    assert terminal.main("d1", platform=FakePlatform(FakeTerm())) == 1
    assert capsys.readouterr().err


def test_a_resize_goes_up_as_a_request(resident):
    term = FakeTerm()
    terminal.main("d1", platform=FakePlatform(term))

    term.resize(100, 30)

    assert resident["requests"][-1] == (
        "/api/terminal/resize",
        {"terminal_id": "t1", "cols": 100, "rows": 30},
    )
