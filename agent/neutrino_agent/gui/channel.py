"""The window's control connection.

On POSIX the window process inherits one already-connected socket from the
``nagent gui`` invocation; the kernel read that connection's peer identity
when it was opened, so every request on it answers in the opener's scope,
and the window process itself needs no privilege. On Windows the elevated
invocation hosts the window and opens the control pipe per request, whose
identity the kernel reads each time.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import http.client
import json
import threading

from neutrino_agent.constants import AGENT_CONTROL_REQUEST_TIMEOUT_S
from neutrino_agent.control import client


class GuiFdChannel:
    """One inherited control connection, serialized for the bridge."""

    def __init__(self, *, sock):
        """
        Args:
            sock: The connected control socket the invocation handed over.
        """
        sock.settimeout(AGENT_CONTROL_REQUEST_TIMEOUT_S)
        self._connection = _GuiFdHttpConnection(sock)
        self._lock = threading.Lock()
        self._is_closed = False

    def request(
        self, *, method: str, path: str, body: "dict | None" = None
    ) -> "tuple[int, dict]":
        """One request over the inherited connection.

        Args:
            method: The HTTP method.
            path: The request path.
            body: Sent as JSON when given.

        Returns:
            The status code and the decoded JSON reply.

        Raises:
            OSError: When the connection is closed or stops answering.
            ValueError: When the reply is not JSON.
        """
        with self._lock:
            if self._is_closed:
                raise OSError("the control connection is closed")
            payload = None
            headers = {}
            if body is not None:
                payload = json.dumps(body).encode("utf-8")
                headers["Content-Type"] = "application/json"
            try:
                self._connection.request(method, path, body=payload, headers=headers)
                reply = self._connection.getresponse()
                decoded = json.loads(reply.read().decode("utf-8"))
            except (OSError, http.client.HTTPException, ValueError):
                self._is_closed = True
                self._connection.close()
                raise OSError("the control connection stopped answering")
        if not isinstance(decoded, dict):
            raise ValueError("the control socket answered with no object")
        return reply.status, decoded


class GuiPipeChannel:
    """The Windows channel: the control pipe, opened per request."""

    def __init__(self, *, pipe_name: str):
        """
        Args:
            pipe_name: The agent's control pipe.
        """
        self._pipe_name = pipe_name

    def request(
        self, *, method: str, path: str, body: "dict | None" = None
    ) -> "tuple[int, dict]":
        """One request over a fresh pipe connection.

        Args:
            method: The HTTP method.
            path: The request path.
            body: Sent as JSON when given.

        Returns:
            The status code and the decoded JSON reply.

        Raises:
            OSError: When nothing answers on the pipe.
            ValueError: When the reply is not JSON.
        """
        return client.request(
            socket_path=self._pipe_name, method=method, path=path, body=body
        )


class _GuiFdHttpConnection(http.client.HTTPConnection):
    """An HTTP connection over a socket somebody else already connected."""

    def __init__(self, sock):
        """
        Args:
            sock: The connected socket.
        """
        super().__init__("localhost", timeout=AGENT_CONTROL_REQUEST_TIMEOUT_S)
        self._connected_sock = sock

    def connect(self) -> None:
        """Reuse the inherited connection instead of dialing anywhere."""
        self.sock = self._connected_sock
