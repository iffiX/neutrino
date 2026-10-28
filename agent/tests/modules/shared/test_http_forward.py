"""What every forwarder shares: the token, a request's head, the relay.

What these pin: a token is the layout the standard names and works once,
only with its secret, only before its expiry and within the horizon; a
spent nonce is dropped once its token expired; a login cookie is the layout
the standard names and works with its key before its expiry; a request's head is read up
to its end and refused past the limit; a cookie's values are found across
headers; a ``Host`` outside loopback and the instance's local name is 421,
an ``Origin`` other than the ``Host``'s 403; the page's answer is passed on
by its length, its chunks, or the end of its connection; and the server
hands each connection to its callable. The forwarder in front of one
instance: it listens on loopback once the hooks say the page is ready,
trying again while it is not; a token is spent once and what follows is
the hooks' decision; requests on one browser connection reach the page over
one kept connection, their heads unchanged and each judged again; a chunked
body is 411 and a page that does not answer 502; both sockets send at once;
a WebSocket is relayed both ways; a taken port is reported until it frees;
a forwarder follows the record fields the hooks name; a page's own fixed
login cookie is renamed to the entry's name in every ``Set-Cookie`` it
returns and back to its own in every request, a WebSocket's included, the
browser's own cookie of that name dropped; and a token's expiry
is judged by the hub's time, so a machine whose clock is hours off, or is
set while the socket stays open, accepts a fresh one.
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

import neutrino_agent.modules.shared.http_forward as http_forward_module
import neutrino_agent.modules.shared.hub_clock as hub_clock_module
from neutrino_agent.modules.shared.hub_clock import HubClock
from neutrino_agent.modules.shared.http_forward import (
    RELAY,
    ConnectionReader,
    ForwarderServer,
    InstanceForwarder,
    answered,
    check_origin,
    cookie_values,
    is_login_valid,
    mint_login,
    mint_token,
    parse_head,
    read_head,
    refused,
    relay_answer,
    renamed_request_cookies,
    renamed_set_cookies,
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


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1:24100",
        "[::1]:24100",
        "localhost:24100",
        "LocalHost",
        "app.m.localhost:7",
    ],
)
def test_a_host_of_loopback_or_the_local_name_passes(host):
    assert check_origin([("Host", host)], "app.m.localhost") == 0


@pytest.mark.parametrize(
    "headers",
    [
        [("Host", "evil.example:24100")],
        [("Host", "app.m.localhost:24100")],
        [("Host", "127.0.0.2:24100")],
        [],
    ],
)
def test_any_other_host_is_421(headers):
    assert check_origin(headers) == 421


@pytest.mark.parametrize(
    "origin, status",
    [
        ("http://127.0.0.1:24100", 0),
        ("HTTP://127.0.0.1:24100/", 0),
        ("http://127.0.0.1:24101", 403),
        ("https://127.0.0.1:24100", 403),
        ("http://evil.example", 403),
        ("null", 403),
    ],
)
def test_an_origin_is_its_own_hosts_or_403(origin, status):
    headers = [("Host", "127.0.0.1:24100"), ("Origin", origin)]

    assert check_origin(headers) == status


def _answered(page_answer: bytes, method: str = "GET", *, is_closed: bool = False):
    """What one answer of the page passes on, and what it says of the connection."""
    page, ours = socket.socketpair()
    browser, theirs = socket.socketpair()
    with page, ours, browser, theirs:
        page.sendall(page_answer)
        if is_closed:
            page.shutdown(socket.SHUT_WR)
        outcome = relay_answer(ConnectionReader(ours), theirs, method)
        theirs.shutdown(socket.SHUT_WR)
        browser.settimeout(5)
        received = b""
        while True:
            chunk = browser.recv(65536)
            if not chunk:
                return outcome, received
            received += chunk


def test_an_answer_is_passed_on_by_its_length_and_keeps_the_connection():
    outcome, received = _answered(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nokNEXT")

    assert outcome is True
    assert received == b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok"


def test_a_chunked_answer_is_passed_on_through_its_trailer():
    body = b"3\r\nabc\r\n0\r\nX-T: 1\r\n\r\n"
    outcome, received = _answered(
        b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n" + body + b"NEXT"
    )

    assert outcome is True
    assert received.endswith(body)


def test_an_answer_with_no_length_ends_with_its_connection():
    outcome, received = _answered(
        b"HTTP/1.1 200 OK\r\n\r\nuntil the end", is_closed=True
    )

    assert outcome is False
    assert received.endswith(b"until the end")


def test_an_answer_that_says_close_ends_the_connection_and_head_has_no_body():
    closing, _ = _answered(
        b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
    )
    head, received = _answered(
        b"HTTP/1.1 200 OK\r\nContent-Length: 9\r\n\r\n", method="HEAD"
    )
    interim, both = _answered(
        b"HTTP/1.1 100 Continue\r\n\r\n" b"HTTP/1.1 204 No Content\r\n\r\n"
    )

    assert closing is False
    assert head is True and received.endswith(b"\r\n\r\n")
    assert interim is True and both.count(b"HTTP/1.1") == 2


def test_a_page_that_ends_before_its_answer_reads_none():
    outcome, received = _answered(b"", is_closed=True)

    assert outcome is None
    assert received == b""


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
    """An echo of every request, many on one connection, and a WebSocket echo, on loopback."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(self):
        self.requests: list = []
        self.connections = 0
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
        self.server.connections += 1
        received = b""
        while True:
            while b"\r\n\r\n" not in received:
                chunk = self.request.recv(65536)
                if not chunk:
                    return
                received += chunk
            head, _, received = received.partition(b"\r\n\r\n")
            self.server.requests.append(head)
            if b"Upgrade: websocket" in head:
                self.request.sendall(b"HTTP/1.1 101 Switching Protocols\r\n\r\n")
                while True:
                    chunk = self.request.recv(65536)
                    if not chunk:
                        return
                    self.request.sendall(chunk)
            length = 0
            for line in head.split(b"\r\n")[1:]:
                name, _, value = line.partition(b":")
                if name.strip().lower() == b"content-length":
                    length = int(value)
            while len(received) < length:
                received += self.request.recv(65536)
            body, received = received[:length], received[length:]
            payload = head + b"\r\n\r\n" + body
            self.request.sendall(
                b"HTTP/1.1 200 OK\r\nContent-Length: "
                + str(len(payload)).encode()
                + b"\r\n\r\n"
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
        self.upstreams: list = []

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
        upstream = socket.create_connection(("127.0.0.1", self.page_port), timeout=5)
        self.upstreams.append(upstream)
        return upstream


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def forwarder_for(hooks, port: int, log=None, local_name="", **changes):
    record = {
        "account": "ann",
        "port": port,
        "secret": SECRET,
        "local_name": local_name,
    }
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
    """One request on a connection of its own, read until the forwarder ends it."""
    with socket.create_connection(("127.0.0.1", port), timeout=5) as client:
        client.sendall(request)
        received = b""
        while True:
            chunk = client.recv(65536)
            if not chunk:
                return received
            received += chunk


def read_answer(client: socket.socket) -> bytes:
    """One whole answer read off a kept connection, by its length."""
    reader = ConnectionReader(client)
    head = reader.read_head()
    length = 0
    for line in head.split(b"\r\n")[1:]:
        name, _, value = line.partition(b":")
        if name.strip().lower() == b"content-length":
            length = int(value)
    body = reader.take_buffer()
    while len(body) < length:
        body += client.recv(65536)
    return head + body


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
        host = f"Host: 127.0.0.1:{port}\r\nConnection: close"

        traded = exchange(
            port, f"GET /app?tkn={token} HTTP/1.1\r\n{host}\r\n\r\n".encode()
        )
        again = exchange(
            port, f"GET /app?tkn={token} HTTP/1.1\r\n{host}\r\n\r\n".encode()
        )
        forged = exchange(port, f"GET /app?tkn=bad HTTP/1.1\r\n{host}\r\n\r\n".encode())
        bare = exchange(port, f"GET /app HTTP/1.1\r\n{host}\r\n\r\n".encode())
        relayed = exchange(
            port,
            f"POST /api HTTP/1.1\r\n{host}\r\nCookie: demo=ok\r\n"
            "Content-Length: 2\r\n\r\nhi".encode(),
        )

        assert traded.startswith(b"HTTP/1.1 302 Found")
        assert b"Set-Cookie: demo=ok" in traded and b"Location: /app" in traded
        assert again.startswith(b"HTTP/1.1 401")
        assert forged.startswith(b"HTTP/1.1 401")
        assert bare.startswith(b"HTTP/1.1 401")
        assert relayed.startswith(b"HTTP/1.1 200")
        assert relayed.endswith(
            b"Connection: close\r\nCookie: demo=ok\r\nContent-Length: 2\r\n\r\nhi"
        )
        assert page.requests[0].startswith(b"POST /api HTTP/1.1")
        assert hooks.admitted == ["/app", "/app", "/app", "/app", "/api"]
    finally:
        forwarder.close()
        page.stop()


def test_requests_on_one_connection_reach_the_page_over_one_kept_connection():
    page = FakePage()
    hooks = DemoHooks(page.port)
    forwarder = forwarder_for(hooks, free_port(), local_name="app.m.localhost")
    try:
        forwarder.start()
        wait_until(lambda: forwarder.is_listening)
        port = forwarder.port
        with socket.create_connection(("127.0.0.1", port), timeout=5) as client:
            first_head = (
                f"GET /a HTTP/1.1\r\nHost: app.m.localhost:{port}\r\n"
                "Cookie: demo=ok\r\nConnection: keep-alive\r\n\r\n"
            ).encode()
            client.sendall(first_head)
            first = read_answer(client)
            client.sendall(
                f"POST /b HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
                "Cookie: demo=ok\r\nContent-Length: 2\r\n\r\nhi".encode()
            )
            second = read_answer(client)
            client.sendall(
                f"GET /c HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n\r\n".encode()
            )
            third = read_answer(client)

        assert first.startswith(b"HTTP/1.1 200") and first.endswith(first_head)
        assert second.endswith(b"\r\n\r\nhi")
        assert third.startswith(b"HTTP/1.1 401")
        assert page.connections == 1
        assert [head.split(b"\r\n")[0] for head in page.requests] == [
            b"GET /a HTTP/1.1",
            b"POST /b HTTP/1.1",
        ]
        assert hooks.admitted == ["/a", "/b", "/c"]
    finally:
        forwarder.close()
        page.stop()


def test_a_wrong_host_is_421_and_a_wrong_origin_403_passed_to_nobody():
    page = FakePage()
    hooks = DemoHooks(page.port)
    forwarder = forwarder_for(hooks, free_port())
    try:
        forwarder.start()
        wait_until(lambda: forwarder.is_listening)
        port = forwarder.port

        rebound = exchange(
            port, b"GET / HTTP/1.1\r\nHost: evil.example\r\nCookie: demo=ok\r\n\r\n"
        )
        crossed = exchange(
            port,
            f"GET / HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
            "Origin: http://127.0.0.1:1\r\nCookie: demo=ok\r\n\r\n".encode(),
        )

        assert rebound.startswith(b"HTTP/1.1 421")
        assert crossed.startswith(b"HTTP/1.1 403")
        assert hooks.admitted == []
        assert page.requests == []
    finally:
        forwarder.close()
        page.stop()


def test_a_chunked_body_is_411_and_a_page_that_does_not_answer_is_502():
    hooks = DemoHooks(free_port())
    forwarder = forwarder_for(hooks, free_port())
    try:
        forwarder.start()
        wait_until(lambda: forwarder.is_listening)
        port = forwarder.port
        host = f"Host: 127.0.0.1:{port}\r\nCookie: demo=ok"

        chunked = exchange(
            port,
            f"POST / HTTP/1.1\r\n{host}\r\nTransfer-Encoding: chunked\r\n\r\n".encode(),
        )
        silent = exchange(port, f"GET / HTTP/1.1\r\n{host}\r\n\r\n".encode())

        assert chunked.startswith(b"HTTP/1.1 411")
        assert silent.startswith(b"HTTP/1.1 502")
    finally:
        forwarder.close()


def test_both_sockets_of_a_forwarder_send_at_once(monkeypatch):
    page = FakePage()
    hooks = DemoHooks(page.port)
    forwarder = forwarder_for(hooks, free_port())
    nodelay = (socket.IPPROTO_TCP, socket.TCP_NODELAY)
    seen = []
    real = http_forward_module.set_no_delay

    def spy(connection):
        real(connection)
        seen.append(connection.getsockopt(*nodelay))

    monkeypatch.setattr(http_forward_module, "set_no_delay", spy)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    try:
        browser = socket.create_connection(listener.getsockname(), timeout=5)
        accepted, _ = listener.accept()
        with browser, accepted:
            browser.sendall(
                b"GET / HTTP/1.1\r\nHost: 127.0.0.1\r\nCookie: demo=ok\r\n"
                b"Connection: close\r\n\r\n"
            )
            forwarder.handle(accepted)

        assert len(seen) == 2 and all(seen)
    finally:
        listener.close()
        page.stop()


def test_a_websocket_is_relayed_both_ways():
    page = FakePage()
    forwarder = forwarder_for(DemoHooks(page.port), free_port())
    try:
        forwarder.start()
        wait_until(lambda: forwarder.is_listening)

        with socket.create_connection(("127.0.0.1", forwarder.port), timeout=5) as ws:
            ws.sendall(
                b"GET /ws HTTP/1.1\r\nHost: 127.0.0.1\r\nCookie: demo=ok\r\n"
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


# --- a page's own login cookie, renamed both ways ---


def test_a_requests_cookie_is_renamed_to_the_pages_own_and_its_namesake_dropped():
    head = (
        b"GET / HTTP/1.1\r\nHost: 127.0.0.1\r\n"
        b"Cookie: a=1; siyuan=theirs; neutrino_abc=mine\r\n"
        b"cookie: siyuan=other\r\nAccept: */*\r\n\r\n"
    )

    renamed = renamed_request_cookies(head, kept="neutrino_abc", page="siyuan")

    assert renamed == (
        b"GET / HTTP/1.1\r\nHost: 127.0.0.1\r\n"
        b"Cookie: a=1; siyuan=mine\r\nAccept: */*\r\n\r\n"
    )


def test_a_set_cookie_of_the_pages_own_name_is_renamed_and_others_kept():
    head = (
        b"HTTP/1.1 200 OK\r\nSet-Cookie: siyuan=v1; Path=/; HttpOnly\r\n"
        b"set-cookie: siyuanx=v2\r\nSet-Cookie: other=v3\r\n\r\n"
    )

    renamed = renamed_set_cookies(head, page="siyuan", kept="neutrino_abc")

    assert renamed == (
        b"HTTP/1.1 200 OK\r\nSet-Cookie: neutrino_abc=v1; Path=/; HttpOnly\r\n"
        b"set-cookie: siyuanx=v2\r\nSet-Cookie: other=v3\r\n\r\n"
    )


def test_a_relayed_answer_takes_the_rename():
    left, right = socket.socketpair()
    page_left, page_right = socket.socketpair()
    with left, right, page_left, page_right:
        page_left.sendall(
            b"HTTP/1.1 200 OK\r\nSet-Cookie: siyuan=v; Path=/\r\n"
            b"Content-Length: 2\r\n\r\nok"
        )
        assert relay_answer(
            ConnectionReader(page_right),
            left,
            "GET",
            lambda head: renamed_set_cookies(head, page="siyuan", kept="neutrino_x"),
        )
        received = right.recv(65536)
    assert b"Set-Cookie: neutrino_x=v; Path=/\r\n" in received
    assert received.endswith(b"\r\n\r\nok")


class RenamingHooks(DemoHooks):
    """Hooks whose page keeps its login in a cookie of its own fixed name."""

    page_cookie = "siyuan"

    def admit(self, request, record):
        if request.cookie_values(record["cookie_name"]):
            return RELAY
        return refused()


def test_the_forwarder_renames_the_cookie_toward_the_page_websocket_included():
    page = FakePage()
    forwarder = InstanceForwarder(
        name="demo",
        record={
            "account": "ann",
            "port": free_port(),
            "secret": SECRET,
            "cookie_name": "neutrino_abc",
        },
        hooks=RenamingHooks(page.port),
        log=lambda line: None,
        ready_poll_s=0.01,
        retry_s=0.01,
    )
    try:
        forwarder.start()
        wait_until(lambda: forwarder.is_listening)

        answer = exchange(
            forwarder.port,
            b"GET /stage HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            b"Cookie: siyuan=forged; neutrino_abc=v\r\nConnection: close\r\n\r\n",
        )
        with socket.create_connection(("127.0.0.1", forwarder.port), timeout=5) as ws:
            ws.sendall(
                b"GET /ws?type=main HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                b"Origin: http://127.0.0.1\r\nCookie: neutrino_abc=v\r\n"
                b"Connection: Upgrade\r\nUpgrade: websocket\r\n\r\n"
            )
            received = b""
            while b"\r\n\r\n" not in received:
                received += ws.recv(65536)
        refused_answer = exchange(
            forwarder.port,
            b"GET / HTTP/1.1\r\nHost: 127.0.0.1\r\nCookie: siyuan=v\r\n"
            b"Connection: close\r\n\r\n",
        )
    finally:
        forwarder.close()
        page.stop()

    assert answer.startswith(b"HTTP/1.1 200")
    assert b"Cookie: siyuan=v\r\n" in page.requests[0]
    assert b"forged" not in page.requests[0]
    assert b"neutrino_abc" not in page.requests[0]
    assert received.startswith(b"HTTP/1.1 101")
    assert b"Cookie: siyuan=v\r\n" in page.requests[1]
    assert refused_answer.startswith(b"HTTP/1.1 401")
