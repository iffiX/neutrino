"""One stream's channel over a socket pair, read back as the transport reads it.

What these pin: a line goes up as one ``data`` record, a line of 100 KB as
one record of its start with ``…`` at its end, and a close whose params do
not fit one record as ``result_too_large`` with the record's limit, the
connection closed after it.
"""

import socket
import threading

from neutrino_agent.streams.channel import StreamChannel
from neutrino_agent.transport.connection import LocalSocketConnection
from neutrino_agent.transport.records import RecordReader, decode_item

RECORD = 64 * 1024


def channel_pair():
    """A channel on one end of a socket pair, and the far end a test reads."""
    near, far = socket.socketpair()
    far.settimeout(5.0)
    return StreamChannel(LocalSocketConnection("", sock=near), "s2"), far


def records_of(far) -> list:
    """Every record's payload and item until the close or the end."""
    reader = RecordReader(far)
    read = []
    while True:
        record = reader.read()
        if record is None:
            return read
        read.append((record[1], decode_item(*record)))
        if read[-1][1][0] == "close":
            return read


def sent(far, send) -> list:
    """What ``send`` writes, read on the far end while it writes."""
    writer = threading.Thread(target=send, daemon=True)
    writer.start()
    read = records_of(far)
    writer.join(5.0)
    assert not writer.is_alive()
    return read


def test_a_line_goes_up_as_one_data_record_with_its_newline():
    channel, far = channel_pair()

    def send():
        channel.send_line("one")
        channel.close("", {"exit_code": 0})

    read = sent(far, send)

    assert [item for _, item in read] == [
        ("data", b"one\n"),
        ("close", "", {"exit_code": 0}),
    ]


def test_a_100_kb_line_goes_up_as_one_record_cut_with_the_mark():
    channel, far = channel_pair()
    line = "2026-11-07 codeg " + "x" * (100 * 1024)

    def send():
        channel.send_line(line)
        channel.close("", {"exit_code": 0})

    read = sent(far, send)

    payload, item = read[0]
    assert item[0] == "data"
    assert len(payload) == RECORD
    assert payload.startswith(b"2026-11-07 codeg xxx")
    assert payload.endswith("…\n".encode("utf-8"))
    assert read[1][1] == ("close", "", {"exit_code": 0})


def test_a_close_too_large_for_a_record_is_sent_as_result_too_large():
    channel, far = channel_pair()
    result = {"lines": ["\x1b[32mINFO\x1b[0m " + "x" * 300] * 300}

    read = sent(far, lambda: channel.close("", {"exit_code": 0, "result": result}))

    assert read[-1][1] == ("close", "result_too_large", {"limit": RECORD})
    assert channel.is_closed
    assert far.recv(1) == b""
