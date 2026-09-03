"""Talking to the gateway with the standard library, pinned over TLS.

The agent polls rather than holding a socket open: the standard library has no
websocket client, and polling survives the gateway restarting, the device
sleeping, and a NAT in between without any reconnect logic of its own.

An ``https`` gateway is verified by fingerprint alone: the handshake runs with
chain and hostname checks off, and the peer certificate's SHA-256 digest must
match the pinned value before any request bytes leave this machine.
"""

import hashlib
import http.client
import json
import ssl
import urllib.parse

from neutrino_agent.constants import AGENT_REQUEST_TIMEOUT_S


class GatewayUnreachable(RuntimeError):
    """Raised when the gateway cannot be reached or answers with an error."""


class GatewayRefused(RuntimeError):
    """Raised when the gateway answered but rejected this machine's token.

    Not a network problem: the hub deliberately no longer knows this device —
    it was forgotten on the panel, or the hub was reset — and retrying with
    the same token can never succeed.
    """


class GatewayUntrusted(RuntimeError):
    """Raised when the peer's certificate does not match the pinned fingerprint.

    Neither a refusal nor a network problem: whatever answered at that address
    is not the hub this machine pinned. Nothing was sent — the check runs on
    the peer certificate before any request bytes leave the machine.
    """


class GatewayHttpChannel:
    """Posts JSON to the gateway and parses its replies."""

    def __init__(self, *, gateway_url: str, token: str, fingerprint: str = ""):
        """
        Args:
            gateway_url: Base URL of the gateway's agent channel, without a
                trailing slash.
            token: Per-device token issued when the agent enrolled.
            fingerprint: SHA-256 hex of the gateway certificate's DER form.
                Required for an ``https`` URL; ignored for plain ``http``.
        """
        self._gateway_url = gateway_url.rstrip("/")
        self._token = token
        self._fingerprint = fingerprint.strip().lower()

    def post(self, path: str, payload: dict) -> dict:
        """Post a JSON body and return the JSON reply.

        The token is added to every payload, so callers never repeat it.

        Args:
            path: Path below the gateway URL, starting with a slash.
            payload: The body to send.

        Returns:
            The parsed reply, or an empty object when the reply has no body.

        Raises:
            GatewayUntrusted: When the gateway's certificate is not the pinned
                one; nothing was sent.
            GatewayRefused: When the gateway rejected this machine's token.
            GatewayUnreachable: On any network error, timeout, other HTTP
                error status, or unparseable reply.
        """
        body = json.dumps({**payload, "token": self._token}).encode("utf-8")
        status, data = self._request(
            "POST",
            f"{self._gateway_url}{path}",
            body=body,
            headers={"Content-Type": "application/json"},
        )
        if status in (401, 403):
            raise GatewayRefused(f"gateway refused this machine's token ({status})")
        if status >= 400:
            raise GatewayUnreachable(f"gateway answered {status} for {path}")
        text = data.decode("utf-8")
        if not text.strip():
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError as error:
            raise GatewayUnreachable(f"gateway sent invalid JSON: {error}") from error

    def download(self, url: str, destination: str) -> None:
        """Fetch a file to disk, used for agent self-updates.

        Args:
            url: Absolute URL to fetch, pinned the same way when ``https``.
            destination: Local path to write.

        Raises:
            GatewayUntrusted: When the peer's certificate is not the pinned
                one.
            GatewayUnreachable: If the download fails.
        """
        status, data = self._request("GET", url)
        if status >= 400:
            raise GatewayUnreachable(
                f"cannot download {url}: gateway answered {status}"
            )
        try:
            with open(destination, "wb") as target:
                target.write(data)
        except OSError as error:
            raise GatewayUnreachable(f"cannot download {url}: {error}") from error

    def _request(self, method: str, url: str, *, body=None, headers=None):
        """One request over a fresh connection.

        Args:
            method: HTTP method.
            url: Absolute URL.
            body: Bytes to send, or None.
            headers: Header dictionary, or None.

        Returns:
            The status code and the response body.

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
            return response.status, response.read()
        except (OSError, http.client.HTTPException) as error:
            raise GatewayUnreachable(f"cannot reach gateway: {error}") from error
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
            host: The gateway's address.
            port: The agent channel's port.
            fingerprint: SHA-256 hex the peer certificate must digest to.
            timeout: Socket timeout in seconds.
        """
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        super().__init__(host, port, timeout=timeout, context=context)
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
                "the gateway's certificate does not match the pinned fingerprint"
            )
