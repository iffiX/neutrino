"""The forwarder in front of one account's code-server.

code-server listens on a socket only its account and root open, with its
own login off. The forwarder is a thread of the agent that listens on
``127.0.0.1`` at the instance's port and judges each request before
code-server sees it:

| A request | The forwarder |
| --- | --- |
| carries ``?tkn=<token>`` that verifies | sets its login cookie and redirects to the same address without the token |
| carries ``?tkn=`` that does not verify, has expired or was spent | 401 |
| carries the login cookie with a good signature and expiry | passed on unchanged to the socket, a WebSocket included |
| carries neither | 401 |

The token is the one :mod:`neutrino_agent.modules.http_forward` checks.
The login cookie, ``neutrino_code_server_<port>``, is
``base64url(expiry || HMAC-SHA256(key, expiry))`` with the key derived from
the instance's secret, and lasts seven days.

Not pure: opens sockets.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import socket
import threading
import time
import urllib.parse

from neutrino_agent.constants import AGENT_FORWARD_TOKEN_PARAMETER
from neutrino_agent.modules.code_server.config import cookie_key
from neutrino_agent.modules.code_server.constants import (
    CODE_SERVER_BIND_RETRY_S,
    CODE_SERVER_COOKIE_EXPIRY_BYTES,
    CODE_SERVER_COOKIE_MAC_BYTES,
    CODE_SERVER_COOKIE_PREFIX,
    CODE_SERVER_LISTEN_HOST,
    CODE_SERVER_LOGIN_LIFETIME_S,
    CODE_SERVER_UPSTREAM_TIMEOUT_S,
)
from neutrino_agent.modules.http_forward import (
    ForwarderServer,
    answer,
    cookie_values,
    parse_head,
    read_head,
    relay,
    split_target,
    take_token,
    unpadded_decode,
)


def cookie_name(port: int) -> str:
    """The cookie the forwarder of one port keeps its login in."""
    return f"{CODE_SERVER_COOKIE_PREFIX}{int(port)}"


def mint_login(key: bytes, expiry: int) -> str:
    """One login cookie's value.

    Args:
        key: From :func:`cookie_key`.
        expiry: When it stops working, in seconds since the epoch.

    Returns:
        ``base64url(expiry || HMAC-SHA256(key, expiry))`` without padding.
    """
    body = int(expiry).to_bytes(CODE_SERVER_COOKIE_EXPIRY_BYTES, "big")
    mac = hmac.new(key, body, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(body + mac).rstrip(b"=").decode("ascii")


def is_login_valid(login: str, key: bytes, now: float) -> bool:
    """Whether a login cookie is signed with the key and still current.

    Args:
        login: The cookie's value.
        key: From :func:`cookie_key`.
        now: Seconds since the epoch.

    Returns:
        True when the signature matches and the expiry is ahead.
    """
    try:
        raw = unpadded_decode(login)
    except (ValueError, binascii.Error):
        return False
    if len(raw) != CODE_SERVER_COOKIE_EXPIRY_BYTES + CODE_SERVER_COOKIE_MAC_BYTES:
        return False
    body, mac = (
        raw[:CODE_SERVER_COOKIE_EXPIRY_BYTES],
        raw[CODE_SERVER_COOKIE_EXPIRY_BYTES:],
    )
    expected = hmac.new(key, body, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, mac):
        return False
    return int.from_bytes(body, "big") > now


def address_without_token(path: str, query: str) -> str:
    """The address a token's redirect goes to: the same, its token taken out.

    Args:
        path: The request's path.
        query: The request's query.

    Returns:
        The path, and the query's other fields in their order.
    """
    kept = [
        (name, value)
        for name, value in urllib.parse.parse_qsl(query, keep_blank_values=True)
        if name != AGENT_FORWARD_TOKEN_PARAMETER
    ]
    if not kept:
        return path or "/"
    return f"{path or '/'}?{urllib.parse.urlencode(kept)}"


class CodeServerForwarder:
    """Stands in front of one account's code-server on the instance's port."""

    def __init__(
        self,
        *,
        account: str,
        port: int,
        secret: str,
        socket_path: str,
        listen_host: str = CODE_SERVER_LISTEN_HOST,
        clock=time.time,
        log=print,
        retry_s: float = CODE_SERVER_BIND_RETRY_S,
    ):
        """
        Args:
            account: The account code-server runs as.
            port: Where the forwarder listens.
            secret: The instance's token secret, from the hub.
            socket_path: The socket code-server listens on.
            listen_host: The address the forwarder listens on.
            clock: Seconds since the epoch.
            log: Callable used for progress messages.
            retry_s: How long a failed bind waits before it is tried again.
        """
        self.account = account
        self.port = int(port)
        self.socket_path = socket_path
        self._secret = secret
        self._key = cookie_key(secret)
        self._listen_host = listen_host
        self._clock = clock
        self._log = log
        self._retry_s = retry_s
        self._lock = threading.Lock()
        self._closed = threading.Event()
        self._server: "ForwarderServer | None" = None
        self._spent: dict = {}
        self._code = ""
        self._params: dict = {}
        self._thread = threading.Thread(
            target=self._run, name=f"code_server_{account}", daemon=True
        )

    @property
    def is_listening(self) -> bool:
        """Whether the forwarder answers on its port."""
        with self._lock:
            return self._server is not None

    @property
    def failure(self) -> tuple:
        """Why the forwarder does not listen: ``(code, params)``, empty when it does."""
        with self._lock:
            return self._code, dict(self._params)

    @property
    def listen_address(self) -> tuple:
        """The address and the port the forwarder listens on, once it does."""
        with self._lock:
            server = self._server
        return server.server_address[:2] if server is not None else ("", 0)

    def matches(self, record: dict, socket_path: str) -> bool:
        """Whether this forwarder serves one instance record as it stands.

        Args:
            record: ``{account, port, secret}``.
            socket_path: The socket the record's account listens on.

        Returns:
            True when every field and the socket are the same.
        """
        return (
            str(record.get("account", "")) == self.account
            and int(record.get("port", 0) or 0) == self.port
            and str(record.get("secret", "")) == self._secret
            and socket_path == self.socket_path
        )

    def start(self) -> None:
        """Begin listening, trying the bind again until it takes."""
        self._thread.start()

    def close(self) -> None:
        """Stop listening and stop trying."""
        self._closed.set()
        with self._lock:
            server, self._server = self._server, None
        if server is not None:
            server.shutdown()
            server.server_close()

    def handle(self, client: socket.socket) -> None:
        """Judge the one request a connection carries, and answer or pass it on.

        Args:
            client: The browser's connection, closed by the caller.
        """
        client.settimeout(CODE_SERVER_UPSTREAM_TIMEOUT_S)
        try:
            head, rest = read_head(client)
        except OSError:
            return
        if head is None:
            return
        request = parse_head(head)
        if request is None:
            return
        _method, target, headers = request
        path, query_text = split_target(target)
        query = urllib.parse.parse_qs(query_text, keep_blank_values=True)
        try:
            if AGENT_FORWARD_TOKEN_PARAMETER in query:
                self._exchange(
                    client, query[AGENT_FORWARD_TOKEN_PARAMETER][0], path, query_text
                )
            elif self._has_login(headers):
                relay(client, head, rest, headers, self._connect_upstream)
            else:
                answer(client, 401)
        except OSError:
            return

    def take_token(self, token: str) -> bool:
        """Whether a token verifies and was never spent; spends it if so.

        Args:
            token: What ``?tkn=`` held.

        Returns:
            True for a token signed with this instance's secret, whose
            expiry is ahead and no further than the horizon, and whose
            nonce was not accepted before.
        """
        now = self._clock()
        with self._lock:
            return take_token(token, secret=self._secret, now=now, spent=self._spent)

    def _run(self) -> None:
        """Listen until closed, trying a failed bind again."""
        while not self._closed.is_set():
            try:
                server = ForwarderServer((self._listen_host, self.port), self.handle)
            except OSError:
                self._fail(
                    "code_server_port_taken",
                    {"account": self.account, "port": self.port},
                )
                self._closed.wait(self._retry_s)
                continue
            with self._lock:
                if self._closed.is_set():
                    server.server_close()
                    return
                self._server = server
                self._code, self._params = "", {}
            self._log(f"code_server: {self.account} answers on port {self.port}")
            server.serve_forever(poll_interval=0.5)
            return

    def _fail(self, code: str, params: dict) -> None:
        with self._lock:
            is_new = self._code != code
            self._code, self._params = code, dict(params)
        if is_new:
            self._log(f"code_server: {self.account} {code}")

    def _exchange(
        self, client: socket.socket, token: str, path: str, query: str
    ) -> None:
        """Trade a token for the login cookie, and go to the same address without it."""
        if not self.take_token(token):
            answer(client, 401)
            return
        expiry = int(self._clock()) + CODE_SERVER_LOGIN_LIFETIME_S
        cookie = (
            f"{cookie_name(self.port)}={mint_login(self._key, expiry)}; Path=/; "
            f"HttpOnly; SameSite=Lax; Max-Age={CODE_SERVER_LOGIN_LIFETIME_S}"
        )
        answer(
            client,
            302,
            extra=[
                ("Location", address_without_token(path, query)),
                ("Set-Cookie", cookie),
                ("Cache-Control", "no-store"),
                ("Referrer-Policy", "no-referrer"),
            ],
        )

    def _has_login(self, headers: list) -> bool:
        """Whether a request carries a login cookie this forwarder set and still honours."""
        now = self._clock()
        return any(
            is_login_valid(value, self._key, now)
            for value in cookie_values(headers, cookie_name(self.port))
        )

    def _connect_upstream(self) -> socket.socket:
        """A connection to code-server's socket; OSError when it does not answer."""
        upstream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        upstream.settimeout(CODE_SERVER_UPSTREAM_TIMEOUT_S)
        try:
            upstream.connect(self.socket_path)
        except OSError:
            upstream.close()
            raise
        return upstream
