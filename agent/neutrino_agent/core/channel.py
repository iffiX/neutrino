"""Talking to the hub with the standard library, pinned over TLS.

The HTTP client serves joining and leaving; the one live socket in
``ws_client`` connects the same way. An ``https`` hub is verified by
fingerprint alone: the handshake runs with chain and hostname checks off,
and the peer certificate's SHA-256 digest must match the pinned value before
any request bytes leave this machine.
"""

import hashlib
import http.client
import json
import socket
import ssl
import urllib.parse

from neutrino_agent.constants import (
    AGENT_REQUEST_TIMEOUT_S,
    CHANNEL_JOIN_PATH,
    CHANNEL_LEAVE_PATH,
)
from neutrino_agent.exceptions import (
    GatewayRefusedDetail,
    GatewayUnreachable,
    GatewayUntrusted,
)


def pinned_socket(
    host: str, port: int, fingerprint: str, *, timeout: float = AGENT_REQUEST_TIMEOUT_S
) -> ssl.SSLSocket:
    """A TLS connection that trusts one certificate and nothing else.

    Args:
        host: The hub's address.
        port: The port to connect to.
        fingerprint: SHA-256 hex the peer certificate must digest to.
        timeout: Socket timeout in seconds.

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
    raw = socket.create_connection((host, port), timeout=timeout)
    try:
        wrapped = _pinned_context().wrap_socket(raw, server_hostname=host)
    except OSError:
        raw.close()
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


def _params(detail: dict) -> dict:
    """The ``params`` of a refusal's detail, an empty object when absent."""
    params = detail.get("params")
    return dict(params) if isinstance(params, dict) else {}


def _pinned_context() -> ssl.SSLContext:
    """A client context that checks nothing itself; the pin does the judging."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


class BindingHttpClient:
    """Joins and leaves over HTTP; everything else rides the socket."""

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

    def join(self, payload: dict) -> dict:
        """Spend a ticket for a binding.

        Args:
            payload: ``{ticket, role, protocol, machine_id, name, software,
                platform}``.

        Returns:
            The hub's ``{id, token}``.

        Raises:
            GatewayUntrusted: When the hub's certificate is not the pinned
                one; nothing was sent.
            GatewayRefusedDetail: When the hub refused with a code, such as
                ``ticket_spent`` or ``protocol_too_new``.
            GatewayUnreachable: On any network error, timeout, an error
                status with no code, or an unreadable reply.
        """
        return self._post_json(CHANNEL_JOIN_PATH, payload)

    def leave(self, binding_id: str, token: str) -> None:
        """Give a binding back.

        Args:
            binding_id: The binding's id.
            token: Its token.

        Raises:
            GatewayUntrusted: When the hub's certificate is not the pinned
                one; nothing was sent.
            GatewayRefusedDetail: When the hub refused with a code.
            GatewayUnreachable: On any network error, timeout, an error
                status with no code, or an unreadable reply.
        """
        self._post_json(CHANNEL_LEAVE_PATH, {"id": binding_id, "token": token})

    def _post_json(self, path: str, payload: dict) -> dict:
        """One POST whose reply is a JSON object, or empty."""
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
            payload: The body to send, as it is.

        Returns:
            The status code, the response body, and the response headers
            lower-cased.

        Raises:
            GatewayUntrusted: When the peer failed the fingerprint check.
            GatewayRefusedDetail: On an error status whose ``detail`` names
                a code.
            GatewayUnreachable: On any network error or other error status.
        """
        body = json.dumps(payload).encode("utf-8")
        status, data, headers = self._request(
            "POST",
            f"{self._gateway_url}{path}",
            body=body,
            headers={"Content-Type": "application/json"},
        )
        if status >= 400:
            detail = error_detail(data)
            code = str(detail.get("code", "") or "")
            if code:
                raise GatewayRefusedDetail(code=code, params=_params(detail))
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
                pinned; connecting unverified would hand the token to whoever
                answers.
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
                timeout=AGENT_REQUEST_TIMEOUT_S,
            )
        return http.client.HTTPConnection(
            host, parts.port or 80, timeout=AGENT_REQUEST_TIMEOUT_S
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
        self.sock = pinned_socket(
            self.host, self.port, self._fingerprint, timeout=self.timeout
        )
