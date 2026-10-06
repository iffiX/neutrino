"""The forwarder in front of CloudCLI, against a fake CloudCLI on loopback.

What these pin: a token signed with the instance's secret works once and
only before its expiry; CloudCLI's register and login routes are never
passed on, however the path is spelled; a request with neither a token nor
a login is 401; a token is traded for CloudCLI's login, kept where its page
keeps it and in the forwarder's cookie, and a redirect to the page; a
request carrying a login CloudCLI signed is passed on with its body, and a
forged or expired one is not; a WebSocket is relayed both ways; and the
forwarder registers CloudCLI's administrator on the first start and
listens only once that account signs in.
"""

import base64
import hashlib
import hmac
import json
import socket
import socketserver
import threading
import time

import pytest

from neutrino_agent.modules.cloudcli.config import jwt_secret
from neutrino_agent.modules.cloudcli.forwarder import (
    CloudcliForwarder,
    cookie_name,
    is_login_valid,
    mint_token,
)

SECRET = "instance-secret"  # scan: allow
PASSWORD = "hub-password-1"  # scan: allow
NOW = 1_800_000_000


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def make_login(secret: str, *, expiry: int, user: str = "ann") -> str:
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64(json.dumps({"userId": 1, "username": user, "exp": expiry}).encode())
    signature = hmac.new(
        secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256
    ).digest()
    return f"{header}.{payload}.{_b64(signature)}"


class FakeCloudcli(socketserver.ThreadingTCPServer):
    """CloudCLI's auth routes, an echo of every other request, and a WebSocket echo."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, *, is_set_up=False):
        self.users: dict = {}
        self.requests: list = []
        if is_set_up:
            self.users["ann"] = PASSWORD
        super().__init__(("127.0.0.1", 0), FakeCloudcliConnection)
        threading.Thread(
            target=self.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        ).start()

    @property
    def port(self) -> int:
        return self.server_address[1]

    def stop(self):
        self.shutdown()
        self.server_close()


class FakeCloudcliConnection(socketserver.BaseRequestHandler):
    def handle(self):
        received = b""
        while b"\r\n\r\n" not in received:
            chunk = self.request.recv(65536)
            if not chunk:
                return
            received += chunk
        head, _, body = received.partition(b"\r\n\r\n")
        lines = head.decode().split("\r\n")
        method, target, _version = lines[0].split(" ")
        headers = dict(
            (name.strip().lower(), value.strip())
            for name, _, value in (line.partition(":") for line in lines[1:])
        )
        length = int(headers.get("content-length", 0) or 0)
        while len(body) < length:
            body += self.request.recv(65536)
        server = self.server
        server.requests.append((method, target, headers, body))
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
        if target == "/api/auth/status":
            self._json(200, {"needsSetup": not server.users, "isAuthenticated": False})
        elif target == "/api/auth/register":
            sent = json.loads(body)
            if server.users:
                self._json(403, {"error": "User already exists"})
            else:
                server.users[sent["username"]] = sent["password"]
                self._json(200, {"success": True, "token": "x"})
        elif target == "/api/auth/login":
            sent = json.loads(body)
            if server.users.get(sent["username"]) == sent["password"]:
                login = make_login(jwt_secret(SECRET), expiry=int(time.time()) + 3600)
                self._json(200, {"success": True, "token": login})
            else:
                self._json(401, {"error": "Invalid username or password"})
        else:
            self._json(200, {"echo": target, "body": body.decode()})

    def _json(self, status, document):
        body = json.dumps(document).encode()
        self.request.sendall(
            f"HTTP/1.1 {status} X\r\nContent-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode() + body
        )


@pytest.fixture
def cloudcli():
    server = FakeCloudcli()
    yield server
    server.stop()


def make_forwarder(upstream_port, *, clock=time.time, account="ann"):
    return CloudcliForwarder(
        account=account,
        port=0,
        upstream_port=upstream_port,
        web_password=PASSWORD,
        token_secret=SECRET,
        clock=clock,
        log=lambda line: None,
        ready_poll_s=0.05,
        retry_s=0.05,
    )


def test_the_forwarder_listens_on_loopback_alone(listening):
    forwarder, _ = listening

    assert forwarder.listen_address[0] == "127.0.0.1"


def wait_listening(forwarder, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if forwarder.is_listening:
            return forwarder.listen_address[1]
        time.sleep(0.02)
    raise AssertionError(f"never listened: {forwarder.failure}")


@pytest.fixture
def listening(cloudcli):
    forwarder = make_forwarder(cloudcli.port)
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


# --- the token ---


def test_a_token_works_once_and_only_with_the_secret_before_its_expiry():
    clock = [NOW]
    forwarder = make_forwarder(1, clock=lambda: clock[0])

    token = mint_token(SECRET, expiry=NOW + 60, nonce=b"n" * 16)
    assert forwarder.take_token(token) is True
    assert forwarder.take_token(token) is False

    assert (
        forwarder.take_token(mint_token("other", expiry=NOW + 60, nonce=b"a" * 16))
        is False
    )
    assert (
        forwarder.take_token(mint_token(SECRET, expiry=NOW, nonce=b"b" * 16)) is False
    )
    assert (
        forwarder.take_token(mint_token(SECRET, expiry=NOW + 3600, nonce=b"c" * 16))
        is False
    )
    assert forwarder.take_token("not a token") is False
    assert forwarder.take_token(token[:-4]) is False


def test_a_spent_nonce_is_forgotten_once_its_token_expired():
    clock = [NOW]
    forwarder = make_forwarder(1, clock=lambda: clock[0])
    assert forwarder.take_token(mint_token(SECRET, expiry=NOW + 60, nonce=b"n" * 16))

    clock[0] = NOW + 61
    assert forwarder.take_token(mint_token(SECRET, expiry=NOW + 120, nonce=b"m" * 16))

    assert list(forwarder._spent) == [b"m" * 16]


def test_a_token_is_the_layout_the_standard_names():
    token = mint_token(SECRET, expiry=NOW, nonce=b"\x01" * 16)
    raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))

    assert raw[:8] == NOW.to_bytes(8, "big")
    assert raw[8:24] == b"\x01" * 16
    assert raw[24:] == hmac.new(SECRET.encode(), raw[:24], hashlib.sha256).digest()


# --- CloudCLI's login ---


def test_a_login_verifies_only_under_its_secret_and_before_its_expiry():
    secret = jwt_secret(SECRET)
    login = make_login(secret, expiry=NOW + 10)

    assert is_login_valid(login, secret, NOW) is True
    assert is_login_valid(login, secret, NOW + 10) is False
    assert is_login_valid(make_login("other", expiry=NOW + 10), secret, NOW) is False
    assert is_login_valid("a.b", secret, NOW) is False
    assert is_login_valid("x.y.z", secret, NOW) is False


# --- the requests ---


@pytest.mark.parametrize(
    "path",
    [
        "/api/auth/register",
        "/api/auth/login",
        "/API/Auth/Login",
        "//api/auth//login/",
        "/api/auth/%6Cogin",
    ],
)
def test_the_register_and_login_routes_are_never_passed_on(listening, cloudcli, path):
    _forwarder, port = listening
    login = make_login(jwt_secret(SECRET), expiry=int(time.time()) + 60)
    before = len(cloudcli.requests)

    answer = ask(
        port,
        f"POST {path} HTTP/1.1\r\nAuthorization: Bearer {login}\r\n"
        "Content-Length: 2\r\n\r\n{}".encode(),
    )

    assert status_of(answer) == 401
    assert len(cloudcli.requests) == before


def test_a_request_with_neither_a_token_nor_a_login_is_refused(listening, cloudcli):
    _forwarder, port = listening
    before = len(cloudcli.requests)

    assert status_of(ask(port, b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")) == 401
    assert status_of(ask(port, b"GET /health HTTP/1.1\r\n\r\n")) == 401
    assert len(cloudcli.requests) == before


def test_a_token_is_traded_for_cloudclis_login_kept_in_the_browser(listening):
    forwarder, port = listening
    token = mint_token(SECRET, expiry=int(time.time()) + 60, nonce=b"t" * 16)

    answer = ask(port, f"GET /?tkn={token} HTTP/1.1\r\n\r\n".encode())

    head, _, body = answer.partition(b"\r\n\r\n")
    assert status_of(answer) == 200
    text = body.decode()
    assert 'localStorage.setItem("auth-token", "' in text
    assert "location.replace('/')" in text
    login = text.split('"auth-token", "')[1].split('"')[0]
    assert is_login_valid(login, jwt_secret(SECRET), time.time())
    assert (
        f"Set-Cookie: {cookie_name(forwarder.port)}={login}; Path=/; HttpOnly".encode()
        in head
    )
    assert b"Cache-Control: no-store" in head

    again = ask(port, f"GET /?tkn={token} HTTP/1.1\r\n\r\n".encode())
    assert status_of(again) == 401


def test_a_token_that_does_not_verify_is_refused(listening):
    _forwarder, port = listening
    token = mint_token("wrong", expiry=int(time.time()) + 60, nonce=b"w" * 16)

    assert status_of(ask(port, f"GET /?tkn={token} HTTP/1.1\r\n\r\n".encode())) == 401


@pytest.mark.parametrize("carrier", ["cookie", "bearer", "query"])
def test_a_request_with_cloudclis_login_is_passed_on_with_its_body(
    listening, cloudcli, carrier
):
    forwarder, port = listening
    login = make_login(jwt_secret(SECRET), expiry=int(time.time()) + 60)
    target = "/api/projects"
    extra = ""
    if carrier == "cookie":
        extra = f"Cookie: other=1; {cookie_name(forwarder.port)}={login}\r\n"
    elif carrier == "bearer":
        extra = f"Authorization: Bearer {login}\r\n"
    else:
        target += f"?token={login}"

    answer = ask(
        port,
        f"POST {target} HTTP/1.1\r\nKeep-Alive: 5\r\nConnection: keep-alive\r\n{extra}"
        "Content-Length: 5\r\n\r\nhelloGET /api/auth/login HTTP/1.1\r\n\r\n".encode(),
    )

    assert status_of(answer) == 200
    assert json.loads(answer.partition(b"\r\n\r\n")[2]) == {
        "echo": target,
        "body": "hello",
    }
    method, seen_target, headers, body = cloudcli.requests[-1]
    assert (method, seen_target, body) == ("POST", target, b"hello")
    assert headers["connection"] == "close"
    assert "keep-alive" not in headers


def test_a_forged_or_expired_login_is_refused(listening):
    forwarder, port = listening
    forged = make_login("other", expiry=int(time.time()) + 60)
    expired = make_login(jwt_secret(SECRET), expiry=int(time.time()) - 1)
    for login in (forged, expired):
        answer = ask(
            port,
            f"GET / HTTP/1.1\r\nCookie: {cookie_name(forwarder.port)}={login}\r\n\r\n".encode(),
        )
        assert status_of(answer) == 401


def test_a_body_without_a_length_is_refused(listening):
    _forwarder, port = listening
    login = make_login(jwt_secret(SECRET), expiry=int(time.time()) + 60)

    answer = ask(
        port,
        f"POST /x HTTP/1.1\r\nAuthorization: Bearer {login}\r\n"
        "Transfer-Encoding: chunked\r\n\r\n0\r\n\r\n".encode(),
    )

    assert status_of(answer) == 411


def test_a_websocket_with_cloudclis_login_is_relayed_both_ways(listening, cloudcli):
    _forwarder, port = listening
    login = make_login(jwt_secret(SECRET), expiry=int(time.time()) + 60)
    with socket.create_connection(("127.0.0.1", port), timeout=5) as client:
        client.sendall(
            f"GET /ws?token={login} HTTP/1.1\r\nUpgrade: websocket\r\n"
            "Connection: Upgrade\r\nSec-WebSocket-Key: abc\r\n\r\n".encode()
        )
        handshake = b""
        while b"\r\n\r\n" not in handshake:
            handshake += client.recv(4096)
        assert status_of(handshake) == 101
        client.sendall(b"frame one")
        echoed = b""
        while len(echoed) < 9:
            echoed += client.recv(4096)
        assert echoed == b"FRAME ONE"
    _method, target, headers, _body = cloudcli.requests[-1]
    assert target == f"/ws?token={login}"
    assert headers["connection"] == "Upgrade"


# --- the first start ---


def test_the_administrator_is_registered_on_the_first_start(cloudcli):
    forwarder = make_forwarder(cloudcli.port)

    assert forwarder.settle_account() is True

    assert cloudcli.users == {"ann": PASSWORD}
    assert forwarder.settle_account() is True
    assert cloudcli.users == {"ann": PASSWORD}


def test_a_short_account_is_registered_under_a_padded_name(cloudcli):
    forwarder = make_forwarder(cloudcli.port, account="al")

    assert forwarder.settle_account() is True

    assert cloudcli.users == {"al_": PASSWORD}


def test_an_administrator_with_another_password_is_reported_and_never_listens():
    cloudcli = FakeCloudcli(is_set_up=True)
    cloudcli.users["ann"] = "somebody-else"
    forwarder = make_forwarder(cloudcli.port)
    try:
        forwarder.start()
        deadline = time.monotonic() + 5
        while forwarder.failure[0] == "" and time.monotonic() < deadline:
            time.sleep(0.02)
        assert forwarder.failure == ("cloudcli_register_failed", {"account": "ann"})
        assert forwarder.is_listening is False
    finally:
        forwarder.close()
        cloudcli.stop()


def test_nothing_is_answered_until_cloudcli_answers():
    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    port = holder.getsockname()[1]
    holder.close()
    forwarder = make_forwarder(port)
    try:
        forwarder.start()
        time.sleep(0.2)
        assert forwarder.is_listening is False
        assert forwarder.failure == ("", {})
    finally:
        forwarder.close()


def test_a_taken_port_is_reported(cloudcli):
    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    taken = holder.getsockname()[1]
    forwarder = CloudcliForwarder(
        account="ann",
        port=taken,
        upstream_port=cloudcli.port,
        web_password=PASSWORD,
        token_secret=SECRET,
        listen_host="127.0.0.1",
        log=lambda line: None,
        ready_poll_s=0.05,
        retry_s=0.05,
    )
    try:
        forwarder.start()
        deadline = time.monotonic() + 5
        while forwarder.failure[0] == "" and time.monotonic() < deadline:
            time.sleep(0.02)
        assert forwarder.failure == (
            "cloudcli_port_taken",
            {"account": "ann", "port": taken},
        )
    finally:
        forwarder.close()
        holder.close()


def test_a_record_matches_only_the_forwarder_it_describes():
    forwarder = make_forwarder(4000)
    record = {
        "account": "ann",
        "port": 0,
        "upstream_port": 4000,
        "web_password": PASSWORD,
        "token_secret": SECRET,
    }

    assert forwarder.matches(record) is True
    assert forwarder.matches(dict(record, token_secret="new")) is False
    assert forwarder.matches(dict(record, port=9000)) is False


def test_an_administrator_with_another_password_asks_once_to_start_afresh():
    cloudcli = FakeCloudcli(is_set_up=True)
    cloudcli.users["ann"] = "somebody-else"
    asked = []
    forwarder = CloudcliForwarder(
        account="ann",
        port=0,
        upstream_port=cloudcli.port,
        web_password=PASSWORD,
        token_secret=SECRET,
        log=lambda line: None,
        on_refused=asked.append,
    )
    try:
        assert forwarder.settle_account() is False
        assert forwarder.settle_account() is False
        assert asked == ["ann"]
        cloudcli.users.clear()
        assert forwarder.settle_account() is True
        assert cloudcli.users == {"ann": PASSWORD}
    finally:
        cloudcli.stop()
