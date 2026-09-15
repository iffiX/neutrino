"""The log stream: an operation's lines up, the module's state in the close.

What these pin: each line goes up as one binary frame, the close carries
the module's state and, on a failure, the code beside it, and a stream
the hub closed or a socket that went away takes no more lines and raises
nothing into the operation.
"""

from neutrino_agent.exceptions import GatewayUnreachable
from neutrino_agent.streams.log import LogStream
from tests.streams.fake_channel import FakeChannel


def test_lines_go_up_one_frame_each_and_the_close_carries_the_state():
    channel = FakeChannel(stream_id=1)
    log = LogStream(channel)

    log.send("samba: installing")
    log.send("Setting up samba")
    log.close("installed")

    assert channel.sent == [b"samba: installing\n", b"Setting up samba\n"]
    assert channel.closed == {"code": "", "params": {"state": "installed"}}


def test_a_failed_operation_closes_with_its_code_beside_the_state():
    channel = FakeChannel(stream_id=1)

    LogStream(channel).close("absent", "install_failed", {"detail": "dpkg"})

    assert channel.closed == {
        "code": "install_failed",
        "params": {"detail": "dpkg", "state": "absent"},
    }


def test_a_stream_the_hub_closed_takes_no_more_lines_and_raises_nothing():
    channel = FakeChannel(stream_id=1)
    log = LogStream(channel)
    log.send("one")
    channel.close_from_hub()

    log.send("two")
    log.send("three")
    log.close("installed")

    assert channel.sent == [b"one\n"]
    # A close from the hub was already the stream's end.
    assert channel.closed is None


def test_a_socket_that_went_away_ends_the_log_quietly():
    class GoneChannel(FakeChannel):
        def send_line(self, text):
            raise GatewayUnreachable("gone")

        def close(self, code="", params=None):
            raise GatewayUnreachable("gone")

    log = LogStream(GoneChannel(stream_id=1))

    log.send("one")
    log.close("installed")
