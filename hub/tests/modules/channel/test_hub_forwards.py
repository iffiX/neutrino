"""The hub's forwards on its loopback, as the Python asks its transport for them.

What these pin: the first address asked for a machine's port starts one
forward with ``forward_start`` naming the binding, ``127.0.0.1:0`` and a
TCP ``connect`` to the port, and later asks reuse it; a stop sends
``forward_stop`` for the address bound; a refusal of the transport reaches
the caller; and a new control connection forgets every forward.
"""

import asyncio
import threading

import pytest

from neutrino_hub.exceptions import StreamRefusedError
from neutrino_hub.modules.channel.hub_forwards import HubForwardTable


class FakeChannel:
    """A local channel whose commands a loop in a thread answers."""

    def __init__(self):
        self.commands = []
        self.refusal = None
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self._thread.start()
        self._next = 40000

    async def send_command(self, command, **fields):
        self.commands.append((command, fields))
        if self.refusal is not None:
            raise StreamRefusedError(self.refusal, {})
        if command == "forward_start":
            self._next += 1
            return {"listen": f"127.0.0.1:{self._next}"}
        return {}

    def close(self):
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(5)
        self.loop.close()


@pytest.fixture
def channel():
    held = FakeChannel()
    yield held
    held.close()


def test_the_first_ask_starts_a_forward_and_later_asks_reuse_it(channel):
    table = HubForwardTable(channel=channel)
    assert table.address("dev", 11434) == "127.0.0.1:40001"
    assert table.address("dev", 11434) == "127.0.0.1:40001"
    assert table.is_held("dev", 11434) is True
    assert channel.commands == [
        (
            "forward_start",
            {
                "binding_id": "dev",
                "listen": "127.0.0.1:0",
                "protocol": "tcp",
                "open": {"kind": "connect", "port": 11434, "protocol": "tcp"},
            },
        )
    ]


def test_a_stop_sends_forward_stop_for_the_address_bound(channel):
    table = HubForwardTable(channel=channel)
    table.address("dev", 11434)
    assert table.stop("dev", 11434) is True
    assert channel.commands[-1] == (
        "forward_stop",
        {"listen": "127.0.0.1:40001", "protocol": "tcp"},
    )
    assert table.stop("dev", 11434) is False
    assert table.is_held("dev", 11434) is False


def test_a_refusal_of_the_transport_reaches_the_caller(channel):
    channel.refusal = "body_invalid"
    table = HubForwardTable(channel=channel)
    with pytest.raises(StreamRefusedError):
        table.address("dev", 11434)
    assert table.is_held("dev", 11434) is False


def test_a_new_control_connection_forgets_every_forward(channel):
    table = HubForwardTable(channel=channel)
    table.address("dev", 11434)
    table.forget_all()
    assert table.is_held("dev", 11434) is False
    assert table.address("dev", 11434) == "127.0.0.1:40002"
