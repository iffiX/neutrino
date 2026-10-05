"""The agent port's limits, counted over the whole port.

Every peer through the relay comes from loopback, so these pin that nothing
is counted per address: the cap on open handshakes closes the oldest, the
cap on admitted sockets refuses the next, and the failed admissions pause
join for the rest of their window.
"""

from neutrino_hub.modules.channel.constants import (
    CHANNEL_ADMISSION_FAILURES_MAX,
    CHANNEL_ADMISSION_WINDOW_S,
    CHANNEL_SOCKETS_MAX,
    CHANNEL_UNADMITTED_MAX,
)
from neutrino_hub.modules.channel.port_guard import ChannelPortGuard
from tests.conftest import FakeClock


class Connection:
    """One accepted connection, as the guard is handed it."""

    def __init__(self):
        self.is_closed = False

    def close(self) -> None:
        self.is_closed = True

    def has_ended(self) -> bool:
        return self.is_closed


def accept(guard: ChannelPortGuard, key) -> Connection:
    connection = Connection()
    guard.accepted(key, connection.close, connection.has_ended)
    return connection


def test_the_limits_are_the_ones_the_standard_names():
    assert CHANNEL_UNADMITTED_MAX == 128
    assert CHANNEL_SOCKETS_MAX == 512
    assert CHANNEL_ADMISSION_FAILURES_MAX == 30
    assert CHANNEL_ADMISSION_WINDOW_S == 60


def test_the_cap_on_open_handshakes_closes_the_oldest_whatever_its_address():
    guard = ChannelPortGuard(unadmitted_max=3)
    first = accept(guard, ("127.0.0.1", 1))
    second = accept(guard, ("127.0.0.1", 2))
    third = accept(guard, ("192.168.1.9", 3))

    fourth = accept(guard, ("127.0.0.1", 4))

    assert first.is_closed
    assert not (second.is_closed or third.is_closed or fourth.is_closed)
    assert guard.unadmitted_count == 3


def test_a_connection_that_ended_frees_its_place():
    guard = ChannelPortGuard(unadmitted_max=2)
    first = accept(guard, ("127.0.0.1", 1))
    second = accept(guard, ("127.0.0.1", 2))
    first.close()

    accept(guard, ("127.0.0.1", 3))

    assert not second.is_closed


def test_a_connection_past_its_admission_time_is_closed_and_not_counted():
    guard = ChannelPortGuard(failures_max=1)
    connection = accept(guard, ("127.0.0.1", 1))

    assert guard.expire(("127.0.0.1", 1), connection.close) is True
    assert connection.is_closed
    assert guard.unadmitted_count == 0
    assert guard.pause_remaining_s() == 0


def test_the_cap_closes_the_oldest_that_has_not_finished_tls():
    guard = ChannelPortGuard(unadmitted_max=3)
    first = accept(guard, ("127.0.0.1", 1))
    second = accept(guard, ("127.0.0.1", 2))
    third = accept(guard, ("127.0.0.1", 3))
    guard.handshaken(("127.0.0.1", 1))

    fourth = accept(guard, ("127.0.0.1", 4))

    assert second.is_closed
    assert not (first.is_closed or third.is_closed or fourth.is_closed)


def test_the_cap_closes_the_oldest_of_all_when_every_one_finished_tls():
    guard = ChannelPortGuard(unadmitted_max=2)
    first = accept(guard, ("127.0.0.1", 1))
    second = accept(guard, ("127.0.0.1", 2))
    guard.handshaken(("127.0.0.1", 1))
    guard.handshaken(("127.0.0.1", 2))

    third = accept(guard, ("127.0.0.1", 3))

    assert first.is_closed
    assert not (second.is_closed or third.is_closed)


def test_an_admitted_connection_is_not_expired():
    guard = ChannelPortGuard(failures_max=1)
    connection = accept(guard, ("127.0.0.1", 1))
    guard.admit(("127.0.0.1", 1))

    assert guard.expire(("127.0.0.1", 1), connection.close) is False
    assert not connection.is_closed
    assert guard.pause_remaining_s() == 0


def test_an_expiry_leaves_a_later_connection_from_the_same_port_alone():
    guard = ChannelPortGuard()
    earlier = accept(guard, ("127.0.0.1", 1))
    earlier.close()
    later = accept(guard, ("127.0.0.1", 1))

    assert guard.expire(("127.0.0.1", 1), earlier.close) is False
    assert not later.is_closed


def test_the_cap_on_admitted_sockets_refuses_the_next():
    guard = ChannelPortGuard(sockets_max=2)
    first = guard.admit(("127.0.0.1", 1))
    second = guard.admit(("127.0.0.1", 2))

    assert first is not None and second is not None
    assert guard.admit(("127.0.0.1", 3)) is None
    guard.release(first)
    assert guard.admit(("127.0.0.1", 3)) is not None


def test_two_sockets_from_one_address_and_port_count_twice():
    guard = ChannelPortGuard(sockets_max=2)
    guard.admit(("127.0.0.1", 1))
    guard.admit(("127.0.0.1", 1))

    assert guard.admitted_count == 2
    assert guard.admit(("127.0.0.1", 1)) is None


def test_failures_at_the_limit_pause_join_until_the_oldest_leaves_the_window():
    clock = FakeClock()
    guard = ChannelPortGuard(failures_max=3, window_s=60, clock=clock)
    guard.record_failure()
    clock.now += 10
    guard.record_failure()
    assert guard.pause_remaining_s() == 0

    guard.record_failure()

    assert guard.pause_remaining_s() == 50
    clock.now += 49
    assert guard.pause_remaining_s() == 1
    clock.now += 1
    assert guard.pause_remaining_s() == 0


# --- what the port logs when it closes a socket on its own ---


def close_lines(caplog) -> list:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == "neutrino_hub.modules.channel.port_guard"
    ]


def test_a_socket_closed_to_make_room_is_one_line_naming_it_and_the_count(caplog):
    guard = ChannelPortGuard(unadmitted_max=2, clock=FakeClock())
    accept(guard, ("2001:db8::7", 1))
    accept(guard, ("192.168.1.9", 2))

    with caplog.at_level("WARNING"):
        accept(guard, ("127.0.0.1", 3))

    assert close_lines(caplog) == [
        "agent port full: closed 2001:db8::7 to make room, 2 sockets held"
    ]


def test_closes_to_make_room_write_one_line_a_minute_and_count_the_rest(caplog):
    clock = FakeClock()
    guard = ChannelPortGuard(unadmitted_max=1, clock=clock)
    accept(guard, ("10.0.0.1", 1))

    with caplog.at_level("WARNING"):
        for port in range(2, 102):
            accept(guard, ("10.0.0.1", port))
            clock.now += 0.1
        clock.now += 60
        accept(guard, ("10.0.0.2", 200))

    assert close_lines(caplog) == [
        "agent port full: closed 10.0.0.1 to make room, 1 sockets held",
        "agent port full: closed 10.0.0.1 to make room, 1 sockets held; "
        "99 more closed since the last such line",
    ]


def test_each_timeout_writes_its_own_line_under_its_own_limit(caplog):
    clock = FakeClock()
    guard = ChannelPortGuard(clock=clock)

    with caplog.at_level("WARNING"):
        for port in range(1, 4):
            accept(guard, ("10.0.0.1", port))
            guard.timed_out(("10.0.0.1", port), "first_byte", 3.0)
        accept(guard, ("10.0.0.2", 9))
        guard.timed_out(("10.0.0.2", 9), "handshake", 10.0)

    assert close_lines(caplog) == [
        "agent port: closed 10.0.0.1, no byte within 3 s",
        "agent port: closed 10.0.0.2, TLS handshake not done within 10 s",
    ]
    assert guard.unadmitted_count == 0


def test_the_normal_path_writes_no_line(caplog):
    guard = ChannelPortGuard(clock=FakeClock())

    with caplog.at_level("DEBUG"):
        accept(guard, ("10.0.0.1", 1))
        guard.handshaken(("10.0.0.1", 1))
        admission = guard.admit(("10.0.0.1", 1))
        guard.release(admission)
        accept(guard, ("10.0.0.1", 2))
        guard.closed(("10.0.0.1", 2))

    assert close_lines(caplog) == []
