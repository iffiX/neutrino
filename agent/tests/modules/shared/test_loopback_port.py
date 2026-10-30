"""The ports on loopback the agent takes for its listeners and instances.

What these pin: a port another program listens on is not free and one
nobody holds is; a port with a listener accepts a connection and one
without does not; a pick is the first free port from the base up, past the
ports taken; a base outside the port range is refused; and a pick that
finds nothing free fails.
"""

import socket

import pytest

from neutrino_agent.modules.shared.loopback_port import (
    is_listening,
    is_port_free,
    pick_port,
)


def test_a_port_another_program_listens_on_is_not_free():
    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    port = holder.getsockname()[1]
    try:
        assert is_port_free(port) is False
    finally:
        holder.close()

    assert is_port_free(port) is True


def test_a_port_with_a_listener_accepts_a_connection_and_one_without_does_not():
    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    port = holder.getsockname()[1]
    try:
        assert is_listening(port) is True
    finally:
        holder.close()

    assert is_listening(port) is False


def test_a_pick_is_the_first_free_port_from_the_base_past_the_taken():
    held = {3001, 3003}

    port = pick_port(3001, taken=[3002], is_free=lambda port: port not in held)

    assert port == 3004


def test_a_base_outside_the_range_is_refused():
    with pytest.raises(ValueError):
        pick_port(0)


def test_a_pick_with_nothing_free_fails():
    with pytest.raises(OSError):
        pick_port(65530, is_free=lambda port: False)
