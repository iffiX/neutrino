"""A hub's shell carried to a terminal: two pumps, one each way.

Pinned here: typed bytes reach the stream and the typing side's end closes
it; the hub's bytes reach the output, what already arrived in one piece, and
the hub's close ends the output pump; a write that fails closes the stream
from here; the window's keys go one send at a time and its close ends the
shell; the outcome names the exit code, the hub's refusal, or a session that
ended first; a resize is a record. An exec stream: pieces both ways, the
empty piece up sending ``eof`` except on a pseudo-terminal, each record down
one piece with its output's byte, and a connection that ends early closing
the stream.
"""

import io
import json
import socket
import struct
import threading
import time

from neutrino_client.constants import (
    CLIENT_TERMINAL_CLEAR_MAX_S,
    CLIENT_TERMINAL_CLEAR_QUIET_S,
)
from neutrino_client.core import protocol
from neutrino_client.core.streams import ClientStream
from neutrino_client.core.terminal import (
    ExecBridge,
    TerminalBridge,
    encode_piece,
    read_piece,
)
from tests.conftest import Clock

WAIT_S = 5


class Far:
    """The transport's end of one stream's connection, played by the test."""

    def __init__(self, end):
        self._end = end
        self._end.settimeout(WAIT_S)

    def record(self, record_type: int, payload: bytes = b"") -> None:
        self._end.sendall(struct.pack("!BI", record_type, len(payload)) + payload)

    def accept(self) -> None:
        self.record(protocol.RECORD_ACCEPT)

    def data(self, payload: bytes) -> None:
        self.record(protocol.RECORD_DATA, payload)

    def stderr(self, payload: bytes) -> None:
        self.record(protocol.RECORD_STDERR, payload)

    def close(self, code: str = "", params=None) -> None:
        self.record(
            protocol.RECORD_CLOSE,
            json.dumps({"code": code, "params": params or {}}).encode(),
        )

    def end(self) -> None:
        self._end.close()

    def received(self) -> list:
        """Every record this side sent, until its connection ended."""
        records = []
        while True:
            try:
                record = protocol.read_record(self._end.recv)
            except OSError:
                return records
            if record is None:
                return records
            records.append(record)


def opened(kind: str = "shell", is_fd_tagged: bool = False):
    """A stream on a socket pair, accepted by the far side."""
    near, far_end = socket.socketpair()
    far = Far(far_end)
    far.accept()
    stream = ClientStream(
        connection=near, kind=kind, is_fd_tagged=is_fd_tagged, accept_timeout_s=WAIT_S
    )
    assert stream.wait_accept(WAIT_S)
    return stream, far


def reader(chunks):
    pending = list(chunks)

    def read(size):
        return pending.pop(0) if pending else b""

    return read


def wait_for(condition, timeout_s: float = WAIT_S) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return condition()


CLOSE_HERE = (protocol.RECORD_CLOSE, b'{"code":"","params":{}}')


def test_typed_bytes_reach_the_hub_and_the_end_closes_the_stream():
    stream, far = opened()
    bridge = TerminalBridge(stream=stream)

    bridge.pump_in(reader([b"ls\n", b"exit\n"]))

    assert far.received() == [
        (protocol.RECORD_DATA, b"ls\n"),
        (protocol.RECORD_DATA, b"exit\n"),
        CLOSE_HERE,
    ]
    assert bridge.outcome() == {"exit_code": None}


def test_the_hubs_bytes_reach_the_output_until_the_hub_closes():
    stream, far = opened()
    bridge = TerminalBridge(stream=stream)
    shown = []
    far.data(b"$ ")
    far.data(b"bye")
    far.close(params={"exit_code": 3})
    assert wait_for(lambda: stream.is_done)

    bridge.pump_out(shown.append)

    assert b"".join(shown) == b"$ bye"
    assert bridge.outcome() == {"exit_code": 3}


def test_the_hub_closing_ends_a_waiting_output_pump():
    stream, far = opened()
    bridge = TerminalBridge(stream=stream)
    pump = threading.Thread(target=bridge.pump_out, args=(list().append,))

    pump.start()
    far.close()
    pump.join(timeout=WAIT_S)

    assert not pump.is_alive()


def test_the_typing_side_ending_ends_the_output_pump_too():
    stream, _far = opened()
    bridge = TerminalBridge(stream=stream)
    pump = threading.Thread(target=bridge.pump_out, args=(list().append,))

    pump.start()
    bridge.pump_in(reader([]))
    pump.join(timeout=WAIT_S)

    assert not pump.is_alive()


def test_an_output_that_fails_closes_the_stream_from_here():
    stream, far = opened()
    bridge = TerminalBridge(stream=stream)
    far.data(b"x")

    def broken(data):
        raise OSError("the terminal went away")

    bridge.pump_out(broken)

    assert far.received() == [CLOSE_HERE]
    assert bridge.outcome() == {"exit_code": None}


def test_a_refusal_is_the_outcome():
    near, far_end = socket.socketpair()
    far = Far(far_end)
    far.close("permission_denied", {"kind": "terminal"})
    stream = ClientStream(connection=near, kind="shell")
    bridge = TerminalBridge(stream=stream)

    bridge.pump_out(list().append)

    assert bridge.outcome() == {
        "code": "permission_denied",
        "params": {"kind": "terminal"},
    }


def test_a_session_that_ends_first_is_unreachable():
    stream, far = opened()
    bridge = TerminalBridge(stream=stream)
    far.end()

    bridge.pump_out(list().append)

    assert bridge.outcome()["code"] == "hub_unreachable"


def test_output_past_one_batch_is_written_in_more_than_one_piece():
    stream, far = opened()
    bridge = TerminalBridge(stream=stream)
    shown = []
    for _ in range(3):
        far.data(b"x" * 40000)
    far.close()
    assert wait_for(lambda: stream.is_done)

    bridge.pump_out(shown.append)

    assert sum(len(piece) for piece in shown) == 120000
    assert max(len(piece) for piece in shown) <= 80000


def test_the_windows_keys_reach_the_hub_and_its_close_ends_the_shell():
    stream, far = opened()
    bridge = TerminalBridge(stream=stream)

    assert bridge.send(b"ls\r") is True
    bridge.close()
    bridge.close()

    assert far.received() == [(protocol.RECORD_DATA, b"ls\r"), CLOSE_HERE]
    assert bridge.send(b"more") is False
    assert bridge.outcome() == {"exit_code": None}


def test_a_resize_is_a_record_on_the_stream():
    stream, far = opened()
    bridge = TerminalBridge(stream=stream)

    assert bridge.resize(132, 40) is True
    bridge.close()

    assert far.received()[0] == (protocol.RECORD_RESIZE, b'{"cols":132,"rows":40}')
    assert bridge.resize(80, 24) is False


def test_a_bridge_names_the_session_its_stream_is_attached_to():
    stream, _far = opened()

    assert TerminalBridge(stream=stream, session_id="kept-1").session_id == "kept-1"
    assert TerminalBridge(stream=stream).session_id == ""


def test_a_session_the_machine_no_longer_keeps_is_the_outcome():
    stream, far = opened()
    bridge = TerminalBridge(stream=stream, session_id="kept-1")
    far.close("session_unknown", {"session_id": "kept-1"})
    assert wait_for(lambda: stream.is_done)

    assert bridge.outcome() == {
        "code": "session_unknown",
        "params": {"session_id": "kept-1"},
    }


# --- Clear: Ctrl+C, then the output dropped until the stream is quiet ---


def clearing_pump(clock):
    """A bridge pumping into a list on a thread, with the clock injected."""
    stream, far = opened()
    bridge = TerminalBridge(stream=stream, clock=clock)
    written = []
    cleared = threading.Event()
    pump = threading.Thread(
        target=bridge.pump_out, args=(written.append, cleared.set), daemon=True
    )
    pump.start()
    return far, bridge, written, cleared, pump


def test_clear_sends_ctrl_c_and_draws_the_first_output_after_the_quiet():
    clock = Clock()
    far, bridge, written, cleared, pump = clearing_pump(clock)

    assert bridge.clear() is True
    assert bridge.is_clearing is True
    far.data(b"the flood")
    time.sleep(0.2)
    clock.now = 0.4
    far.data(b"its tail")
    assert not cleared.wait(0.6)
    clock.now = 0.4 + CLIENT_TERMINAL_CLEAR_QUIET_S
    assert cleared.wait(2)
    far.data(b"$ ")

    assert wait_for(lambda: written == [b"$ "])
    assert bridge.is_clearing is False
    far.close()
    pump.join(timeout=WAIT_S)
    # Ctrl+C at the press and nothing else: the box stays empty.
    assert far.received() == [(protocol.RECORD_DATA, b"\x03")]


def test_a_stream_that_never_goes_quiet_is_drawn_again_after_the_cap():
    clock = Clock()
    far, bridge, written, cleared, pump = clearing_pump(clock)

    bridge.clear()
    for step in range(5):
        clock.now = step * CLIENT_TERMINAL_CLEAR_MAX_S / 4
        far.data(b"flood")
        wait_for(lambda: False, 0.05)

    assert cleared.wait(2)
    far.data(b"after")
    assert wait_for(lambda: written and written[-1].endswith(b"after"))
    assert b"flood" not in b"".join(written)
    far.close()
    pump.join(timeout=WAIT_S)


def test_output_before_a_clear_is_written_as_ever():
    clock = Clock()
    far, bridge, written, _cleared, pump = clearing_pump(clock)

    far.data(b"before")

    assert wait_for(lambda: written == [b"before"])
    assert bridge.is_clearing is False
    far.close()
    pump.join(timeout=WAIT_S)


def test_keys_that_cannot_be_read_end_the_shell_with_the_reason():
    """The control connection's read gave up: the client ended the shell, and
    the outcome says so rather than reading as a shell that closed."""
    stream, far = opened()
    bridge = TerminalBridge(stream=stream)

    def read(size):
        raise TimeoutError("timed out")

    bridge.pump_in(read)

    assert far.received() == [CLOSE_HERE]
    assert bridge.outcome() == {
        "code": "terminal_input_failed",
        "params": {"detail": "timed out"},
    }


# --- an exec stream ---


def test_a_piece_reads_back_as_written_and_a_cut_one_as_the_end():
    pieces = io.BytesIO(encode_piece(b"abc") + encode_piece(b"") + b"\x00\x00")

    assert read_piece(pieces.read) == b"abc"
    assert read_piece(pieces.read) == b""
    assert read_piece(pieces.read) is None


def test_the_empty_piece_sends_eof_after_the_input_and_the_stream_stays_open():
    stream, far = opened("exec", is_fd_tagged=True)
    bridge = ExecBridge(stream=stream, is_tty=False)
    typed = io.BytesIO(encode_piece(b"select 1;") + encode_piece(b""))
    is_closed = []

    def read(size):
        data = typed.read(size)
        if not data and not is_closed:
            is_closed.append(True)
            far.close(params={"exit_code": 0})
            wait_for(lambda: stream.is_done)
        return data

    bridge.pump_in(read)

    assert far.received()[:2] == [
        (protocol.RECORD_DATA, b"select 1;"),
        (protocol.RECORD_EOF, b""),
    ]
    assert bridge.outcome() == {"exit_code": 0}


def test_a_pseudo_terminal_never_sends_eof():
    stream, far = opened("exec")
    bridge = ExecBridge(stream=stream, is_tty=True)

    bridge.pump_in(io.BytesIO(encode_piece(b"q") + encode_piece(b"")).read)

    assert all(kind != protocol.RECORD_EOF for kind, _payload in far.received())


def test_a_connection_that_ends_before_the_command_closes_it_from_here():
    stream, far = opened("exec", is_fd_tagged=True)
    bridge = ExecBridge(stream=stream, is_tty=False)

    bridge.pump_in(io.BytesIO(encode_piece(b"half")).read)

    assert far.received() == [(protocol.RECORD_DATA, b"half"), CLOSE_HERE]
    assert bridge.outcome() == {"exit_code": None}


def test_each_record_goes_down_as_one_piece_with_its_outputs_byte():
    stream, far = opened("exec", is_fd_tagged=True)
    bridge = ExecBridge(stream=stream, is_tty=False)
    far.data(b"out")
    far.data(b"")
    far.stderr(b"err")
    far.close(params={"exit_code": 7})
    shown = io.BytesIO()

    bridge.pump_out(shown.write)

    shown.seek(0)
    assert [read_piece(shown.read) for _ in range(3)] == [
        b"\x01out",
        b"\x02err",
        None,
    ]
    assert bridge.outcome() == {"exit_code": 7}
