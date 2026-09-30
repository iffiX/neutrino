"""Talking to the resident over its control socket.

The CLI connects as whoever ran it; the kernel reports that identity to the
server, so no credential travels in the request. A request the resident
answers with 101 keeps its connection, which then carries a terminal's
bytes one way.
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

# The most a status line and its headers may take before the answer is
# judged unreadable.
UPGRADE_HEADER_LIMIT = 64 * 1024


def upgrade(
    *,
    socket_path: str,
    path: str,
    body: dict,
    timeout_s: int = CLIENT_CONTROL_REQUEST_TIMEOUT_S,
) -> "tuple[int, dict, ControlUpgrade | None]":
    """One POST that the resident may answer by keeping the connection.

    Args:
        socket_path: The socket the resident serves on.
        path: The request path.
        body: Sent as JSON.
        timeout_s: How long connecting may take; a kept connection then
            waits as long as its terminal lasts.

    Returns:
        ``(101, {"terminal_id"}, connection)`` when the resident kept it;
        ``(status, reply, None)`` for any other answer.

    Raises:
        OSError: When nothing answers on the socket.
        ValueError: When the answer is unreadable.
    """
    raw = _open_raw(socket_path, timeout_s)
    reader = raw.makefile("rb")
    payload = json.dumps(body).encode("utf-8")
    try:
        raw.sendall(
            f"POST {path} HTTP/1.1\r\nHost: localhost\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii") + payload
        )
        status, headers = _read_head(reader)
        if status == 101:
            if hasattr(raw, "settimeout"):
                raw.settimeout(None)
            terminal_id = headers.get("x-neutrino-terminal", "")
            return 101, {"terminal_id": terminal_id}, ControlUpgrade(raw, reader)
        length = int(headers.get("content-length", "0") or 0)
        decoded = json.loads(reader.read(length).decode("utf-8") or "{}")
    except (OSError, ValueError):
        reader.close()
        raw.close()
        raise
    reader.close()
    raw.close()
    if not isinstance(decoded, dict):
        raise ValueError("the control socket answered with no object")
    return status, decoded, None


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


def _open_raw(socket_path: str, timeout_s: int):
    """A connected socket or pipe to the resident.

    Raises:
        OSError: When nothing answers.
    """
    if socket_path.startswith(CLIENT_CONTROL_PIPE_PREFIX):
        from neutrino_client.platforms.windows_pipe import open_pipe_connection

        return open_pipe_connection(socket_path)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout_s)
    try:
        sock.connect(socket_path)
    except OSError:
        sock.close()
        raise
    return sock


def _read_head(reader) -> "tuple[int, dict]":
    """The status and the lower-cased headers of one answer.

    Raises:
        ValueError: When the status line or a header cannot be read.
    """
    line = reader.readline(UPGRADE_HEADER_LIMIT).decode("latin-1")
    parts = line.split(" ", 2)
    if len(parts) < 2 or not parts[1].isdigit():
        raise ValueError("the control socket answered with no status line")
    headers = {}
    taken = len(line)
    while True:
        header = reader.readline(UPGRADE_HEADER_LIMIT).decode("latin-1")
        taken += len(header)
        if taken > UPGRADE_HEADER_LIMIT:
            raise ValueError("the control socket answered with too much head")
        if header in ("\r\n", "\n", ""):
            break
        name, _, value = header.partition(":")
        headers[name.strip().lower()] = value.strip()
    return int(parts[1]), headers


class ControlUpgrade:
    """One connection the resident kept, carrying a terminal's bytes."""

    def __init__(self, raw, reader):
        """
        Args:
            raw: The socket or pipe connection.
            reader: The buffered reader over it that read the answer's head.
        """
        self._raw = raw
        self._reader = reader

    def read(self, size: int) -> bytes:
        """The next bytes the resident sent, empty at the end.

        Args:
            size: The most to take.

        Returns:
            The bytes.
        """
        try:
            return self._reader.read1(size)
        except OSError:
            return b""

    def send(self, data: bytes) -> None:
        """Send bytes to the resident.

        Args:
            data: The bytes.

        Raises:
            OSError: When the connection is gone.
        """
        self._raw.sendall(data)

    def close(self) -> None:
        """End the connection. Idempotent."""
        try:
            self._reader.close()
        finally:
            self._raw.close()
