"""The forwarder in front of code-server, against a fake code-server on a socket.

What these pin: the forwarder listens on ``127.0.0.1`` alone; a token
signed with the instance's secret is traded once for a login cookie of the
port's own name and a redirect to the same address without the token; a
token that does not verify, has expired or was spent is 401; a request with
neither a token nor a good cookie is 401; a forged or expired cookie is
401; a request with a good cookie reaches the socket unchanged, its body
included; a WebSocket is relayed both ways; a code-server that does not
answer is 502; and a taken port is reported.
"""

import shutil
import socket
import socketserver
import tempfile
import threading
import time

import pytest

from neutrino_agent.modules.code_server.config import cookie_key
from neutrino_agent.modules.code_server.constants import CODE_SERVER_LISTEN_HOST
from neutrino_agent.modules.code_server.forwarder import (
    CodeServerForwarder,
    address_without_token,
    cookie_name,
    is_login_valid,
    mint_login,
)
from neutrino_agent.modules.http_forward import mint_token

SECRET = "instance-secret"  # scan: allow
NOW = 1_800_000_000


class FakeCodeServer(socketserver.ThreadingUnixStreamServer):
    """An echo of every request, and a WebSocket echo, on a Unix socket."""

    daemon_threads = True

    def __init__(self, path):
        self.requests: list = []
        super().__init__(path, FakeCodeServerConnection)
        threading.Thread(
            target=self.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        ).start()

    def stop(self):
        self.shutdown()
        self.server_close()


class FakeCodeServerConnection(socketserver.BaseRequestHandler):
    def handle(self):
        received = b""
        while b"\r\n\r\n" not in received:
            chunk = self.request.recv(65536)
            if not chunk:
                return
            received += chunk
        head, _, body = received.partition(b"\r\n\r\n")
        lines = head.decode().split("\r\n")
        headers = dict(
            (name.strip().lower(), value.strip())
            for name, _, value in (line.partition(":") for line in lines[1:])
        )
        length = int(headers.get("content-length", 0) or 0)
        while len(body) < length:
            body += self.request.recv(65536)
        self.server.requests.append((head + b"\r\n\r\n", body))
        if headers.get("upgrade", "").lower() == "websocket":
            self.request.sendall(
                b"HTTP/1.1 101 Switching Protocols\r\n"
                b"Upgrade: websocket\r\nConnection: Upgrade\r\n\r\n"
            )
            while True:
                data = self.request.recv(65536)
                if not data:
                    return
                self.request.sendall(data.upper())
        answer = b"echo " + lines[0].encode() + b" " + body
        self.request.sendall(
            b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\nConnection: close\r\n\r\n"
            % len(answer)
            + answer
        )


@pytest.fixture
def socket_dir():
    directory = tempfile.mkdtemp(prefix="cs", dir="/tmp")
    yield directory
    shutil.rmtree(directory, ignore_errors=True)


@pytest.fixture
def code_server(socket_dir):
    server = FakeCodeServer(f"{socket_dir}/code_server.sock")
    yield server
    server.stop()


def make_forwarder(socket_path, *, clock=time.time, port=0):
    return CodeServerForwarder(
        account="ann",
        port=port,
        secret=SECRET,
        socket_path=socket_path,
        clock=clock,
        log=lambda line: None,
        retry_s=0.05,
    )


def wait_listening(forwarder, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if forwarder.is_listening:
            return forwarder.listen_address[1]
        time.sleep(0.02)
    raise AssertionError(f"never listened: {forwarder.failure}")


@pytest.fixture
def listening(code_server, socket_dir):
    forwarder = make_forwarder(f"{socket_dir}/code_server.sock")
    forwarder.start()
    port = wait_listening(forwarder)
    yield forwarder, port
    forwarder.close()


def ask(port, request: bytes) -> bytes:
    with socket.create_connection(("127.0.0.1", port), timeout=5) as client:
        client.sendall(request)
        received = b""
        while True:
            data = client.recv(65536)
            if not data:
                return received
            received += data


def status_of(answer: bytes) -> int:
    return int(answer.split(b" ", 2)[1])


def header_of(answer: bytes, name: bytes) -> str:
    for line in answer.split(b"\r\n\r\n")[0].split(b"\r\n")[1:]:
        key, _, value = line.partition(b":")
        if key.strip().lower() == name:
            return value.strip().decode()
    return ""


def good_cookie(port, *, expiry=None):
    expiry = int(time.time()) + 3600 if expiry is None else expiry
    return f"{cookie_name(port)}={mint_login(cookie_key(SECRET), expiry)}"


def test_the_forwarder_listens_on_loopback_alone(listening):
    forwarder, _port = listening

    assert CODE_SERVER_LISTEN_HOST == "127.0.0.1"
    assert forwarder.listen_address[0] == "127.0.0.1"


def test_a_token_is_traded_once_for_a_cookie_and_a_redirect(listening, code_server):
    forwarder, port = listening
    token = mint_token(SECRET, expiry=int(time.time()) + 60, nonce=b"n" * 16)

    answer = ask(port, f"GET /x/?folder=/h&tkn={token} HTTP/1.1\r\n\r\n".encode())
    again = ask(port, f"GET /?tkn={token} HTTP/1.1\r\n\r\n".encode())

    assert status_of(answer) == 302
    assert header_of(answer, b"location") == "/x/?folder=%2Fh"
    cookie = header_of(answer, b"set-cookie")
    name, _, rest = cookie.partition("=")
    value = rest.split(";")[0]
    assert name == cookie_name(forwarder.port)
    assert cookie_name(8443) == "neutrino_code_server_8443"
    assert "HttpOnly" in cookie and "Max-Age=604800" in cookie
    assert is_login_valid(value, cookie_key(SECRET), time.time() + 6 * 24 * 3600)
    assert status_of(again) == 401
    assert code_server.requests == []


def test_a_token_that_does_not_verify_or_expired_is_refused(listening):
    _forwarder, port = listening
    forged = mint_token("other", expiry=int(time.time()) + 60, nonce=b"a" * 16)
    expired = mint_token(SECRET, expiry=int(time.time()) - 1, nonce=b"b" * 16)

    for token in (forged, expired, "junk"):
        assert status_of(ask(port, f"GET /?tkn={token} HTTP/1.1\r\n\r\n".encode())) == (
            401
        )


def test_a_request_with_neither_a_token_nor_a_cookie_is_refused(listening, code_server):
    _forwarder, port = listening

    assert status_of(ask(port, b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")) == 401
    assert code_server.requests == []


def test_a_forged_or_expired_cookie_is_refused(listening):
    forwarder, port = listening
    expired = good_cookie(forwarder.port, expiry=int(time.time()) - 1)
    forged = f"{cookie_name(forwarder.port)}={mint_login(cookie_key('x'), NOW * 2)}"
    other_port = good_cookie(forwarder.port + 1)

    for cookie in (expired, forged, other_port):
        request = f"GET / HTTP/1.1\r\nCookie: {cookie}\r\n\r\n".encode()
        assert status_of(ask(port, request)) == 401


def test_a_request_with_a_good_cookie_reaches_the_socket_unchanged(
    listening, code_server
):
    forwarder, port = listening
    cookie = good_cookie(forwarder.port)
    request = (
        f"POST /api?x=1 HTTP/1.1\r\nHost: s.localhost:{port}\r\n"
        f"Cookie: a=b; {cookie}\r\nContent-Length: 5\r\n\r\nhello"
    ).encode()

    answer = ask(port, request)

    assert status_of(answer) == 200
    assert answer.endswith(b"echo POST /api?x=1 HTTP/1.1 hello")
    ((head, body),) = code_server.requests
    assert f"Host: s.localhost:{port}".encode() in head
    assert cookie.encode() in head
    assert body == b"hello"


def test_a_websocket_with_a_good_cookie_is_relayed_both_ways(listening, code_server):
    forwarder, port = listening
    with socket.create_connection(("127.0.0.1", port), timeout=5) as client:
        client.sendall(
            (
                "GET /stable HTTP/1.1\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                f"Cookie: {good_cookie(forwarder.port)}\r\n\r\n"
            ).encode()
        )
        received = b""
        while b"\r\n\r\n" not in received:
            received += client.recv(65536)
        assert status_of(received) == 101
        client.sendall(b"ping")
        echoed = b""
        while len(echoed) < 4:
            echoed += client.recv(65536)

    assert echoed == b"PING"


def test_a_code_server_that_does_not_answer_is_502(socket_dir):
    forwarder = make_forwarder(f"{socket_dir}/missing.sock")
    forwarder.start()
    try:
        port = wait_listening(forwarder)
        cookie = good_cookie(forwarder.port)
        request = f"GET / HTTP/1.1\r\nCookie: {cookie}\r\n\r\n".encode()
        assert status_of(ask(port, request)) == 502
    finally:
        forwarder.close()


def test_a_taken_port_is_reported(socket_dir):
    with socket.socket() as holder:
        holder.bind(("127.0.0.1", 0))
        holder.listen()
        taken = holder.getsockname()[1]
        forwarder = make_forwarder(f"{socket_dir}/x.sock", port=taken)
        forwarder.start()
        try:
            deadline = time.monotonic() + 5
            while not forwarder.failure[0] and time.monotonic() < deadline:
                time.sleep(0.02)
            assert forwarder.failure == (
                "code_server_port_taken",
                {"account": "ann", "port": taken},
            )
            assert forwarder.is_listening is False
        finally:
            forwarder.close()


def test_a_token_s_redirect_keeps_the_rest_of_the_address():
    assert address_without_token("/", "tkn=a") == "/"
    assert address_without_token("", "tkn=a") == "/"
    assert address_without_token("/p", "a=1&tkn=x&b=2") == "/p?a=1&b=2"


def test_a_record_matches_only_the_forwarder_it_describes():
    forwarder = make_forwarder("/s", port=8443)
    record = {"account": "ann", "port": 8443, "secret": SECRET}

    assert forwarder.matches(record, "/s")
    assert not forwarder.matches(dict(record, port=8444), "/s")
    assert not forwarder.matches(dict(record, secret="t"), "/s")
    assert not forwarder.matches(record, "/t")
