"""The AI gateway forward: the transport's listener, asked for by state.

What these pin: a state whose ``ai_tools`` says ``is_forwarded`` asks the
transport for ``forward_start`` on ``127.0.0.1:8317`` with the ``connect``
open of the ``ai`` entry, and one that does not gives the listener back
with ``forward_stop``; the hub's own machine asks for none; a refusal is one
line in the log, said once, and asked for again by ``ensure``; no transport
asks for nothing and says so; and a transport that ended forgets the
listener so the next one is asked.
"""

import pytest

from neutrino_agent.exceptions import GatewayUnreachable
from neutrino_agent.streams.ai_forward import (
    AiGatewayForward,
    is_forward_wanted,
    listen_port,
)

ON = {"ai_tools": {"is_enabled": True, "is_forwarded": True}}
OFF = {"ai_tools": {"is_enabled": False, "is_forwarded": False}}


class Transport:
    """The transport's command line, answered from a table."""

    def __init__(self, answers=None):
        self.commands: list = []
        self.answers = dict(answers or {})
        self.is_gone = False

    def __call__(self, name, **fields):
        if self.is_gone:
            raise GatewayUnreachable("no transport")
        self.commands.append((name, fields))
        answer = self.answers.get(name, {})
        return answer(fields) if callable(answer) else dict(answer)


def forward(transport, lines=None, port=8317):
    return AiGatewayForward(
        command=transport, log=(lines.append if lines is not None else print), port=port
    )


@pytest.mark.parametrize(
    "document, is_wanted",
    [
        (ON, True),
        (OFF, False),
        ({"ai_tools": {"is_enabled": True}}, False),
        ({"ai_tools": {"is_forwarded": "yes"}}, False),
        ({}, False),
    ],
)
def test_the_forward_is_wanted_while_the_section_says_is_forwarded(document, is_wanted):
    assert is_forward_wanted(document) is is_wanted


def test_a_state_asking_for_it_starts_the_listener_and_one_not_asking_stops_it():
    transport = Transport({"forward_start": lambda f: {"listen": f["listen"]}})
    made = forward(transport)

    made.take(ON)
    assert made.local_port == 8317
    made.take(OFF)

    assert transport.commands == [
        (
            "forward_start",
            {
                "listen": "127.0.0.1:8317",
                "protocol": "tcp",
                "open": {"kind": "connect", "id": "ai"},
            },
        ),
        ("forward_stop", {"listen": "127.0.0.1:8317", "protocol": "tcp"}),
    ]
    assert made.local_port == 0


def test_the_address_the_transport_bound_is_the_one_held():
    transport = Transport({"forward_start": {"listen": "127.0.0.1:40123"}})
    made = forward(transport, port=0)

    made.take(ON)

    assert transport.commands[0][1]["listen"] == "127.0.0.1:0"
    assert made.local_port == 40123


def test_the_same_state_again_asks_nothing_more():
    transport = Transport()
    made = forward(transport)

    made.take(ON)
    made.take(ON)
    made.ensure()

    assert [name for name, _ in transport.commands] == ["forward_start"]


def test_the_hubs_own_machine_asks_for_none():
    transport = Transport()

    forward(transport).take({"ai_tools": {"is_enabled": True, "is_forwarded": False}})

    assert transport.commands == []


def test_a_refusal_is_said_once_and_asked_for_again_by_ensure():
    lines: list = []
    transport = Transport({"forward_start": {"code": "port_taken", "params": {}}})
    made = forward(transport, lines)

    made.take(ON)
    made.ensure()
    transport.answers["forward_start"] = {"listen": "127.0.0.1:8317"}
    made.ensure()

    assert len([line for line in lines if "cannot listen" in line]) == 1
    assert [name for name, _ in transport.commands] == ["forward_start"] * 3
    assert made.local_port == 8317


def test_no_transport_asks_nothing_and_says_so():
    lines: list = []
    transport = Transport()
    transport.is_gone = True
    made = forward(transport, lines)

    made.take(ON)

    assert made.local_port == 0
    assert any("not asked for" in line for line in lines)


def test_a_transport_that_ended_is_forgotten_and_the_next_one_asked():
    transport = Transport()
    made = forward(transport)
    made.take(ON)

    made.reset()
    made.ensure()

    assert [name for name, _ in transport.commands] == ["forward_start"] * 2


def test_a_stop_with_nothing_held_asks_nothing():
    transport = Transport()

    forward(transport).stop()

    assert transport.commands == []


@pytest.mark.parametrize(
    "listen, port", [("127.0.0.1:8317", 8317), ("", 0), ("127.0.0.1", 0)]
)
def test_a_listeners_port_is_read_off_its_address(listen, port):
    assert listen_port(listen) == port
