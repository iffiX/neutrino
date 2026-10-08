"""``nclient terminal``: the seven verbs against a scripted resident.

The resident is scripted: its state, its kept connections and its answers.
Pinned: a machine named by id or name, a hub to tell two apart, and a
machine offered for the verb's kind only; ``open`` and ``attach`` with 0
closed, 1 refused, 2 not offered, the keys carried up and the output down,
a resize as a request, ``--shared`` in the open and ``--persistent`` as a
persist after the first output; a session id matched by prefix with one,
none and several matches; ``exec`` returning the remote code, 125 for a
refusal and 126 for no machine, stdout and stderr apart, stdin ended with
the empty piece, and raw mode only with ``--tty`` on a terminal; ``list``'s
columns and its JSON; ``persist``, ``share`` and ``stop`` with one flag
each and their refusals.
"""

import io
import json
import time

import pytest

from neutrino_client.cli import terminal, wording
from neutrino_client.control import client
from neutrino_client.core.terminal import encode_piece, read_piece

SESSION = "3f2a1b4c-0000-4000-8000-000000000001"
OTHER_SESSION = "3f2a9999-0000-4000-8000-000000000002"
STATE = {
    "hubs": [
        {"hub_id": "h1", "hub_name": "home", "gateway_url": "https://h"},
        {"hub_id": "h2", "hub_name": "office", "gateway_url": "https://o"},
    ],
    "terminals": {
        "machines": [
            {
                "hub_id": "h1",
                "device_id": "d1",
                "name": "lepton",
                "is_online": True,
                "is_shell_allowed": True,
                "is_exec_allowed": True,
            },
            {
                "hub_id": "h2",
                "device_id": "d2",
                "name": "lepton",
                "is_online": True,
                "is_shell_allowed": True,
                "is_exec_allowed": False,
            },
            {
                "hub_id": "h2",
                "device_id": "d3",
                "name": "muon",
                "is_online": True,
                "is_shell_allowed": True,
                "is_exec_allowed": True,
            },
            {
                "hub_id": "h2",
                "device_id": "d4",
                "name": "tau",
                "is_online": True,
                "is_shell_allowed": False,
                "is_exec_allowed": True,
            },
            {
                "hub_id": "h2",
                "device_id": "d5",
                "name": "gone",
                "is_online": False,
                "is_shell_allowed": True,
                "is_exec_allowed": True,
            },
        ],
        "sessions": [
            {
                "hub_id": "h2",
                "device_id": "d3",
                "session_id": SESSION,
                "title": "vim notes.md",
                "account": "alice",
                "owner": "client:c1",
                "owner_name": "box",
                "is_owned": True,
                "is_persistent": True,
                "is_shared": False,
                "attached_count": 2,
            },
            {
                "hub_id": "h2",
                "device_id": "d3",
                "session_id": OTHER_SESSION,
                "title": "top",
                "account": "root",
                "owner": "hub",
                "owner_name": "office",
                "is_owned": False,
                "is_persistent": False,
                "is_shared": True,
                "attached_count": 1,
            },
        ],
    },
}


class Kept:
    """One kept connection: what it hands back, and what it was sent."""

    def __init__(self, chunks=()):
        self.chunks = list(chunks)
        self.sent = []
        self.is_closed = False

    def read(self, size):
        if not self.chunks:
            return b""
        data, rest = self.chunks[0][:size], self.chunks[0][size:]
        if rest:
            self.chunks[0] = rest
        else:
            self.chunks.pop(0)
        return data

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
    def __init__(self, term=None):
        self.term = term

    def control_socket_path(self):
        return "/run/x.sock"

    def raw_terminal(self):
        assert self.term is not None, "raw mode was entered"
        return self.term


class TerminalInput(io.BytesIO):
    """Standard input that is a terminal."""

    def isatty(self):
        return True


class BrokenOutput(io.BytesIO):
    def write(self, data):
        raise BrokenPipeError("the reader went away")


@pytest.fixture
def resident(monkeypatch):
    script = {
        "upgrades": [],
        "answers": {
            "/api/terminal/attach": (101, {"terminal_id": "t1"}),
            "/api/terminal/exec": (101, {"terminal_id": "t1"}),
        },
        "requests": [],
        "replies": {},
        "result": {"exit_code": 0},
        "keys": Kept(),
        "output": Kept([b"$ ", b"bye"]),
        "state": json.loads(json.dumps(STATE)),
    }
    monkeypatch.setattr(wording, "read_state", lambda: script["state"])

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
        return script["replies"].get(path, (200, {}))

    monkeypatch.setattr(client, "upgrade", upgrade)
    monkeypatch.setattr(wording, "request", request)
    return script


def wait_for(condition) -> None:
    deadline = time.monotonic() + 5
    while not condition():
        assert time.monotonic() < deadline
        time.sleep(0.01)


def pieces(*frames) -> list:
    """The output connection's chunks: one piece per frame."""
    return [encode_piece(frame) for frame in frames]


def sent_pieces(kept) -> list:
    stream = io.BytesIO(b"".join(kept.sent))
    found = []
    while True:
        piece = read_piece(stream.read)
        if piece is None:
            return found
        found.append(piece)


# --- open and attach ---


def test_a_machine_by_name_on_the_hub_named_is_opened_and_carried(resident):
    term = FakeTerm(keys=[b"ls\n"])

    status = terminal.main_open("lepton", hub="office", platform=FakePlatform(term))

    assert status == terminal.EXIT_CLOSED
    path, body = resident["upgrades"][0]
    assert path == "/api/terminal/attach"
    assert (body["hub_id"], body["device_id"], body["session_id"]) == ("h2", "d2", "")
    assert "is_shared" not in body
    assert body["cols"] > 0 and body["rows"] > 0
    assert resident["upgrades"][1] == ("/api/terminal/output", {"terminal_id": "t1"})
    assert term.written == [b"$ ", b"bye"]
    assert resident["keys"].is_closed and resident["output"].is_closed


def test_a_machine_by_id_needs_no_hub(resident):
    assert terminal.main_open("d3", platform=FakePlatform(FakeTerm())) == 0


def test_shared_is_in_the_open_and_persistent_follows_the_first_output(resident):
    status = terminal.main_open(
        "d3", is_shared=True, is_persistent=True, platform=FakePlatform(FakeTerm())
    )

    assert status == 0
    assert resident["upgrades"][0][1]["is_shared"] is True
    wait_for(
        lambda: ("/api/terminal/persist", {"terminal_id": "t1", "is_persistent": True})
        in resident["requests"]
    )


def test_a_session_prefix_is_attached_to_by_its_whole_id(resident):
    status = terminal.main_attach("muon", "3f2a1", platform=FakePlatform(FakeTerm()))

    assert status == 0
    assert resident["upgrades"][0][1]["session_id"] == SESSION


def test_a_prefix_no_session_has_is_exit_2_in_words(resident, capsys):
    status = terminal.main_attach("muon", "ffff", platform=FakePlatform(FakeTerm()))

    assert status == terminal.EXIT_NO_MACHINE
    assert "no longer keeps this session" in capsys.readouterr().err
    assert resident["upgrades"] == []


def test_a_prefix_several_sessions_have_prints_them_and_is_exit_2(resident, capsys):
    status = terminal.main_attach("muon", "3f2a", platform=FakePlatform(FakeTerm()))

    err = capsys.readouterr().err
    assert status == terminal.EXIT_NO_MACHINE
    assert SESSION in err and OTHER_SESSION in err
    assert resident["upgrades"] == []


def test_a_session_the_machine_no_longer_keeps_is_exit_1_in_words(resident, capsys):
    resident["answers"]["/api/terminal/attach"] = (
        400,
        {"code": "session_unknown", "params": {"session_id": SESSION}},
    )

    status = terminal.main_attach("d3", SESSION, platform=FakePlatform(FakeTerm()))

    assert status == terminal.EXIT_REFUSED
    assert "no longer keeps this session" in capsys.readouterr().err


def test_one_name_on_two_hubs_is_refused_as_ambiguous(resident, capsys):
    assert terminal.main_open("lepton", platform=FakePlatform(FakeTerm())) == 2
    assert "home" in capsys.readouterr().err


def test_a_machine_nobody_offers_a_shell_on_is_exit_2(resident, capsys):
    assert terminal.main_open("pion", platform=FakePlatform(FakeTerm())) == 2
    assert terminal.main_open("tau", platform=FakePlatform(FakeTerm())) == 2
    assert resident["upgrades"] == []


def test_a_refused_open_is_exit_1_in_words(resident, capsys):
    resident["answers"]["/api/terminal/attach"] = (
        403,
        {"code": "permission_denied", "params": {"kind": "terminal"}},
    )

    assert terminal.main_open("d1", platform=FakePlatform(FakeTerm())) == 1
    assert "terminal" in capsys.readouterr().err


def test_a_shell_the_hub_refused_after_the_open_is_exit_1(resident, capsys):
    resident["result"] = {"code": "agent_offline", "params": {"device": "d1"}}

    assert terminal.main_open("d1", platform=FakePlatform(FakeTerm())) == 1
    assert capsys.readouterr().err


def test_a_shell_that_exits_with_a_code_is_still_exit_0(resident):
    resident["result"] = {"exit_code": 5}

    assert terminal.main_open("d1", platform=FakePlatform(FakeTerm())) == 0


def test_a_resize_goes_up_as_a_request(resident):
    term = FakeTerm()
    terminal.main_open("d1", platform=FakePlatform(term))

    term.resize(100, 30)

    assert resident["requests"][-1] == (
        "/api/terminal/resize",
        {"terminal_id": "t1", "cols": 100, "rows": 30},
    )


# --- exec ---


def run_exec(resident, *, stdin=b"", command=("ls",), machine="muon", **options):
    out, err = io.BytesIO(), io.BytesIO()
    source = stdin if isinstance(stdin, io.BytesIO) else io.BytesIO(stdin)
    status = terminal.main_exec(
        machine,
        list(command),
        platform=options.pop("platform", FakePlatform()),
        stdin=source,
        stdout=options.pop("stdout", out),
        stderr=err,
        **options,
    )
    return status, out.getvalue(), err.getvalue()


def test_exec_returns_the_remote_code_with_stdout_and_stderr_apart(resident):
    resident["output"] = Kept(pieces(b"\x01rows\n", b"\x02warning\n", b"\x01done\n"))
    resident["result"] = {"exit_code": 3}

    status, out, err = run_exec(resident, command=["psql", "app"])

    assert status == 3
    assert (out, err) == (b"rows\ndone\n", b"warning\n")
    path, body = resident["upgrades"][0]
    assert path == "/api/terminal/exec"
    assert (body["hub_id"], body["device_id"], body["argv"], body["is_tty"]) == (
        "h2",
        "d3",
        ["psql", "app"],
        False,
    )
    assert "session_id" not in body


def test_execs_stdin_goes_up_and_ends_with_the_empty_piece(resident):
    resident["output"] = Kept(pieces(b"\x01ok"))

    run_exec(resident, stdin=b"select 1;\n")

    wait_for(lambda: sent_pieces(resident["keys"])[-1:] == [b""])
    assert b"".join(sent_pieces(resident["keys"])) == b"select 1;\n"


def test_exec_without_tty_never_enters_raw_mode_on_a_terminal(resident):
    resident["output"] = Kept(pieces(b"\x01up 3 days"))

    status, out, _err = run_exec(resident, stdin=TerminalInput(b""))

    assert (status, out) == (0, b"up 3 days")


def test_exec_with_tty_and_no_terminal_runs_on_pipes(resident):
    resident["output"] = Kept(pieces(b"\x01top"))

    status, out, _err = run_exec(resident, is_tty=True)

    assert (status, out) == (0, b"top")
    assert resident["upgrades"][0][1]["is_tty"] is True
    assert all(piece for piece in sent_pieces(resident["keys"]))


def test_exec_with_tty_on_a_terminal_goes_through_raw_mode(resident):
    resident["output"] = Kept(pieces(b"\x01screen"))
    term = FakeTerm(keys=[b"q"])

    status, _out, _err = run_exec(
        resident, stdin=TerminalInput(b""), is_tty=True, platform=FakePlatform(term)
    )

    assert status == 0
    assert term.written == [b"screen"]
    term.resize(90, 20)
    assert resident["requests"][-1][0] == "/api/terminal/resize"


@pytest.mark.parametrize("machine", ["pion", "d2"])
def test_exec_on_a_machine_not_offered_for_commands_is_126(resident, machine):
    status, _out, _err = run_exec(resident, machine=machine)

    assert status == terminal.EXIT_EXEC_NO_MACHINE
    assert resident["upgrades"] == []


def test_exec_on_a_machine_offered_for_commands_alone_runs(resident):
    status, _out, _err = run_exec(resident, machine="tau")

    assert status == 0
    assert resident["upgrades"][0][1]["device_id"] == "d4"


def test_execs_refused_open_is_125_in_words(resident, capsys):
    resident["answers"]["/api/terminal/exec"] = (
        403,
        {"code": "permission_denied", "params": {"kind": "exec"}},
    )

    status, _out, _err = run_exec(resident)

    assert status == terminal.EXIT_EXEC_REFUSED
    assert "exec" in capsys.readouterr().err


def test_a_command_the_machine_cannot_run_is_125_in_words(resident, capsys):
    resident["output"] = Kept()
    resident["result"] = {"code": "shell_program_unusable", "params": {"path": "nope"}}

    status, _out, _err = run_exec(resident, command=["nope"])

    assert status == terminal.EXIT_EXEC_REFUSED
    assert "cannot run nope" in capsys.readouterr().err


def test_exec_with_no_command_is_125(resident, capsys):
    status, _out, _err = run_exec(resident, command=[])

    assert status == terminal.EXIT_EXEC_REFUSED
    assert "--" in capsys.readouterr().err
    assert resident["upgrades"] == []


def test_an_output_nobody_reads_any_more_ends_exec_at_125(resident):
    resident["output"] = Kept(pieces(b"\x01lines"))

    status, _out, _err = run_exec(resident, stdout=BrokenOutput())

    assert status == terminal.EXIT_EXEC_REFUSED
    assert resident["keys"].is_closed and resident["output"].is_closed


# --- list ---


def test_list_prints_every_online_machine_and_its_sessions(resident, capsys):
    assert terminal.main_list() == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split() == list(wording.TERMINAL_LIST_COLUMNS)
    assert lines[1].split() == ["lepton", "home"] + ["-"] * 8
    rows = [line.split() for line in lines if line.startswith("muon")]
    assert rows[0][:5] == ["muon", "office", SESSION[:8], "vim", "notes.md"]
    assert rows[0][5:] == ["alice", "box", "yes", "yes", "no", "2"]
    assert rows[1] == [
        "muon",
        "office",
        OTHER_SESSION[:8],
        "top",
        "root",
        "office",
        "no",
        "no",
        "yes",
        "1",
    ]
    assert not any(line.startswith("gone") for line in lines)


def test_list_as_json_is_one_object_of_whole_ids(resident, capsys):
    assert terminal.main_list(hub="office", is_json=True) == 0

    listed = json.loads(capsys.readouterr().out)
    assert [row["name"] for row in listed["machines"]] == ["lepton", "muon", "tau"]
    muon = listed["machines"][1]
    assert (muon["hub_name"], muon["is_exec_allowed"]) == ("office", True)
    assert muon["sessions"][0] == {
        "session_id": SESSION,
        "title": "vim notes.md",
        "account": "alice",
        "owner": "client:c1",
        "owner_name": "box",
        "is_owned": True,
        "is_persistent": True,
        "is_shared": False,
        "attached_count": 2,
    }


def test_list_without_a_running_client_is_exit_1(resident, monkeypatch):
    monkeypatch.setattr(wording, "read_state", lambda: None)

    assert terminal.main_list() == 1


# --- persist, share and stop ---


def test_persist_and_share_each_send_one_flag_for_the_whole_id(resident):
    assert terminal.main_persist("muon", "3f2a1", is_on=True) == 0
    assert terminal.main_share("muon", "3f2a1", is_on=False) == 0

    assert resident["requests"] == [
        (
            "/api/terminal/persist",
            {"is_persistent": True, "hub_id": "h2", "session_id": SESSION},
        ),
        (
            "/api/terminal/persist",
            {"is_shared": False, "hub_id": "h2", "session_id": SESSION},
        ),
    ]


def test_stop_names_the_session(resident):
    assert terminal.main_stop("muon", "3f2a9") == 0

    assert resident["requests"] == [
        ("/api/terminal/stop", {"hub_id": "h2", "session_id": OTHER_SESSION})
    ]


def test_share_on_a_session_of_someone_else_is_exit_1(resident, capsys):
    resident["replies"]["/api/terminal/persist"] = (
        400,
        {"code": "session_not_owned", "params": {"session_id": OTHER_SESSION}},
    )

    assert terminal.main_share("muon", "3f2a9", is_on=True) == 1
    assert "belongs to someone else" in capsys.readouterr().err


def test_a_session_the_hub_no_longer_finds_is_exit_2(resident):
    resident["replies"]["/api/terminal/stop"] = (
        400,
        {"code": "session_unknown", "params": {"session_id": SESSION}},
    )

    assert terminal.main_stop("muon", "3f2a1") == 2


def test_a_session_verb_with_several_matches_sends_nothing(resident):
    assert terminal.main_stop("muon", "3f") == 2
    assert terminal.main_persist("pion", "3f", is_on=True) == 2
    assert resident["requests"] == []
