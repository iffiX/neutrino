"""``nclient terminal``: the six verbs against a scripted client.

Pinned: a machine named by name or id, ``--hub`` telling two hubs' machines
of one name apart; ``open`` and ``attach`` with 0 closed, 1 refused, 2 not
offered, the account named in the open, the keys carried up, the output
down and a resize as a request; a session id matched by prefix with one,
none and several matches; ``exec`` returning the remote code, 125 for a
refusal and 126 for no machine, stdout and stderr apart, stdin ended with
the empty piece, and raw mode only with ``--tty`` on a terminal; ``list``'s
columns; ``set`` with the flags given and refused for a session another
client owns; ``stop``. A refusal naming the machine names it by its name.
"""

import io
import subprocess
import sys
import time

from neutrino_client.cli import terminal, wording
from neutrino_client.core.terminal import encode_piece, read_piece
from tests.cli.conftest import OTHER_SESSION, SESSION


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


def upgrades(running) -> list:
    return [
        (path, body) for method, path, body in running.requests if method == "UPGRADE"
    ]


def wait_for(condition) -> None:
    deadline = time.monotonic() + 5
    while not condition():
        assert time.monotonic() < deadline
        time.sleep(0.01)


def pieces(*frames) -> list:
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


def test_a_machine_by_name_is_opened_as_the_account_and_carried(running):
    term = FakeTerm(keys=[b"ls\n"])
    running.output = [b"$ ", b"bye"]

    status = terminal.main_open("build", account="ci", platform=FakePlatform(term))

    assert status == terminal.EXIT_CLOSED
    path, body = upgrades(running)[0]
    assert path == "/api/terminal/attach"
    assert (body["hub_id"], body["device_id"], body["session_id"], body["account"]) == (
        "h2",
        "d7",
        "",
        "ci",
    )
    assert body["cols"] > 0 and body["rows"] > 0
    assert upgrades(running)[1] == ("/api/terminal/output", {"terminal_id": "t1"})
    assert term.written == [b"$ ", b"bye"]
    wait_for(lambda: running.kept["/api/terminal/attach"].sent == [b"ls\n"])


def test_the_first_account_is_the_clients_default(running):
    assert terminal.main_open("d1", platform=FakePlatform(FakeTerm())) == 0
    assert upgrades(running)[0][1]["account"] == ""


def test_one_name_on_two_hubs_asks_for_the_hub(running, capsys):
    assert terminal.main_open("lab-gpu", platform=FakePlatform(FakeTerm())) == 2

    assert capsys.readouterr().err.strip() == wording.word_code(
        "ambiguous_hub", {"hubs": "home, office"}
    )
    assert (
        terminal.main_open("lab-gpu", hub="home", platform=FakePlatform(FakeTerm()))
        == 0
    )


def test_a_machine_nobody_offers_a_shell_on_is_exit_2(running, capsys):
    assert terminal.main_open("pion", platform=FakePlatform(FakeTerm())) == 2

    assert upgrades(running) == []
    assert (
        capsys.readouterr().err.strip().startswith("no machine named pion; there are:")
    )


def test_a_session_prefix_is_attached_to_by_its_whole_id(running):
    status = terminal.main_attach(
        "lab-gpu", "3f2a1", hub="home", platform=FakePlatform(FakeTerm())
    )

    assert status == 0
    assert upgrades(running)[0][1]["session_id"] == SESSION


def test_a_prefix_no_session_has_is_exit_2_in_words(running, capsys):
    status = terminal.main_attach("d1", "ffff", platform=FakePlatform(FakeTerm()))

    assert status == terminal.EXIT_NO_MACHINE
    assert capsys.readouterr().err.strip() == wording.word_code("session_unknown")
    assert upgrades(running) == []


def test_a_prefix_several_sessions_have_prints_them_and_is_exit_2(running, capsys):
    status = terminal.main_attach("d1", "3f2a", platform=FakePlatform(FakeTerm()))

    err = capsys.readouterr().err
    assert status == terminal.EXIT_NO_MACHINE
    assert SESSION in err and OTHER_SESSION in err
    assert upgrades(running) == []


def test_a_refused_open_is_exit_1_in_words(running, capsys):
    running.upgrades["/api/terminal/attach"] = (
        403,
        {"code": "permission_denied", "params": {"kind": "terminal"}},
    )

    assert terminal.main_open("d1", platform=FakePlatform(FakeTerm())) == 1
    assert capsys.readouterr().err.strip() == (
        "the hub gives this client no terminal permission"
    )


def test_an_offline_machine_is_named_by_its_name(running, capsys):
    running.upgrades["/api/terminal/attach"] = (
        409,
        {"code": "agent_offline", "params": {"device": "d1"}},
    )

    assert terminal.main_open("d1", platform=FakePlatform(FakeTerm())) == 1
    assert capsys.readouterr().err.strip() == "lab-gpu is offline"


def test_a_shell_the_hub_refused_after_the_open_is_exit_1(running, capsys):
    running.result = {"code": "account_not_enabled", "params": {"account": "root"}}

    assert terminal.main_open("d1", platform=FakePlatform(FakeTerm())) == 1
    assert capsys.readouterr().err.strip() == wording.word_code(
        "account_not_enabled", {"account": "root"}
    )


def test_a_shell_that_exits_with_a_code_is_still_exit_0(running):
    running.result = {"exit_code": 5}

    assert terminal.main_open("d1", platform=FakePlatform(FakeTerm())) == 0


def test_a_resize_goes_up_as_a_request(running):
    term = FakeTerm()
    terminal.main_open("d1", platform=FakePlatform(term))

    term.resize(100, 30)

    assert running.posts("/api/terminal/resize")[-1] == {
        "terminal_id": "t1",
        "cols": 100,
        "rows": 30,
    }


def test_no_running_client_is_exit_1(running, capsys):
    running.is_running = False

    assert terminal.main_open("d1", platform=FakePlatform(FakeTerm())) == 1
    assert capsys.readouterr().err.strip() == wording.word_code("client_not_running")


# --- exec ---


def run_exec(running, *, stdin=b"", command=("ls",), machine="build", **options):
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


def test_exec_returns_the_remote_code_with_stdout_and_stderr_apart(running):
    running.output = pieces(b"\x01rows\n", b"\x02warning\n", b"\x01done\n")
    running.result = {"exit_code": 3}

    status, out, err = run_exec(running, command=["psql", "app"], account="ci")

    assert status == 3
    assert (out, err) == (b"rows\ndone\n", b"warning\n")
    path, body = upgrades(running)[0]
    assert path == "/api/terminal/exec"
    assert (body["hub_id"], body["device_id"], body["argv"], body["is_tty"]) == (
        "h2",
        "d7",
        ["psql", "app"],
        False,
    )
    assert body["account"] == "ci"
    assert "session_id" not in body


def test_execs_stdin_goes_up_and_ends_with_the_empty_piece(running):
    running.output = pieces(b"\x01ok")

    run_exec(running, stdin=b"select 1;\n")

    kept = running.kept["/api/terminal/exec"]
    wait_for(lambda: sent_pieces(kept)[-1:] == [b""])
    assert b"".join(sent_pieces(kept)) == b"select 1;\n"


def test_exec_without_tty_never_enters_raw_mode_on_a_terminal(running):
    running.output = pieces(b"\x01up 3 days")
    running.result = {"exit_code": 0}

    status, out, _err = run_exec(running, stdin=TerminalInput(b""))

    assert (status, out) == (0, b"up 3 days")


def test_exec_with_tty_on_a_terminal_goes_through_raw_mode(running):
    running.output = pieces(b"\x01screen")
    running.result = {"exit_code": 0}
    term = FakeTerm(keys=[b"q"])

    status, _out, _err = run_exec(
        running, stdin=TerminalInput(b""), is_tty=True, platform=FakePlatform(term)
    )

    assert status == 0
    assert term.written == [b"screen"]
    assert upgrades(running)[0][1]["is_tty"] is True


def test_exec_on_a_machine_no_hub_offers_is_126(running):
    status, _out, _err = run_exec(running, machine="pion")

    assert status == terminal.EXIT_EXEC_NO_MACHINE
    assert upgrades(running) == []


def test_execs_refused_open_is_125_in_words(running, capsys):
    running.upgrades["/api/terminal/exec"] = (
        403,
        {"code": "terminal_account_missing", "params": {}},
    )

    status, _out, _err = run_exec(running)

    assert status == terminal.EXIT_EXEC_REFUSED
    assert capsys.readouterr().err.strip() == wording.word_code(
        "terminal_account_missing"
    )


def test_a_command_the_machine_cannot_run_is_125_in_words(running, capsys):
    running.output = []
    running.result = {"code": "shell_program_unusable", "params": {"path": "nope"}}

    status, _out, _err = run_exec(running, command=["nope"])

    assert status == terminal.EXIT_EXEC_REFUSED
    assert "cannot run nope" in capsys.readouterr().err


def test_exec_with_no_command_is_125(running, capsys):
    status, _out, _err = run_exec(running, command=[])

    assert status == terminal.EXIT_EXEC_REFUSED
    assert "--" in capsys.readouterr().err
    assert upgrades(running) == []


def test_exec_with_no_running_client_is_125(running):
    running.is_running = False

    status, _out, _err = run_exec(running)

    assert status == terminal.EXIT_EXEC_REFUSED


def test_an_output_nobody_reads_any_more_ends_exec_at_125(running):
    running.output = pieces(b"\x01lines")

    status, _out, _err = run_exec(running, stdout=BrokenOutput())

    assert status == terminal.EXIT_EXEC_REFUSED
    assert running.kept["/api/terminal/exec"].is_closed


# --- list ---


def test_list_prints_the_machines_sessions_with_how_long_they_are_open(running, capsys):
    assert terminal.main_list("d1") == 0

    lines = [line.split() for line in capsys.readouterr().out.splitlines()]
    assert lines[0] == [
        "SESSION",
        "ACCOUNT",
        "OPEN",
        "PERSISTENT",
        "SHARED",
        "ATTACHED",
    ]
    assert lines[1] == [SESSION[:8], "iffi", "1h", "yes", "no", "2"]
    assert lines[2] == [OTHER_SESSION[:8], "lab", "1h", "no", "yes", "1"]


def test_list_of_a_machine_with_no_session_says_so(running, capsys):
    assert terminal.main_list("build") == 0
    assert capsys.readouterr().out.strip() == "build keeps no session"


def test_list_speaks_chinese(running, chinese, capsys):
    assert terminal.main_list("d1") == 0
    assert capsys.readouterr().out.splitlines()[0].split() == [
        "会话",
        "账户",
        "开了多久",
        "持久",
        "共享",
        "在看",
    ]


def test_list_of_a_machine_nobody_offers_is_exit_2(running):
    assert terminal.main_list("pion") == 2


# --- set and stop ---


def test_set_sends_the_flags_given_for_the_whole_id(running):
    assert terminal.main_set("d1", "3f2a1", is_persistent=True) == 0
    assert terminal.main_set("d1", "3f2a1", is_persistent=False, is_shared=True) == 0

    assert running.posts("/api/terminal/persist") == [
        {"is_persistent": True, "hub_id": "h1", "session_id": SESSION},
        {
            "is_persistent": False,
            "is_shared": True,
            "hub_id": "h1",
            "session_id": SESSION,
        },
    ]


def test_set_with_no_flag_sends_nothing(running, capsys):
    assert terminal.main_set("d1", "3f2a1") == 2

    assert running.posts("/api/terminal/persist") == []
    assert "--persist" in capsys.readouterr().err


def test_set_on_a_session_another_client_owns_is_exit_1(running, capsys):
    running.answers["/api/terminal/persist"] = lambda body: (
        400,
        {"code": "session_not_owned", "params": {"session_id": OTHER_SESSION}},
    )

    assert terminal.main_set("d1", "3f2a9", is_shared=False) == 1
    assert capsys.readouterr().err.strip() == wording.word_code("session_not_owned")


def test_stop_names_the_session(running):
    assert terminal.main_stop("d1", "3f2a9") == 0

    assert running.posts("/api/terminal/stop") == [
        {"hub_id": "h1", "session_id": OTHER_SESSION}
    ]


def test_a_session_the_hub_no_longer_finds_is_exit_2(running):
    running.answers["/api/terminal/stop"] = lambda body: (
        400,
        {"code": "session_unknown", "params": {"session_id": SESSION}},
    )

    assert terminal.main_stop("d1", "3f2a1") == 2


def test_a_session_verb_with_several_matches_sends_nothing(running):
    assert terminal.main_stop("d1", "3f") == 2
    assert terminal.main_set("pion", "3f", is_shared=True) == 2
    assert running.posts("/api/terminal/stop") == []


def test_a_process_exits_cleanly_while_a_thread_waits_on_an_open_stdin():
    """The input thread reads stdin through its descriptor, not the buffer."""
    script = (
        "import sys, threading, time\n"
        "from neutrino_client.cli.terminal import _reader\n"
        "read = _reader(sys.stdin.buffer)\n"
        "threading.Thread(target=read, daemon=True).start()\n"
        "time.sleep(0.2)\n"
        "sys.exit(7)\n"
    )
    held_open = subprocess.Popen(
        [sys.executable, "-c", script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    _out, err = held_open.communicate(input=None, timeout=20)
    assert held_open.returncode == 7, err.decode(errors="replace")
    assert b"Fatal Python error" not in err
