"""What every forwarder shares: the token, a request's head, the relay.

What these pin: a token is the layout the standard names and works once,
only with its secret, only before its expiry and within the horizon; a
spent nonce is dropped once its token expired; a login cookie is the layout
the standard names and works with its key before its expiry; a request's head is read up
to its end and refused past the limit; a cookie's values are found across
headers; an ordinary request is passed on with ``Connection: close`` and
its body cut at its length; a chunked body is 411; a page that does not
answer is 502; and the server hands each connection to its callable. The
forwarder in front of one instance: it listens on loopback once the
hooks say the page is ready, trying again while it is not; a token is
spent once and what follows is the hooks' decision; a request the hooks
admit reaches the page, a WebSocket relayed both ways; a taken port is
reported until it frees; a forwarder follows the record fields the
hooks name; and a token's expiry is judged by the hub's time, so a machine
whose clock is hours off, or is set while the socket stays open, accepts a
fresh one.
"""

import base64
import hashlib
import hmac
import os
import socket
import socketserver
import threading
import time

import pytest

import neutrino_agent.modules.shared.hub_clock as hub_clock_module
from neutrino_agent.modules.shared.hub_clock import HubClock
from neutrino_agent.modules.shared.http_forward import (
    RELAY,
    ForwarderServer,
    InstanceForwarder,
    answered,
    closing_head,
    cookie_values,
    is_login_valid,
    mint_login,
    mint_token,
    parse_head,
    read_head,
    refused,
    relay,
    split_target,
    take_token,
)

SECRET = "instance-secret"  # scan: allow
NOW = 1_800_000_000


def test_a_token_is_the_layout_the_standard_names():
    token = mint_token(SECRET, expiry=NOW, nonce=b"\x01" * 16)
    raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))

    assert raw[:8] == NOW.to_bytes(8, "big")
    assert raw[8:24] == b"\x01" * 16
    assert raw[24:] == hmac.new(SECRET.encode(), raw[:24], hashlib.sha256).digest()


def test_a_token_works_once_with_its_secret_before_its_expiry():
    spent: dict = {}
    token = mint_token(SECRET, expiry=NOW + 60, nonce=b"n" * 16)

    assert take_token(token, secret=SECRET, now=NOW, spent=spent) is True
    assert take_token(token, secret=SECRET, now=NOW, spent=spent) is False
    assert not take_token(
        mint_token("other", expiry=NOW + 60, nonce=b"a" * 16),
        secret=SECRET,
        now=NOW,
        spent=spent,
    )
    assert not take_token(
        mint_token(SECRET, expiry=NOW, nonce=b"b" * 16),
        secret=SECRET,
        now=NOW,
        spent=spent,
    )
    assert not take_token(
        mint_token(SECRET, expiry=NOW + 3600, nonce=b"c" * 16),
        secret=SECRET,
        now=NOW,
        spent=spent,
    )
    assert not take_token("not a token", secret=SECRET, now=NOW, spent=spent)


def test_a_spent_nonce_is_dropped_once_its_token_expired():
    spent: dict = {}
    first = mint_token(SECRET, expiry=NOW + 60, nonce=b"n" * 16)
    second = mint_token(SECRET, expiry=NOW + 120, nonce=b"m" * 16)

    assert take_token(first, secret=SECRET, now=NOW, spent=spent)
    assert take_token(second, secret=SECRET, now=NOW + 61, spent=spent)

    assert list(spent) == [b"m" * 16]


def test_a_login_is_the_layout_the_standard_names_and_works_with_its_key():
    key = b"k" * 32
    login = mint_login(key, NOW + 60)
    raw = base64.urlsafe_b64decode(login + "=" * (-len(login) % 4))

    assert "=" not in login
    assert raw[:8] == (NOW + 60).to_bytes(8, "big")
    assert raw[8:] == hmac.new(key, raw[:8], hashlib.sha256).digest()
    assert is_login_valid(login, key, NOW) is True
    assert is_login_valid(login, key, NOW + 60) is False
    assert is_login_valid(mint_login(b"other", NOW + 60), key, NOW) is False
    assert is_login_valid(login[:-4], key, NOW) is False
    assert is_login_valid("junk", key, NOW) is False


def test_a_head_is_read_to_its_end_and_refused_past_the_limit():
    left, right = socket.socketpair()
    with left, right:
        left.sendall(b"GET /a?b=c HTTP/1.1\r\nHost: x\r\n\r\nbody")
        head, rest = read_head(right)
        assert head == b"GET /a?b=c HTTP/1.1\r\nHost: x\r\n\r\n"
        assert rest == b"body"
        assert parse_head(head) == ("GET", "/a?b=c", [("Host", "x")])

    left, right = socket.socketpair()
    with left, right:
        sender = threading.Thread(
            target=left.sendall, args=(b"GET / HTTP/1.1\r\n" + b"x" * 70000,)
        )
        sender.start()
        assert read_head(right) == (None, b"")
        right.close()
        sender.join(timeout=5)


def test_a_target_splits_in_either_form_and_a_cookie_is_found_in_every_header():
    assert split_target("/p?q=1") == ("/p", "q=1")
    assert split_target("http://h:1/p?q=1") == ("/p", "q=1")
    headers = [("Cookie", "a=1; b=2"), ("cookie", "b=3")]

    assert cookie_values(headers, "b") == ["2", "3"]
    assert cookie_values(headers, "c") == []


def test_closing_head_replaces_the_connection_header():
    head = b"GET / HTTP/1.1\r\nConnection: keep-alive\r\nKeep-Alive: 5\r\n\r\n"

    assert closing_head(head) == b"GET / HTTP/1.1\r\nConnection: close\r\n\r\n"


def _relay_once(request: bytes, connect) -> bytes:
    left, right = socket.socketpair()
    with left, right:
        left.sendall(request)
        head, rest = read_head(right)
        _method, _target, headers = parse_head(head)
        relay(right, head, rest, headers, connect)
        right.shutdown(socket.SHUT_WR)
        received = b""
        left.settimeout(5)
        while True:
            data = left.recv(65536)
            if not data:
                return received
            received += data


def test_an_ordinary_request_is_passed_on_closed_and_its_body_cut_at_its_length():
    page, ours = socket.socketpair()
    seen = []

    def serve():
        received = b""
        while b"\r\n\r\n" not in received or not received.endswith(b"hello"):
            received += page.recv(65536)
        seen.append(received)
        page.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
        page.close()

    server = threading.Thread(target=serve)
    server.start()
    answer = _relay_once(
        b"POST /x HTTP/1.1\r\nContent-Length: 5\r\nConnection: keep-alive\r\n\r\n"
        b"helloEXTRA",
        lambda: ours,
    )
    server.join(timeout=5)

    assert seen == [
        b"POST /x HTTP/1.1\r\nContent-Length: 5\r\nConnection: close\r\n\r\nhello"
    ]
    assert answer.endswith(b"ok")


def test_a_chunked_body_is_411_and_a_page_that_does_not_answer_is_502():
    def refused():
        raise ConnectionRefusedError()

    chunked = _relay_once(
        b"POST / HTTP/1.1\r\nTransfer-Encoding: chunked\r\n\r\n", refused
    )
    silent = _relay_once(b"GET / HTTP/1.1\r\n\r\n", refused)

    assert chunked.startswith(b"HTTP/1.1 411")
    assert silent.startswith(b"HTTP/1.1 502")


def test_the_server_hands_each_connection_to_its_callable():
    handled = []

    def handle(client):
        handled.append(client.recv(5))

    server = ForwarderServer(("127.0.0.1", 0), handle)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.05}
    )
    thread.start()
    try:
        with socket.create_connection(server.server_address[:2], timeout=5) as one:
            one.sendall(b"hello")
            one.settimeout(5)
            one.recv(1)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert handled == [b"hello"]


# --- the forwarder in front of one instance ---


class FakePage(socketserver.ThreadingTCPServer):
    """An echo of every request, and a WebSocket echo, on loopback."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(self):
        self.requests: list = []
        super().__init__(("127.0.0.1", 0), FakePageConnection)
        threading.Thread(
            target=self.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        ).start()

    @property
    def port(self) -> int:
        return self.server_address[1]

    def stop(self):
        self.shutdown()
        self.server_close()


class FakePageConnection(socketserver.BaseRequestHandler):
    def handle(self):
        received = b""
        while b"\r\n\r\n" not in received:
            chunk = self.request.recv(65536)
            if not chunk:
                return
            received += chunk
        head, _, body = received.partition(b"\r\n\r\n")
        self.server.requests.append(head)
        if b"Upgrade: websocket" in head:
            self.request.sendall(b"HTTP/1.1 101 Switching Protocols\r\n\r\n")
            while True:
                chunk = self.request.recv(65536)
                if not chunk:
                    return
                self.request.sendall(chunk)
        payload = head + b"\r\n\r\n" + body
        self.request.sendall(
            b"HTTP/1.1 200 OK\r\nContent-Length: "
            + str(len(payload)).encode()
            + b"\r\nConnection: close\r\n\r\n"
            + payload
        )


class DemoHooks:
    """Hooks whose page is ready after ``not_ready`` tries, then by code."""

    forwarder_fields = ("account", "port", "secret")
    secret_field = "secret"

    def __init__(self, page_port: int, *, not_ready: int = 0, codes=()):
        self.page_port = page_port
        self.not_ready = not_ready
        self.codes = list(codes)
        self.ready_calls = 0
        self.admitted: list = []

    def on_first_start(self, record) -> str:
        self.ready_calls += 1
        if self.not_ready > 0:
            self.not_ready -= 1
            raise OSError("the page is not up")
        return self.codes.pop(0) if self.codes else ""

    def admit(self, request, record):
        self.admitted.append(request.path)
        if request.token:
            if not request.take_token():
                return refused()
            return answered(
                302, headers=(("Location", request.path), ("Set-Cookie", "demo=ok"))
            )
        if "ok" in request.cookie_values("demo"):
            return RELAY
        return refused()

    def connect(self, record):
        return socket.create_connection(("127.0.0.1", self.page_port), timeout=5)


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def forwarder_for(hooks, port: int, log=None, **changes):
    record = {"account": "ann", "port": port, "secret": SECRET}
    return InstanceForwarder(
        name="demo",
        record=record,
        hooks=hooks,
        log=log if log is not None else (lambda line: None),
        ready_poll_s=0.01,
        retry_s=0.01,
        **changes,
    )


def wait_until(condition, timeout_s=5.0) -> None:
    deadline = time.monotonic() + timeout_s
    while not condition():
        assert time.monotonic() < deadline, "the forwarder did not get there"
        time.sleep(0.01)


def exchange(port: int, request: bytes) -> bytes:
    with socket.create_connection(("127.0.0.1", port), timeout=5) as client:
        client.sendall(request)
        received = b""
        while True:
            chunk = client.recv(65536)
            if not chunk:
                return received
            received += chunk


def good_token() -> str:
    return mint_token(SECRET, expiry=int(time.time()) + 60, nonce=os.urandom(16))


def test_the_forwarder_listens_on_loopback_once_the_page_answers():
    page = FakePage()
    lines = []
    hooks = DemoHooks(page.port, not_ready=2)
    forwarder = forwarder_for(hooks, free_port(), log=lines.append)
    try:
        forwarder.start()
        wait_until(lambda: forwarder.is_listening)

        assert forwarder.listen_address == ("127.0.0.1", forwarder.port)
        assert hooks.ready_calls == 3
        assert forwarder.failure == ("", {})
        assert lines == [f"demo: ann answers on port {forwarder.port}"]
    finally:
        forwarder.close()
        page.stop()


def test_a_token_is_traded_once_and_the_login_is_relayed():
    page = FakePage()
    hooks = DemoHooks(page.port)
    forwarder = forwarder_for(hooks, free_port())
    try:
        forwarder.start()
        wait_until(lambda: forwarder.is_listening)
        token = good_token()
        port = forwarder.port

        traded = exchange(
            port, f"GET /app?tkn={token} HTTP/1.1\r\nHost: x\r\n\r\n".encode()
        )
        again = exchange(
            port, f"GET /app?tkn={token} HTTP/1.1\r\nHost: x\r\n\r\n".encode()
        )
        forged = exchange(port, b"GET /app?tkn=bad HTTP/1.1\r\nHost: x\r\n\r\n")
        bare = exchange(port, b"GET /app HTTP/1.1\r\nHost: x\r\n\r\n")
        relayed = exchange(
            port,
            b"POST /api HTTP/1.1\r\nHost: x\r\nCookie: demo=ok\r\n"
            b"Content-Length: 2\r\n\r\nhi",
        )

        assert traded.startswith(b"HTTP/1.1 302 Found")
        assert b"Set-Cookie: demo=ok" in traded and b"Location: /app" in traded
        assert again.startswith(b"HTTP/1.1 401")
        assert forged.startswith(b"HTTP/1.1 401")
        assert bare.startswith(b"HTTP/1.1 401")
        assert relayed.startswith(b"HTTP/1.1 200")
        assert relayed.endswith(b"Connection: close\r\n\r\nhi")
        assert page.requests[0].startswith(b"POST /api HTTP/1.1")
        assert hooks.admitted == ["/app", "/app", "/app", "/app", "/api"]
    finally:
        forwarder.close()
        page.stop()


def test_a_websocket_is_relayed_both_ways():
    page = FakePage()
    forwarder = forwarder_for(DemoHooks(page.port), free_port())
    try:
        forwarder.start()
        wait_until(lambda: forwarder.is_listening)

        with socket.create_connection(("127.0.0.1", forwarder.port), timeout=5) as ws:
            ws.sendall(
                b"GET /ws HTTP/1.1\r\nHost: x\r\nCookie: demo=ok\r\n"
                b"Connection: Upgrade\r\nUpgrade: websocket\r\n\r\n"
            )
            received = b""
            while b"\r\n\r\n" not in received:
                received += ws.recv(65536)
            assert received.startswith(b"HTTP/1.1 101")
            ws.sendall(b"frame-1")
            assert ws.recv(65536) == b"frame-1"
    finally:
        forwarder.close()
        page.stop()


def test_a_page_that_is_not_ready_names_its_code_and_is_tried_again():
    page = FakePage()
    lines = []
    hooks = DemoHooks(page.port, codes=["demo_register_failed"])
    forwarder = forwarder_for(hooks, free_port(), log=lines.append)
    try:
        forwarder.start()
        wait_until(lambda: forwarder.is_listening)

        assert hooks.ready_calls == 2
        assert lines[0] == "demo: ann demo_register_failed"
    finally:
        forwarder.close()
        page.stop()


def test_a_taken_port_is_reported_and_taken_once_it_is_free():
    page = FakePage()
    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    port = holder.getsockname()[1]
    forwarder = forwarder_for(DemoHooks(page.port), port)
    try:
        forwarder.start()
        wait_until(lambda: forwarder.failure[0] == "demo_port_taken")

        assert forwarder.failure == (
            "demo_port_taken",
            {"account": "ann", "port": port},
        )
        assert forwarder.is_listening is False
        holder.close()
        wait_until(lambda: forwarder.is_listening)
        assert forwarder.failure == ("", {})
    finally:
        holder.close()
        forwarder.close()
        page.stop()


def test_a_closed_forwarder_stops_waiting():
    hooks = DemoHooks(1, not_ready=10**6)
    forwarder = forwarder_for(hooks, free_port())
    forwarder.start()
    wait_until(lambda: hooks.ready_calls > 0)

    forwarder.close()

    forwarder._thread.join(timeout=5)
    assert not forwarder._thread.is_alive()


def test_a_forwarder_matches_a_record_by_the_hooks_fields():
    forwarder = forwarder_for(DemoHooks(1), 8443)
    record = {"account": "ann", "port": 8443, "secret": SECRET, "database": "a"}

    assert forwarder.matches(record) is True
    assert forwarder.matches(dict(record, database="b")) is True
    assert forwarder.matches(dict(record, secret="other")) is False
    assert forwarder.matches(dict(record, port=1)) is False


class SkewedMachine:
    """This machine's clock, some seconds off the hub's, which can be set."""

    def __init__(self, skew_s: float):
        self.skew_s = skew_s

    def time(self) -> float:
        return time.time() + self.skew_s


def hub_minted_token() -> str:
    """A token as the hub mints it, by the hub's own clock."""
    return mint_token(SECRET, expiry=int(time.time()) + 60, nonce=os.urandom(16))


@pytest.mark.parametrize("skew_s", [-13 * 3600, 13 * 3600])
def test_a_fresh_token_works_on_a_machine_whose_clock_is_hours_off(monkeypatch, skew_s):
    """The forwarder judges the expiry by the hub's time, which the last
    welcome gave; by the machine's own clock the token reads expired or too
    far ahead."""
    machine = SkewedMachine(skew_s)
    clock = HubClock(clock=machine.time)
    clock.take(time.time())
    monkeypatch.setattr(hub_clock_module, "_HUB_CLOCK", clock)
    forwarder = forwarder_for(DemoHooks(1), free_port())
    on_own_clock = forwarder_for(DemoHooks(1), free_port(), clock=machine.time)

    assert forwarder.take_token(hub_minted_token()) is True
    assert on_own_clock.take_token(hub_minted_token()) is False


def test_a_token_works_after_the_machines_clock_is_set_while_the_socket_stays_open(
    monkeypatch,
):
    machine = SkewedMachine(-13 * 3600)
    clock = HubClock(clock=machine.time)
    clock.take(time.time())
    monkeypatch.setattr(hub_clock_module, "_HUB_CLOCK", clock)
    forwarder = forwarder_for(DemoHooks(1), free_port())
    assert forwarder.take_token(hub_minted_token()) is True

    machine.skew_s = 0.0

    assert forwarder.take_token(hub_minted_token()) is True
    assert abs(clock.offset) < 1.0
