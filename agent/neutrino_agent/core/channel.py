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


def _error_detail(data: bytes) -> dict:
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


class GatewayUnreachable(RuntimeError):
    """Raised when the gateway cannot be reached or answers with an error."""


class GatewayRefused(RuntimeError):
    """Raised when the gateway answered but rejected this machine's token.

    Not a network problem: the hub deliberately no longer knows this device —
    it was forgotten on the panel, or the hub was reset — and retrying with
    the same token can never succeed.
    """


class GatewayVersionRefused(RuntimeError):
    """Raised when the gateway turned this agent away as newer than itself.

    A definitive rejection, not a network problem: the hub answered and said
    no, and keeps saying no until it is updated to this agent's version.
    """

    def __init__(self, *, hub_version: str, agent_version: str):
        """
        Args:
            hub_version: What the hub reported itself as.
            agent_version: What this agent reported itself as.
        """
        super().__init__(
            f"this agent ({agent_version}) is newer than the hub "
            f"({hub_version}); update the hub first"
        )
        self.hub_version = hub_version
        self.agent_version = agent_version


class GatewayUntrusted(RuntimeError):
    """Raised when the peer's certificate does not match the pinned fingerprint.

    Whatever answered at that address is not the hub this machine pinned — a
    hub reset or reinstalled, or an impersonator. Nothing was sent: the check
    runs on the peer certificate before any request bytes leave the machine.
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
            GatewayVersionRefused: When the gateway turned this agent away as
                newer than itself.
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
            raise GatewayUnreachable(f"gateway sent invalid JSON: {error}") from error

    def post_download(self, path: str, payload: dict, destination: str) -> str:
        """Post a JSON body and write the bytes that come back to disk.

        Args:
            path: Path below the gateway URL, starting with a slash.
            payload: The body to send; the token is added.
            destination: Local file to write.

        Returns:
            The reply's ``X-Checksum-Sha256`` value, empty when none came.

        Raises:
            GatewayUntrusted: When the gateway's certificate is not the pinned
                one; nothing was sent.
            GatewayRefused: When the gateway rejected this machine's token.
            GatewayUnreachable: On any network error, error status, or a
                destination that cannot be written.
        """
        _, data, headers = self._post(path, payload)
        try:
            with open(destination, "wb") as target:
                target.write(data)
        except OSError as error:
            raise GatewayUnreachable(f"cannot save {path}: {error}") from error
        return headers.get("x-checksum-sha256", "")

    def _post(self, path: str, payload: dict):
        """One POST with the token added, its status already judged.

        Args:
            path: Path below the gateway URL, starting with a slash.
            payload: The body to send.

        Returns:
            The status code, the response body, and the response headers
            lower-cased.

        Raises:
            GatewayUntrusted: When the peer failed the fingerprint check.
            GatewayRefused: On a 401 or 403.
            GatewayVersionRefused: On a 409 naming this agent as too new.
            GatewayUnreachable: On any network error or other error status.
        """
        body = json.dumps({**payload, "token": self._token}).encode("utf-8")
        status, data, headers = self._request(
            "POST",
            f"{self._gateway_url}{path}",
            body=body,
            headers={"Content-Type": "application/json"},
        )
        if status in (401, 403):
            raise GatewayRefused(f"gateway refused this machine's token ({status})")
        if status == 409:
            detail = _error_detail(data)
            params = detail.get("params") or {}
            if detail.get("code") == "agent_newer_than_hub":
                raise GatewayVersionRefused(
                    hub_version=str(params.get("hub_version", "")),
                    agent_version=str(params.get("agent_version", "")),
                )
            if detail.get("code"):
                raise GatewayUnreachable(
                    f"gateway answered 409 ({detail['code']}) for {path}"
                )
        if status >= 400:
            raise GatewayUnreachable(f"gateway answered {status} for {path}")
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
