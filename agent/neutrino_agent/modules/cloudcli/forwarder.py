"""The forwarder in front of one account's CloudCLI.

CloudCLI listens on loopback alone. The forwarder is a thread of the agent
that listens on loopback at the instance's port, where the agent's end of a
``connect`` stream reaches it, and judges each request before CloudCLI sees
it:

| A request | The forwarder |
| --- | --- |
| asks for CloudCLI's register or login route | 401; those are never passed on |
| carries ``?tkn=<token>`` that verifies | logs in to CloudCLI with the hub's password, answers a page that keeps the login where CloudCLI's own page keeps it, and redirects to ``/`` |
| carries ``?tkn=`` that does not verify, has expired or was spent | 401 |
| carries CloudCLI's login | passed on, a WebSocket included |
| carries neither | 401 |

A token is ``base64url(expiry || nonce || HMAC-SHA256(secret, expiry ||
nonce))``, checked here with no call to the hub; every nonce accepted is
held until its expiry. CloudCLI's login is an HS256 JWT signed with
``JWT_SECRET``, which the agent derives from the instance's secret and sets
in CloudCLI's environment; the forwarder checks a login's signature and
expiry itself. CloudCLI's page keeps the login in
``localStorage['auth-token']`` and sends it as ``Authorization: Bearer``,
and as ``?token=`` on a WebSocket. The exchange also sets the forwarder's
own cookie, ``neutrino_cloudcli_<port>``, holding the same login; a page
load and an asset carry that cookie alone.

Each connection carries one request. An ordinary request is passed on with
``Connection: close`` in place of its own and its body cut at its
``Content-Length``; a WebSocket is passed on unchanged and relayed both ways
until either side closes.

Before CloudCLI's first account exists the forwarder registers it, the
account the instance runs as with the hub's password, and it listens only
once that account signs in.

Not pure: opens sockets.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import binascii
import hashlib
import hmac
import http.client
import json
import socket
import threading
import time
import urllib.parse

from neutrino_agent.constants import AGENT_FORWARD_TOKEN_PARAMETER
from neutrino_agent.modules.cloudcli.constants import (
    CLOUDCLI_BLOCKED_PATHS,
    CLOUDCLI_COOKIE_PREFIX,
    CLOUDCLI_LISTEN_HOST,
    CLOUDCLI_LOGIN_LIFETIME_S,
    CLOUDCLI_LOGIN_PATH,
    CLOUDCLI_QUERY_TOKEN,
    CLOUDCLI_READY_POLL_S,
    CLOUDCLI_REGISTER_PATH,
    CLOUDCLI_REGISTER_RETRY_S,
    CLOUDCLI_STATUS_PATH,
    CLOUDCLI_STORAGE_KEY,
    CLOUDCLI_UPSTREAM_HOST,
    CLOUDCLI_UPSTREAM_TIMEOUT_S,
)
from neutrino_agent.modules.cloudcli.config import jwt_secret, username_of
from neutrino_agent.modules.http_forward import (
    ForwarderServer,
    answer,
    mint_token,
    parse_head,
    read_head,
    relay,
    split_target,
    take_token,
    unpadded_decode,
)

__all__ = ["CloudcliForwarder", "cookie_name", "is_login_valid", "mint_token"]

# The page that keeps CloudCLI's login and goes to CloudCLI's own.
EXCHANGE_PAGE = (
    '<!doctype html><meta charset="utf-8"><title>CloudCLI</title>'
    "<script>localStorage.setItem(%s, %s);location.replace('/');</script>"
)


def is_login_valid(login: str, secret: str, now: float) -> bool:
    """Whether a CloudCLI login is signed with the secret and still current.

    Args:
        login: The JWT.
        secret: The secret CloudCLI signs with, from :func:`jwt_secret`.
        now: Seconds since the epoch.

    Returns:
        True for an HS256 JWT whose signature matches and whose ``exp`` is
        ahead.
    """
    parts = login.split(".")
    if len(parts) != 3:
        return False
    try:
        header = json.loads(unpadded_decode(parts[0]))
        payload = json.loads(unpadded_decode(parts[1]))
        signature = unpadded_decode(parts[2])
    except (ValueError, binascii.Error):
        return False
    if not isinstance(header, dict) or header.get("alg") != "HS256":
        return False
    expected = hmac.new(
        secret.encode("utf-8"),
        f"{parts[0]}.{parts[1]}".encode("ascii", "replace"),
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(expected, signature):
        return False
    expiry = payload.get("exp") if isinstance(payload, dict) else None
    return isinstance(expiry, (int, float)) and expiry > now


def cookie_name(port: int) -> str:
    """The cookie the forwarder of one port keeps CloudCLI's login in."""
    return f"{CLOUDCLI_COOKIE_PREFIX}{int(port)}"


def _normal_path(path: str) -> str:
    """A path as CloudCLI's router matches it: decoded, lower case, slashes collapsed."""
    decoded = urllib.parse.unquote(path).lower()
    while "//" in decoded:
        decoded = decoded.replace("//", "/")
    return decoded.rstrip("/") or "/"


class CloudcliForwarder:
    """Stands in front of one account's CloudCLI on the instance's port."""

    def __init__(
        self,
        *,
        account: str,
        port: int,
        upstream_port: int,
        web_password: str,
        token_secret: str,
        listen_host: str = CLOUDCLI_LISTEN_HOST,
        upstream_host: str = CLOUDCLI_UPSTREAM_HOST,
        clock=time.time,
        log=print,
        ready_poll_s: float = CLOUDCLI_READY_POLL_S,
        retry_s: float = CLOUDCLI_REGISTER_RETRY_S,
    ):
        """
        Args:
            account: The account CloudCLI runs as, which names its
                administrator.
            port: Where the forwarder listens.
            upstream_port: Where CloudCLI listens on loopback.
            web_password: The administrator's password, from the hub.
            token_secret: The secret a token for this instance is signed
                with, from the hub.
            listen_host: The address the forwarder listens on.
            upstream_host: The address CloudCLI listens on.
            clock: Seconds since the epoch.
            log: Callable used for progress messages.
            ready_poll_s: How often CloudCLI is asked whether it answers.
            retry_s: How long a failed registration or bind waits before
                it is tried again.
        """
        self.account = account
        self.port = int(port)
        self.upstream_port = int(upstream_port)
        self._web_password = web_password
        self._token_secret = token_secret
        self._login_secret = jwt_secret(token_secret)
        self._listen_host = listen_host
        self._upstream_host = upstream_host
        self._clock = clock
        self._log = log
        self._ready_poll_s = ready_poll_s
        self._retry_s = retry_s
        self._lock = threading.Lock()
        self._closed = threading.Event()
        self._server: "ForwarderServer | None" = None
        self._spent: dict = {}
        self._code = ""
        self._params: dict = {}
        self._thread = threading.Thread(
            target=self._run, name=f"cloudcli_{account}", daemon=True
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

    def matches(self, record: dict) -> bool:
        """Whether this forwarder serves one instance record as it stands.

        Args:
            record: ``{account, port, upstream_port, web_password,
                token_secret}``.

        Returns:
            True when every field is the same.
        """
        return (
            str(record.get("account", "")) == self.account
            and int(record.get("port", 0) or 0) == self.port
            and int(record.get("upstream_port", 0) or 0) == self.upstream_port
            and str(record.get("web_password", "")) == self._web_password
            and str(record.get("token_secret", "")) == self._token_secret
        )

    def start(self) -> None:
        """Begin waiting for CloudCLI, then listen."""
        self._thread.start()

    def close(self) -> None:
        """Stop listening and stop waiting."""
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
        client.settimeout(CLOUDCLI_UPSTREAM_TIMEOUT_S)
        try:
            head, rest = read_head(client)
        except OSError:
            return
        if head is None:
            return
        request = parse_head(head)
        if request is None:
            return
        method, target, headers = request
        path, query_text = split_target(target)
        query = urllib.parse.parse_qs(query_text, keep_blank_values=True)
        try:
            if _normal_path(path) in CLOUDCLI_BLOCKED_PATHS:
                answer(client, 401)
            elif AGENT_FORWARD_TOKEN_PARAMETER in query:
                self._exchange(client, query[AGENT_FORWARD_TOKEN_PARAMETER][0])
            elif self._has_login(headers, query):
                self._relay(client, head, rest, headers)
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
            return take_token(
                token, secret=self._token_secret, now=now, spent=self._spent
            )

    def settle_account(self) -> bool:
        """Register CloudCLI's administrator when it has none, and sign in.

        Returns:
            True when the account signs in with the hub's password.

        Raises:
            OSError: When CloudCLI does not answer.
        """
        status, answer = self._call("GET", CLOUDCLI_STATUS_PATH)
        if status != 200:
            raise ConnectionError(f"CloudCLI answered {status}")
        credentials = {
            "username": username_of(self.account),
            "password": self._web_password,
        }
        if answer.get("needsSetup") is True:
            status, _ = self._call("POST", CLOUDCLI_REGISTER_PATH, credentials)
            if status == 200:
                self._log(f"cloudcli: registered the administrator of {self.account}")
        return bool(self._login())

    def _run(self) -> None:
        """Wait for CloudCLI and its account, then listen until closed."""
        while not self._closed.is_set():
            try:
                is_settled = self.settle_account()
            except OSError:
                self._closed.wait(self._ready_poll_s)
                continue
            if not is_settled:
                self._fail("cloudcli_register_failed", {"account": self.account})
                self._closed.wait(self._retry_s)
                continue
            try:
                server = ForwarderServer((self._listen_host, self.port), self.handle)
            except OSError:
                self._fail(
                    "cloudcli_port_taken", {"account": self.account, "port": self.port}
                )
                self._closed.wait(self._retry_s)
                continue
            with self._lock:
                if self._closed.is_set():
                    server.server_close()
                    return
                self._server = server
                self._code, self._params = "", {}
            self._log(f"cloudcli: {self.account} answers on port {self.port}")
            server.serve_forever(poll_interval=0.5)
            return

    def _fail(self, code: str, params: dict) -> None:
        with self._lock:
            is_new = self._code != code
            self._code, self._params = code, dict(params)
        if is_new:
            self._log(f"cloudcli: {self.account} {code}")

    def _exchange(self, client: socket.socket, token: str) -> None:
        """Trade a token for CloudCLI's login, kept in the browser."""
        if not self.take_token(token):
            answer(client, 401)
            return
        try:
            login = self._login()
        except OSError:
            login = ""
        if not login:
            answer(client, 502)
            return
        page = EXCHANGE_PAGE % (
            json.dumps(CLOUDCLI_STORAGE_KEY),
            json.dumps(login),
        )
        cookie = (
            f"{cookie_name(self.port)}={login}; Path=/; HttpOnly; "
            f"SameSite=Lax; Max-Age={CLOUDCLI_LOGIN_LIFETIME_S}"
        )
        answer(
            client,
            200,
            page.encode("utf-8"),
            content_type="text/html; charset=utf-8",
            extra=[
                ("Set-Cookie", cookie),
                ("Cache-Control", "no-store"),
                ("Referrer-Policy", "no-referrer"),
            ],
        )

    def _has_login(self, headers: list, query: dict) -> bool:
        """Whether a request carries a login CloudCLI issued and still honours."""
        now = self._clock()
        candidates = list(query.get(CLOUDCLI_QUERY_TOKEN, []))
        wanted = cookie_name(self.port)
        for name, value in headers:
            lowered = name.lower()
            if lowered == "authorization":
                scheme, _, credential = value.strip().partition(" ")
                if scheme.lower() == "bearer":
                    candidates.append(credential.strip())
            elif lowered == "cookie":
                for pair in value.split(";"):
                    key, _, held = pair.strip().partition("=")
                    if key == wanted:
                        candidates.append(held)
        return any(
            is_login_valid(candidate, self._login_secret, now)
            for candidate in candidates
        )

    def _relay(
        self, client: socket.socket, head: bytes, rest: bytes, headers: list
    ) -> None:
        """Pass one request on to CloudCLI and its answer back."""
        relay(client, head, rest, headers, self._connect_upstream)

    def _connect_upstream(self) -> socket.socket:
        """A connection to CloudCLI on loopback; OSError when it does not answer."""
        return socket.create_connection(
            (self._upstream_host, self.upstream_port),
            timeout=CLOUDCLI_UPSTREAM_TIMEOUT_S,
        )

    def _login(self) -> str:
        """CloudCLI's login for the administrator, empty when it refuses; OSError when it does not answer."""
        status, answer = self._call(
            "POST",
            CLOUDCLI_LOGIN_PATH,
            {"username": username_of(self.account), "password": self._web_password},
        )
        if status != 200:
            return ""
        return str(answer.get("token", "") or "")

    def _call(self, method: str, path: str, body: "dict | None" = None) -> tuple:
        """``(status, answer)`` of one call to CloudCLI's JSON API; OSError when it does not answer."""
        connection = http.client.HTTPConnection(
            self._upstream_host,
            self.upstream_port,
            timeout=CLOUDCLI_UPSTREAM_TIMEOUT_S,
        )
        try:
            payload = json.dumps(body).encode("utf-8") if body is not None else None
            connection.request(
                method,
                path,
                body=payload,
                headers={"Content-Type": "application/json"} if payload else {},
            )
            response = connection.getresponse()
            text = response.read()
            status = response.status
        except http.client.HTTPException as error:
            raise ConnectionError(str(error)) from error
        finally:
            connection.close()
        try:
            answer = json.loads(text.decode("utf-8") or "{}")
        except (UnicodeDecodeError, ValueError):
            answer = {}
        return status, answer if isinstance(answer, dict) else {}
