"""Talking to the resident over its control socket.

The CLI connects as whoever ran it; the kernel reports that identity to the
server, so no credential travels in the request.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import http.client
import json
import socket

from neutrino_client.constants import (
    CLIENT_CONTROL_PIPE_PREFIX,
    CLIENT_CONTROL_REQUEST_TIMEOUT_S,
)


def request(
    *,
    socket_path: str,
    method: str,
    path: str,
    body: "dict | None" = None,
    timeout_s: int = CLIENT_CONTROL_REQUEST_TIMEOUT_S,
) -> "tuple[int, dict]":
    """One HTTP request over the control socket.

    Args:
        socket_path: The socket the resident serves on.
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
    if socket_path.startswith(CLIENT_CONTROL_PIPE_PREFIX):
        connection = _ControlPipeHttpConnection(socket_path, timeout_s=timeout_s)
    else:
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


class _ControlPipeHttpConnection(http.client.HTTPConnection):
    """An HTTP connection over a Windows named pipe."""

    def __init__(self, pipe_name: str, *, timeout_s: int):
        """
        Args:
            pipe_name: The pipe to connect to.
            timeout_s: How long to wait; a blocking pipe carries no deadline,
                so this is accepted for shape.
        """
        super().__init__("localhost", timeout=timeout_s)
        self._pipe_name = pipe_name

    def connect(self) -> None:
        """Open the pipe instead of a host and port."""
        from neutrino_client.platforms.windows_pipe import open_pipe_connection

        self.sock = open_pipe_connection(self._pipe_name)
