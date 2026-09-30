"""Talking to the hub with the standard library, pinned over TLS.

The HTTP channel serves joining and leaving; the one live socket in
``ws_client`` connects the same way and carries everything else.

An ``https`` hub is verified by fingerprint alone: the handshake runs with
chain and hostname checks off, and the peer certificate's SHA-256 digest must
match the pinned value before any request bytes leave this machine.
"""

import hashlib
import http.client
import json
import socket
import ssl
import urllib.parse

from neutrino_client.constants import (
    CLIENT_PROTOCOL_REFUSAL_CODES,
    CLIENT_REQUEST_TIMEOUT_S,
)
from neutrino_client.exceptions import (
    GatewayProtocolRefused,
    GatewayRefused,
    GatewayRefusedDetail,
    GatewayUnreachable,
    GatewayUntrusted,
)


def pinned_socket(
    host: str,
    port: int,
    fingerprint: str,
    *,
    timeout: float = CLIENT_REQUEST_TIMEOUT_S,
    on_socket=None,
) -> ssl.SSLSocket:
    """A TLS connection that trusts one certificate and nothing else.

    Args:
        host: The hub's address.
        port: The port to connect to.
        fingerprint: SHA-256 hex the peer certificate must digest to.
        timeout: Socket timeout in seconds.
        on_socket: Called with the TCP socket before it connects and with
            the TLS socket before its handshake, so another thread can end
            the connect; None for nobody. What it raises ends the attempt.

    Returns:
        The connected socket, handshake done and the peer checked.

    Raises:
        GatewayUntrusted: When no fingerprint is pinned, or the peer's does
            not match; the socket is closed before any bytes are sent.
        OSError: On any network failure.
    """
    wanted = fingerprint.strip().lower()
    if not wanted:
        raise GatewayUntrusted(f"no certificate fingerprint is pinned for {host}")
    raw = _connect_tcp(host, port, timeout, on_socket)
    try:
        wrapped = _pinned_context().wrap_socket(
            raw, server_hostname=host, do_handshake_on_connect=False
        )
    except OSError:
        raw.close()
        raise
    try:
        if on_socket is not None:
            on_socket(wrapped)
        wrapped.do_handshake()
    except OSError:
        wrapped.close()
        raise
    certificate = wrapped.getpeercert(binary_form=True) or b""
    if hashlib.sha256(certificate).hexdigest() != wanted:
        wrapped.close()
        raise GatewayUntrusted(
            "the hub's certificate does not match the pinned fingerprint"
        )
    return wrapped


def error_detail(data: bytes) -> dict:
    """The ``detail`` object of an error reply, empty when there is none.

    Args:
        data: The reply body.

    Returns:
        The detail dictionary, or an empty one.
    """
    try:
        detail = json.loads(data.decode("utf-8")).get("detail")
    except (ValueError, UnicodeDecodeError, AttributeError):
        return {}
    return detail if isinstance(detail, dict) else {}


def refusal_error(code: str, params: dict) -> "Exception | None":
    """The typed error one ``{code, params}`` refusal maps to.

    Args:
        code: The hub's code.
        params: Its parameters.

    Returns:
        A protocol refusal for the two admission codes, the typed detail for
        any other code, and None for a refusal that names no code.
    """
    if code in CLIENT_PROTOCOL_REFUSAL_CODES:
        return GatewayProtocolRefused(
            code=code,
            peer=_number(params.get("peer")),
            hub=_number(params.get("hub")),
            minimum=_number(params.get("min")),
        )
    if code:
        return GatewayRefusedDetail(code=code, params=dict(params))
    return None


def _connect_tcp(host: str, port: int, timeout: float, on_socket) -> socket.socket:
    """A TCP connection to the first of the host's addresses that answers.

    Args:
        host: The hub's address.
        port: The port to connect to.
        timeout: Socket timeout in seconds.
        on_socket: Called with each socket before it connects; None for
            nobody.

    Returns:
        The connected socket.

    Raises:
        OSError: When the host resolves to no address or none answers.
    """
    failure: "OSError | None" = None
    for family, kind, proto, _name, address in socket.getaddrinfo(
        host, port, 0, socket.SOCK_STREAM
    ):
        sock = socket.socket(family, kind, proto)
        try:
            if on_socket is not None:
                on_socket(sock)
            sock.settimeout(timeout)
            sock.connect(address)
            return sock
        except OSError as error:
            sock.close()
            failure = error
    if failure is not None:
        raise failure
    raise OSError(f"{host} resolves to no address")


def _number(value) -> int:
    """A protocol number as the wire carried it, 0 for anything else."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _pinned_context() -> ssl.SSLContext:
    """A client context that checks nothing itself; the pin does the judging."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


class GatewayHttpChannel:
    """Posts JSON to the hub and parses its replies."""

    def __init__(self, *, gateway_url: str, fingerprint: str = ""):
        """
        Args:
            gateway_url: Base URL of the hub's agent port, without a trailing
                slash.
            fingerprint: SHA-256 hex of the hub certificate's DER form.
                Required for an ``https`` URL; ignored for plain ``http``.
        """
        self._gateway_url = gateway_url.rstrip("/")
        self._fingerprint = fingerprint.strip().lower()

    def post(self, path: str, payload: dict) -> dict:
        """Post a JSON body and return the JSON reply.

        Args:
            path: Path below the hub URL, starting with a slash.
            payload: The body to send, as it is.

        Returns:
            The parsed reply, or an empty object when the reply has no body.

        Raises:
            GatewayUntrusted: When the hub's certificate is not the pinned
                one; nothing was sent.
            GatewayRefused: When the hub rejected this client's token.
            GatewayProtocolRefused: When the hub does not speak this
                client's protocol number.
            GatewayRefusedDetail: When the hub refused with another code.
            GatewayUnreachable: On any network error, timeout, other HTTP
                error status, or unparseable reply.
        """
        _, data, _ = self._post(path, payload)
        text = data.decode("utf-8")
        if not text.strip():
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError as error:
            raise GatewayUnreachable(f"hub sent invalid JSON: {error}") from error

    def _post(self, path: str, payload: dict):
        """One POST, its status already judged.

        Args:
            path: Path below the hub URL, starting with a slash.
            payload: The body to send.

        Returns:
            The status code, the response body, and the response headers
            lower-cased.

        Raises:
            GatewayUntrusted: When the peer failed the fingerprint check.
            GatewayRefused: On a 401 or 403.
            GatewayProtocolRefused: On a 409 naming a protocol number the
                hub does not speak.
            GatewayRefusedDetail: On a 409 carrying another code.
            GatewayUnreachable: On any network error or other error status.
        """
        body = json.dumps(payload).encode("utf-8")
        status, data, headers = self._request(
            "POST",
            f"{self._gateway_url}{path}",
            body=body,
            headers={"Content-Type": "application/json"},
        )
        if status in (401, 403):
            raise GatewayRefused(f"hub refused this client's token ({status})")
        if status == 409:
            detail = error_detail(data)
            refusal = refusal_error(
                str(detail.get("code", "") or ""), detail.get("params") or {}
            )
            if refusal is not None:
                raise refusal
        if status >= 400:
            raise GatewayUnreachable(f"hub answered {status} for {path}")
        return status, data, headers

    def _request(self, method: str, url: str, *, body=None, headers=None):
        """One request over a fresh connection.

        Args:
            method: HTTP method.
            url: Absolute URL.
            body: Bytes to send, or None.
            headers: Header dictionary, or None.

        Returns:
            The status code, the response body, and the response headers with
            lower-cased names.

        Raises:
            GatewayUntrusted: When the peer failed the fingerprint check.
            GatewayUnreachable: On any network error.
        """
        parts = urllib.parse.urlsplit(url)
        connection = self._connection(parts)
        target = parts.path or "/"
        if parts.query:
            target += "?" + parts.query
        try:
            connection.request(method, target, body=body, headers=headers or {})
            response = connection.getresponse()
            named = {name.lower(): value for name, value in response.getheaders()}
            return response.status, response.read(), named
        except GatewayUntrusted:
            raise
        except (OSError, http.client.HTTPException) as error:
            raise GatewayUnreachable(f"cannot reach hub: {error}") from error
        finally:
            connection.close()

    def _connection(self, parts):
        """A connection for one request, pinned when the scheme is TLS.

        Args:
            parts: The split URL.

        Returns:
            The unopened connection.

        Raises:
            GatewayUntrusted: When the URL is ``https`` and no fingerprint is
                pinned.
        """
        host = parts.hostname or ""
        if parts.scheme == "https":
            if not self._fingerprint:
                raise GatewayUntrusted(
                    f"no certificate fingerprint is pinned for {host}"
                )
            return _PinnedHttpsConnection(
                host,
                parts.port or 443,
                fingerprint=self._fingerprint,
                timeout=CLIENT_REQUEST_TIMEOUT_S,
            )
        return http.client.HTTPConnection(
            host, parts.port or 80, timeout=CLIENT_REQUEST_TIMEOUT_S
        )


class _PinnedHttpsConnection(http.client.HTTPSConnection):
    """An HTTPS connection that trusts one certificate and nothing else."""

    def __init__(self, host: str, port: int, *, fingerprint: str, timeout: float):
        """
        Args:
            host: The hub's address.
            port: The agent port.
            fingerprint: SHA-256 hex the peer certificate must digest to.
            timeout: Socket timeout in seconds.
        """
        super().__init__(host, port, timeout=timeout, context=_pinned_context())
        self._fingerprint = fingerprint

    def connect(self):
        """Handshake, then keep the socket only if the peer is the pinned one.

        Raises:
            GatewayUntrusted: On a mismatch; the connection is closed before
                any request bytes are written.
        """
        super().connect()
        certificate = self.sock.getpeercert(binary_form=True) or b""
        digest = hashlib.sha256(certificate).hexdigest()
        if digest != self._fingerprint:
            self.close()
            raise GatewayUntrusted(
                "the hub's certificate does not match the pinned fingerprint"
            )
