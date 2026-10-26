"""The resident's local channel to its transport, against a scripted transport.

What is pinned: every connection opens with the secret and its ``op``; a
command goes out with an ``id`` of its own and its answer comes back
without it, a transport refusal as ``{code, params}``; an unanswered
command gives up; the events and frames of one binding reach that binding's
listener alone, in order, a ``forward_end`` the forwards' listeners; a frame
goes out as ``{frame, binding}``; a stream opens on a connection of its own
naming its binding and its open record; a control connection that drops
fails every waiter, tells the listeners it was lost and, once it is open
again, that it is back; and the program is started with ``client --listen
<path>`` and the secret on the first line of its standard input, which
stays open until the stop.
"""

import os
import queue
import sys
import threading
import time

import pytest

from neutrino_client.core.transport import (
    ClientTransportChannel,
    ClientTransportProcess,
    make_secret,
)
from neutrino_client.exceptions import GatewayUnreachable
from tests.fake_transport import RECORD_DATA, FakeTransport, unix_connect

WAIT_S = 5


def wait_for(condition, timeout_s: float = WAIT_S) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def transport():
    fake = FakeTransport()
    yield fake
    fake.close()


@pytest.fixture
def channel(transport):
    made = ClientTransportChannel(
        connect=unix_connect,
        listen=transport.listen,
        secret=transport.secret,
        log=lambda line: None,
        restart_min_s=0.05,
    )
    made.start()
    assert made.wait_ready(WAIT_S)
    yield made
    made.stop()


def test_a_secret_is_64_hex_characters_made_afresh():
    one, other = make_secret(), make_secret()
    assert len(one) == 64 and int(one, 16) >= 0
    assert one != other


def test_the_control_connection_opens_with_the_secret(transport, channel):
    assert transport.wait_control()
    assert transport.refused_connections == 0


def test_a_wrong_secret_opens_nothing(transport):
    wrong = ClientTransportChannel(
        connect=unix_connect,
        listen=transport.listen,
        secret="cd" * 32,
        log=lambda line: None,
        start_timeout_s=0.2,
        restart_min_s=0.05,
    )
    wrong.start()
    assert wait_for(lambda: transport.refused_connections >= 1)
    assert not transport.wait_control(0.2)
    wrong.stop()


def test_a_command_is_answered_by_its_id_and_the_answer_comes_back_without_it(
    transport, channel
):
    transport.answers["forward_start"] = lambda line: {"listen": line["listen"]}
    answer = channel.command("forward_start", {"listen": "127.0.0.1:24001"})
    sent = transport.next_command("forward_start")
    assert sent["listen"] == "127.0.0.1:24001" and sent["id"]
    assert answer == {"listen": "127.0.0.1:24001"}


def test_a_refusal_comes_back_as_a_code(transport, channel):
    transport.answers["forward_start"] = lambda line: {
        "code": "port_taken",
        "params": {"port": 24001},
    }
    answer = channel.command("forward_start", {"listen": "127.0.0.1:24001"})
    assert answer == {"code": "port_taken", "params": {"port": 24001}}


def test_an_unanswered_command_gives_up(transport, channel):
    transport.answers["round"] = lambda line: None
    with pytest.raises(GatewayUnreachable):
        channel.command("round", {"binding": "c1"}, timeout_s=0.1)


def test_each_bindings_lines_reach_its_own_listener_in_order(transport, channel):
    heard = {"c1": queue.Queue(), "c2": queue.Queue()}
    channel.listen_binding("c1", heard["c1"].put)
    channel.listen_binding("c2", heard["c2"].put)
    transport.emit({"event": "session_open", "binding": "c1", "address": "a"})
    transport.frame("c1", {"type": "welcome", "id": "h1"})
    transport.frame("c2", {"type": "state", "hash": "x"})
    assert heard["c1"].get(timeout=WAIT_S)["event"] == "session_open"
    assert heard["c1"].get(timeout=WAIT_S)["frame"]["type"] == "welcome"
    assert heard["c2"].get(timeout=WAIT_S)["frame"]["type"] == "state"
    assert heard["c1"].empty()


def test_a_forgotten_binding_hears_nothing_more(transport, channel):
    heard = queue.Queue()
    channel.listen_binding("c1", heard.put)
    channel.forget_binding("c1", heard.put)
    transport.frame("c1", {"type": "state"})
    with pytest.raises(queue.Empty):
        heard.get(timeout=0.2)


def test_a_forward_end_reaches_the_forwards_listeners(transport, channel):
    ends = queue.Queue()
    channel.on_forward_end(ends.put)
    transport.emit(
        {
            "event": "forward_end",
            "listen": "127.0.0.1:24001",
            "protocol": "udp",
            "code": "agent_offline",
            "params": {},
        }
    )
    assert ends.get(timeout=WAIT_S)["code"] == "agent_offline"


def test_a_listener_may_wait_for_a_command_while_it_hears(transport, channel):
    answers = queue.Queue()

    def listener(line):
        answers.put(channel.command("round", {"binding": "c1"}))

    channel.listen_binding("c1", listener)
    transport.frame("c1", {"type": "state"})
    assert answers.get(timeout=WAIT_S) == {}


def test_a_frame_goes_out_naming_its_binding(transport, channel):
    channel.send_frame("c1", {"type": "hello", "id": "c1"})
    channel.send_frame("c1", {"type": "leave"}, is_last=True)
    assert transport.next_frame("hello") == {
        "frame": {"type": "hello", "id": "c1"},
        "binding": "c1",
    }
    assert transport.next_frame("leave")["is_last"] is True


def test_a_stream_opens_on_a_connection_of_its_own(transport, channel):
    stream = channel.open_stream(
        "c1", {"kind": "shell", "device_id": "d1", "cols": 80, "rows": 24}
    )
    peer = transport.next_open()
    assert peer.binding == "c1"
    assert peer.open == {"kind": "shell", "device_id": "d1", "cols": 80, "rows": 24}
    peer.accept()
    peer.send_record(RECORD_DATA, b"$ ")
    assert stream.read(WAIT_S) == b"$ "


def test_a_dropped_control_connection_fails_its_waiters_and_comes_back(
    transport, channel
):
    lost, ready = threading.Event(), threading.Event()
    channel.on_lost(lost.set)
    transport.answers["round"] = lambda line: None
    failures = queue.Queue()

    def ask():
        try:
            channel.command("round", {"binding": "c1"}, timeout_s=WAIT_S)
        except GatewayUnreachable as error:
            failures.put(error)

    asker = threading.Thread(target=ask)
    asker.start()
    transport.next_command("round")
    channel.on_ready(ready.set)
    transport.drop_control()
    assert lost.wait(WAIT_S)
    assert isinstance(failures.get(timeout=WAIT_S), GatewayUnreachable)
    assert ready.wait(WAIT_S)
    assert channel.is_ready()


def test_no_stream_opens_while_the_transport_is_down(transport):
    idle = ClientTransportChannel(
        connect=unix_connect, listen=transport.listen, secret=transport.secret
    )
    with pytest.raises(GatewayUnreachable):
        idle.open_stream("c1", {"kind": "connect", "id": "x"})
    with pytest.raises(GatewayUnreachable):
        idle.command("round", {"binding": "c1"})


FAKE_PROGRAM = """
import sys
with open(sys.argv[-1] + ".seen", "w") as out:
    out.write(" ".join(sys.argv[1:]) + "\\n" + sys.stdin.readline())
sys.stdin.read()
"""


def test_the_program_is_started_in_client_mode_with_the_secret_on_its_stdin(
    tmp_path,
):
    program = tmp_path / "fake_transport.py"
    program.write_text(FAKE_PROGRAM)
    launcher = tmp_path / "neutrino_transport"
    launcher.write_text(f"#!{sys.executable}\nexec(open({str(program)!r}).read())\n")
    launcher.chmod(0o755)
    listen = str(tmp_path / "run" / "neutrino" / "transport.sock")
    process = ClientTransportProcess(
        program=str(launcher), listen=listen, log_path=str(tmp_path / "t.log")
    )
    secret = process.start()
    seen = listen + ".seen"
    assert wait_for(lambda: os.path.exists(seen) and open(seen).read().count("\n") == 2)
    arguments, line = open(seen).read().splitlines()
    assert arguments == f"client --listen {listen}"
    assert line == secret
    assert process.is_running()
    process.stop()
    assert not process.is_running()
    assert oct(os.stat(os.path.dirname(listen)).st_mode & 0o777) == "0o700"


def test_a_program_that_cannot_start_is_an_os_error(tmp_path):
    process = ClientTransportProcess(
        program=str(tmp_path / "missing"),
        listen=str(tmp_path / "t.sock"),
        log_path=str(tmp_path / "t.log"),
    )
    with pytest.raises(OSError):
        process.start()
