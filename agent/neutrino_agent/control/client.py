"""Talking to the running agent over its control socket.

The CLI connects as whoever ran it; the kernel reports that identity to the
server, so no credential travels in the request.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import http.client
import json
import socket

from neutrino_agent.constants import AGENT_CONTROL_REQUEST_TIMEOUT_S


def request(
    *,
    socket_path: str,
    method: str,
    path: str,
    body: "dict | None" = None,
    timeout_s: int = AGENT_CONTROL_REQUEST_TIMEOUT_S,
) -> "tuple[int, dict]":
    """One HTTP request over the control socket.

    Args:
        socket_path: The socket the agent serves on.
        method: The HTTP method.
        path: The request path.
        body: Sent as JSON when given.
        timeout_s: How long to wait.

    Returns:
        The status code and the decoded JSON reply.

    Raises:
        OSError: When nothing answers on the socket.
        ValueError: When the reply is not JSON.
    """
    connection = _ControlSocketHttpConnection(socket_path, timeout_s=timeout_s)
    try:
        payload = None
        headers = {}
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        connection.request(method, path, body=payload, headers=headers)
        reply = connection.getresponse()
        decoded = json.loads(reply.read().decode("utf-8"))
    finally:
        connection.close()
    if not isinstance(decoded, dict):
        raise ValueError("the control socket answered with no object")
    return reply.status, decoded


class _ControlSocketHttpConnection(http.client.HTTPConnection):
    """An HTTP connection over a Unix socket."""

    def __init__(self, socket_path: str, *, timeout_s: int):
        """
        Args:
            socket_path: The socket to connect to.
            timeout_s: How long to wait.
        """
        super().__init__("localhost", timeout=timeout_s)
        self._socket_path = socket_path

    def connect(self) -> None:
        """Connect to the socket path instead of a host and port."""
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self._socket_path)
