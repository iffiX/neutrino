"""The streams this side opens: odd ids counting up, and the close each waits for.

The registry is driven with a recording sender: what is pinned is the open
frame's shape, a close whose params come back to the waiter, a close whose
code is the hub's refusal, a wait that runs out, and the socket ending under
an open stream.
"""

import json
import threading

import pytest

from neutrino_client.core.streams import ClientStream, ClientStreamRegistry
from neutrino_client.exceptions import GatewayRefusedDetail, GatewayUnreachable
from tests.conftest import discard


class Sender:
    """Keeps every text frame sent, or refuses when the socket is gone."""

    def __init__(self, error=None):
        self.frames = []
        self.error = error

    def __call__(self, text: str) -> None:
        if self.error is not None:
            raise self.error
        self.frames.append(json.loads(text))


@pytest.fixture
def registry():
    sender = Sender()
    return ClientStreamRegistry(send_text=sender, log=discard), sender


def test_ids_are_odd_and_count_upward(registry):
    subject, sender = registry

    first = subject.open("service", {"id": "rdp_s9"})
    second = subject.open("service", {"id": "ai"})
    third = subject.open("service", {})

    assert (first.stream_id, second.stream_id, third.stream_id) == (1, 3, 5)
    assert sender.frames[0] == {
        "type": "open",
        "stream": 1,
        "kind": "service",
        "id": "rdp_s9",
    }
    assert sender.frames[2] == {"type": "open", "stream": 5, "kind": "service"}


def test_a_close_with_params_resolves_the_wait(registry):
    subject, _sender = registry
    stream = subject.open("service", {"id": "rdp_s9"})

    subject.take_close({"type": "close", "stream": 1, "params": {"host": "h"}})

    assert stream.wait_close(timeout_s=1) == {"host": "h"}


def test_a_close_with_a_code_is_the_hubs_refusal(registry):
    subject, _sender = registry
    stream = subject.open("service", {"id": "rdp_s9"})

    subject.take_close(
        {"type": "close", "stream": 1, "code": "rdp_not_shared", "params": {"id": "x"}}
    )

    with pytest.raises(GatewayRefusedDetail) as refused:
        stream.wait_close(timeout_s=1)
    assert refused.value.code == "rdp_not_shared"
    assert refused.value.params == {"id": "x"}


def test_a_close_that_names_no_params_resolves_to_nothing(registry):
    subject, _sender = registry
    stream = subject.open("service", {})

    subject.take_close({"type": "close", "stream": 1})

    assert stream.wait_close(timeout_s=1) == {}


def test_a_wait_that_runs_out_is_unreachable(registry):
    subject, _sender = registry
    stream = subject.open("service", {"id": "ai"})

    with pytest.raises(GatewayUnreachable):
        stream.wait_close(timeout_s=0.05)


def test_the_close_reaches_a_waiter_on_another_thread(registry):
    subject, _sender = registry
    stream = subject.open("service", {"id": "ai"})
    outcome = {}

    def wait() -> None:
        outcome["params"] = stream.wait_close(timeout_s=5)

    waiter = threading.Thread(target=wait)
    waiter.start()
    subject.take_close({"type": "close", "stream": 1, "params": {"api_key": "k"}})
    waiter.join(timeout=5)

    assert outcome == {"params": {"api_key": "k"}}


def test_the_socket_ending_wakes_every_waiter_unreachable(registry):
    subject, _sender = registry
    first = subject.open("service", {})
    second = subject.open("service", {})

    subject.end_all()

    for stream in (first, second):
        with pytest.raises(GatewayUnreachable):
            stream.wait_close(timeout_s=1)
    with pytest.raises(GatewayUnreachable):
        subject.open("service", {})


def test_a_close_for_a_stream_nobody_opened_is_dropped(registry):
    subject, _sender = registry
    lines = []
    subject._log = lines.append

    subject.take_close({"type": "close", "stream": 7, "params": {}})

    assert lines and "7" in lines[0]


def test_a_close_that_names_no_integer_stream_is_typed(registry):
    subject, _sender = registry

    with pytest.raises(TypeError):
        subject.take_close({"type": "close", "stream": "one"})


def test_an_open_the_socket_cannot_carry_holds_no_stream():
    sender = Sender(error=GatewayUnreachable("gone"))
    subject = ClientStreamRegistry(send_text=sender, log=discard)

    with pytest.raises(GatewayUnreachable):
        subject.open("service", {})

    assert subject._streams == {}


def test_a_stream_reads_its_own_close_once():
    stream = ClientStream(stream_id=1, kind="service")

    stream.take_close(code="", params={"port": 21118})

    assert stream.wait_close(timeout_s=0) == {"port": 21118}
    assert stream.wait_close(timeout_s=0) == {"port": 21118}
