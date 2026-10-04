"""What every forwarder shares: the token, a request's head, the relay.

What these pin: a token is the layout the standard names and works once,
only with its secret, only before its expiry and within the horizon; a
spent nonce is dropped once its token expired; a request's head is read up
to its end and refused past the limit; a cookie's values are found across
headers; an ordinary request is passed on with ``Connection: close`` and
its body cut at its length; a chunked body is 411; a page that does not
answer is 502; and the server hands each connection to its callable.
"""

import base64
import hashlib
import hmac
import socket
import threading

from neutrino_agent.modules.http_forward import (
    ForwarderServer,
    closing_head,
    cookie_values,
    mint_token,
    parse_head,
    read_head,
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
