"""Talking to the gateway over plain HTTP with urllib.

The agent polls rather than holding a socket open: the standard library has no
websocket client, and polling survives the gateway restarting, the device
sleeping, and a NAT in between without any reconnect logic of its own.
"""

import json
import urllib.error
import urllib.request

from neutrino_agent.constants import AGENT_REQUEST_TIMEOUT_S


class GatewayUnreachable(RuntimeError):
    """Raised when the gateway cannot be reached or answers with an error."""


class GatewayHttpChannel:
    """Posts JSON to the gateway and parses its replies."""

    def __init__(self, *, gateway_url: str, token: str):
        """
        Args:
            gateway_url: Base URL of the gateway panel, without a trailing
                slash.
            token: Per-device token issued when the agent was installed.
        """
        self._gateway_url = gateway_url.rstrip("/")
        self._token = token

    def post(self, path: str, payload: dict) -> dict:
        """Post a JSON body and return the JSON reply.

        The token is added to every payload, so callers never repeat it.

        Args:
            path: Path below the gateway URL, starting with a slash.
            payload: The body to send.

        Returns:
            The parsed reply, or an empty object when the reply has no body.

        Raises:
            GatewayUnreachable: On any network error, timeout, HTTP error
                status, or unparseable reply.
        """
        body = json.dumps({**payload, "token": self._token}).encode("utf-8")
        request = urllib.request.Request(
            f"{self._gateway_url}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request, timeout=AGENT_REQUEST_TIMEOUT_S
            ) as response:
                text = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            raise GatewayUnreachable(
                f"gateway answered {error.code} for {path}"
            ) from error
        except (urllib.error.URLError, OSError) as error:
            raise GatewayUnreachable(f"cannot reach gateway: {error}") from error
        if not text.strip():
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError as error:
            raise GatewayUnreachable(f"gateway sent invalid JSON: {error}") from error

    def download(self, url: str, destination: str) -> None:
        """Fetch a file to disk, used for agent self-updates.

        Args:
            url: Absolute URL to fetch.
            destination: Local path to write.

        Raises:
            GatewayUnreachable: If the download fails.
        """
        try:
            with urllib.request.urlopen(url, timeout=AGENT_REQUEST_TIMEOUT_S) as source:
                with open(destination, "wb") as target:
                    target.write(source.read())
        except (urllib.error.URLError, OSError) as error:
            raise GatewayUnreachable(f"cannot download {url}: {error}") from error
