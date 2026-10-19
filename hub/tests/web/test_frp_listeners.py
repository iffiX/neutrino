"""The frp vendors' loopback listeners on a running loop.

A listener opens while its way in is on and closes when it is turned off,
without the loop stopping; one whose port another socket holds is recorded
as taken; a process with no serving loop opens nothing.
"""

import asyncio
import socket
import threading
import urllib.request

import pytest
import uvicorn

from neutrino_hub.web import frp_listeners
from neutrino_hub.web.frp_listeners import FrpLoopbackListeners


async def app(scope, receive, send):
    """Answers every HTTP request with ``ok``."""
    if scope["type"] != "http":
        return
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def answers(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2) as reply:
            return reply.read() == b"ok"
    except OSError:
        return False


@pytest.fixture
def served(monkeypatch):
    """A loop running on a thread of its own, the vendors on free ports."""
    ports = {"sakurafrp": free_port(), "openfrp": free_port()}
    monkeypatch.setattr(frp_listeners, "FRP_LOOPBACK_PORTS", ports)
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    listeners = FrpLoopbackListeners()
    listeners.attach(
        loop,
        lambda port: uvicorn.Config(
            app, host="127.0.0.1", port=port, log_level="warning"
        ),
    )
    yield listeners, ports
    asyncio.run_coroutine_threadsafe(listeners.close(), loop).result(timeout=10)
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5)
    loop.close()


def test_a_listener_opens_while_its_way_in_is_on_and_closes_when_off(served):
    listeners, ports = served

    listeners.follow({"sakurafrp": True, "openfrp": False})
    is_open = answers(ports["sakurafrp"])
    is_other_open = answers(ports["openfrp"])
    listeners.follow({"sakurafrp": False, "openfrp": False})

    assert is_open is True
    assert is_other_open is False
    assert answers(ports["sakurafrp"]) is False
    assert listeners.is_taken("sakurafrp") is False


def test_both_listeners_serve_at_once_and_a_second_follow_keeps_them(served):
    listeners, ports = served

    listeners.follow({"sakurafrp": True, "openfrp": True})
    listeners.follow({"sakurafrp": True, "openfrp": True})

    assert answers(ports["sakurafrp"]) and answers(ports["openfrp"])


def test_a_port_another_socket_holds_is_taken_until_the_way_in_is_off(served):
    listeners, ports = served
    holder = socket.socket()
    holder.bind(("127.0.0.1", ports["openfrp"]))
    holder.listen()
    try:
        listeners.follow({"sakurafrp": False, "openfrp": True})
        is_taken = listeners.is_taken("openfrp")
        listeners.follow({"sakurafrp": False, "openfrp": False})
    finally:
        holder.close()

    assert is_taken is True
    assert listeners.is_taken("openfrp") is False


def test_a_process_serving_no_channel_opens_nothing(monkeypatch):
    port = free_port()
    monkeypatch.setattr(frp_listeners, "FRP_LOOPBACK_PORTS", {"sakurafrp": port})

    FrpLoopbackListeners().follow({"sakurafrp": True})

    assert answers(port) is False
