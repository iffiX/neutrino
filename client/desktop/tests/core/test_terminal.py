"""A hub's shell carried to a terminal: two pumps, one each way.

Pinned here: typed bytes reach the stream and the typing side's end closes
it; the hub's bytes reach the output, what already arrived in one piece, and
the hub's close ends the output pump; a write that fails closes the stream
from here; the window's keys go one send at a time and its close ends the
shell; the outcome names the exit code, the hub's refusal, or a socket that
ended first.
"""

import threading

from neutrino_client.constants import (
    CLIENT_TERMINAL_CLEAR_MAX_S,
    CLIENT_TERMINAL_CLEAR_QUIET_S,
)
from neutrino_client.core.streams import ClientStreamRegistry
from neutrino_client.core.terminal import TerminalBridge
from neutrino_client.core.protocol import decode_binary
from tests.conftest import Clock, discard


class Wire:
    """Records every frame the stream layer sends."""

    def __init__(self):
        self.text = []
        self.binary = []

    def send_text(self, text: str) -> None:
        import json

        self.text.append(json.loads(text))

    def send_bytes(self, data: bytes) -> None:
        self.binary.append(decode_binary(data))


def shell():
    wire = Wire()
    registry = ClientStreamRegistry(
        send_text=wire.send_text, send_bytes=wire.send_bytes, log=discard
    )
    stream = registry.open("shell", {"device_id": "d1"}, has_bytes=True)
    return registry, stream, wire


def reader(chunks):
    pending = list(chunks)

    def read(size):
        return pending.pop(0) if pending else b""

    return read


def test_typed_bytes_reach_the_hub_and_the_end_closes_the_stream():
    registry, stream, wire = shell()
    registry.take_credit({"type": "credit", "stream": 1, "bytes": 100})
    bridge = TerminalBridge(stream=stream)

    bridge.pump_in(reader([b"ls\n", b"exit\n"]))

    assert wire.binary == [(1, b"ls\n"), (1, b"exit\n")]
    assert wire.text[-1] == {"type": "close", "stream": 1, "code": "", "params": {}}
    assert bridge.outcome() == {"exit_code": None}


def test_the_hubs_bytes_reach_the_output_until_the_hub_closes():
    registry, stream, _wire = shell()
    bridge = TerminalBridge(stream=stream)
    shown = []
    registry.take_bytes(1, b"$ ")
    registry.take_bytes(1, b"bye")
    registry.take_close({"type": "close", "stream": 1, "params": {"exit_code": 3}})

    bridge.pump_out(shown.append)

    assert shown == [b"$ bye"]
    assert bridge.outcome() == {"exit_code": 3}


def test_the_hub_closing_ends_a_waiting_output_pump():
    registry, stream, _wire = shell()
    bridge = TerminalBridge(stream=stream)
    pump = threading.Thread(target=bridge.pump_out, args=(list().append,))

    pump.start()
    registry.take_close({"type": "close", "stream": 1, "params": {}})
    pump.join(timeout=5)

    assert not pump.is_alive()


def test_the_typing_side_ending_ends_the_output_pump_too():
    _registry, stream, _wire = shell()
    bridge = TerminalBridge(stream=stream)
    pump = threading.Thread(target=bridge.pump_out, args=(list().append,))

    pump.start()
    bridge.pump_in(reader([]))
    pump.join(timeout=5)

    assert not pump.is_alive()


def test_an_output_that_fails_closes_the_stream_from_here():
    registry, stream, wire = shell()
    bridge = TerminalBridge(stream=stream)
    registry.take_bytes(1, b"x")

    def broken(data):
        raise OSError("the terminal went away")

    bridge.pump_out(broken)

    assert wire.text[-1]["type"] == "close"
    assert bridge.outcome() == {"exit_code": None}


def test_a_refusal_is_the_outcome():
    registry, stream, _wire = shell()
    bridge = TerminalBridge(stream=stream)
    registry.take_close(
        {
            "type": "close",
            "stream": 1,
            "code": "permission_denied",
            "params": {"kind": "terminal"},
        }
    )

    bridge.pump_out(list().append)

    assert bridge.outcome() == {
        "code": "permission_denied",
        "params": {"kind": "terminal"},
    }


def test_a_socket_that_ends_first_is_unreachable():
    registry, stream, _wire = shell()
    bridge = TerminalBridge(stream=stream)
    registry.end_all()

    bridge.pump_out(list().append)

    assert bridge.outcome()["code"] == "hub_unreachable"


def test_reading_grants_the_hub_more_as_the_output_is_written():
    registry, stream, wire = shell()
    bridge = TerminalBridge(stream=stream)
    half = 512 * 1024
    registry.take_bytes(1, b"a" * half)
    registry.take_close({"type": "close", "stream": 1, "params": {}})

    bridge.pump_out(list().append)

    grants = [frame for frame in wire.text if frame["type"] == "credit"]
    assert len(grants) == 1


def test_output_past_one_batch_is_written_in_more_than_one_piece():
    registry, stream, _wire = shell()
    bridge = TerminalBridge(stream=stream)
    shown = []
    for _ in range(3):
        registry.take_bytes(1, b"x" * 40000)
    registry.take_close({"type": "close", "stream": 1, "params": {}})

    bridge.pump_out(shown.append)

    assert [len(piece) for piece in shown] == [80000, 40000]


def test_the_windows_keys_reach_the_hub_and_its_close_ends_the_shell():
    registry, stream, wire = shell()
    registry.take_credit({"type": "credit", "stream": 1, "bytes": 100})
    bridge = TerminalBridge(stream=stream)

    assert bridge.send(b"ls\r") is True
    bridge.close()
    bridge.close()

    assert wire.binary == [(1, b"ls\r")]
    assert [frame["type"] for frame in wire.text].count("close") == 1
    assert bridge.send(b"more") is False
    assert bridge.outcome() == {"exit_code": None}


def test_a_bridge_names_the_session_its_stream_is_attached_to():
    _registry, stream, _wire = shell()

    assert TerminalBridge(stream=stream, session_id="kept-1").session_id == "kept-1"
    assert TerminalBridge(stream=stream).session_id == ""


def test_a_session_the_machine_no_longer_keeps_is_the_outcome():
    registry, stream, _wire = shell()
    bridge = TerminalBridge(stream=stream, session_id="kept-1")
    registry.take_close(
        {
            "type": "close",
            "stream": 1,
            "code": "session_unknown",
            "params": {"session_id": "kept-1"},
        }
    )

    assert bridge.outcome() == {
        "code": "session_unknown",
        "params": {"session_id": "kept-1"},
    }


# --- Clear: Ctrl+C, then the output dropped until the stream is quiet ---


def clearing_pump(clock):
    """A bridge pumping into a list on a thread, with the clock injected."""
    registry, stream, wire = shell()
    registry.take_credit({"type": "credit", "stream": 1, "bytes": 100})
    bridge = TerminalBridge(stream=stream, clock=clock)
    written = []
    cleared = threading.Event()
    pump = threading.Thread(
        target=bridge.pump_out, args=(written.append, cleared.set), daemon=True
    )
    pump.start()
    return registry, bridge, wire, written, cleared, pump


def wait_for(condition, timeout_s: float = 5.0) -> bool:
    import time

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return condition()


def test_clear_sends_ctrl_c_and_draws_the_first_output_after_the_quiet():
    clock = Clock()
    registry, bridge, wire, written, cleared, pump = clearing_pump(clock)

    assert bridge.clear() is True
    assert bridge.is_clearing is True
    registry.take_bytes(1, b"the flood")
    clock.now = 0.4
    registry.take_bytes(1, b"its tail")
    assert not cleared.wait(0.6)
    clock.now = 0.4 + CLIENT_TERMINAL_CLEAR_QUIET_S
    assert cleared.wait(2)
    registry.take_bytes(1, b"$ ")

    assert wait_for(lambda: written == [b"$ "])
    # Ctrl+C at the press and nothing else: the box stays empty.
    assert wire.binary == [(1, b"\x03")]
    assert bridge.is_clearing is False
    registry.take_close({"type": "close", "stream": 1, "params": {}})
    pump.join(timeout=5)


def test_a_stream_that_never_goes_quiet_is_drawn_again_after_the_cap():
    clock = Clock()
    registry, bridge, _wire, written, cleared, pump = clearing_pump(clock)

    bridge.clear()
    for step in range(5):
        clock.now = step * CLIENT_TERMINAL_CLEAR_MAX_S / 4
        registry.take_bytes(1, b"flood")
        wait_for(lambda: False, 0.05)

    assert cleared.wait(2)
    registry.take_bytes(1, b"after")
    assert wait_for(lambda: written and written[-1].endswith(b"after"))
    assert b"flood" not in b"".join(written)
    registry.take_close({"type": "close", "stream": 1, "params": {}})
    pump.join(timeout=5)


def test_output_before_a_clear_is_written_as_ever():
    clock = Clock()
    registry, bridge, _wire, written, _cleared, pump = clearing_pump(clock)

    registry.take_bytes(1, b"before")

    assert wait_for(lambda: written == [b"before"])
    assert bridge.is_clearing is False
    registry.take_close({"type": "close", "stream": 1, "params": {}})
    pump.join(timeout=5)
