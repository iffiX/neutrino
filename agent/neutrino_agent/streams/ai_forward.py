"""The AI gateway forward: how the machine's AI tools reach the hub's gateway.

The gateway answers on the hub's loopback alone, so while the state's
``ai_tools`` section is on and its ``is_forwarded`` is true, which the hub
sends false on its own machine alone, the agent listens on
``127.0.0.1:8317``, the endpoint the switch writes into each tool, and opens
``connect {id: ai}`` to the hub for each connection it accepts. Bytes go
both ways under credit; end of file on either side ends the stream and the
connection, with no half-close. While the agent has no channel to the hub
the listener accepts nothing and stays bound, and the connections waiting in
its queue are served once the channel is back. The forward adds no key and
reads none.

Not pure: listens on a socket and opens streams.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import socket
import threading
import time

from neutrino_agent.constants import (
    AGENT_AI_ENTRY_ID,
    AGENT_AI_FORWARD_HOST,
    AGENT_AI_FORWARD_POLL_S,
    AGENT_AI_FORWARD_PORT,
    AGENT_WS_CHUNK_BYTES,
    AGENT_WS_STREAM_CREDIT_BYTES,
)
from neutrino_agent.exceptions import GatewayUnreachable, StreamClosed
from neutrino_agent.streams import STREAM_KIND_CONNECT


def is_forward_wanted(document: dict) -> bool:
    """Whether a state asks for the forward.

    Args:
        document: The state, ``{ai_tools, ...}``.

    Returns:
        True while its ``ai_tools`` section is on and its ``is_forwarded``
        is true.
    """
    section = document.get("ai_tools")
    if not isinstance(section, dict):
        return False
    return section.get("is_enabled") is True and section.get("is_forwarded") is True


def _close_socket(connection: socket.socket) -> None:
    """Close a socket at once, waking any thread blocked on it."""
    with contextlib.suppress(OSError):
        connection.shutdown(socket.SHUT_RDWR)
    with contextlib.suppress(OSError):
        connection.close()


class AiGatewayForward:
    """The loopback listener whose every connection is one ``connect`` stream."""

    def __init__(
        self,
        *,
        open_stream,
        is_online,
        log=print,
        port: int = AGENT_AI_FORWARD_PORT,
        poll_s: float = AGENT_AI_FORWARD_POLL_S,
    ):
        """
        Args:
            open_stream: Called with ``(kind, **args)`` to open a stream to
                the hub; returns its channel and raises
                :class:`GatewayUnreachable` with no socket.
            is_online: Says whether the agent has a live socket to the hub.
            log: Callable used for progress messages.
            port: The loopback port to listen on.
            poll_s: How long a forward with no channel waits before it
                looks again.
        """
        self._open_stream = open_stream
        self._is_online = is_online
        self._log = log
        self._port = port
        self._poll_s = poll_s
        self._lock = threading.Lock()
        self._is_wanted = False
        self._listener: "socket.socket | None" = None
        self._connections: set = set()
        # The failure last written to the log; the same one is not written again.
        self._noted = ""

    @property
    def local_port(self) -> int:
        """The port the forward listens on, 0 while it listens on none."""
        with self._lock:
            listener = self._listener
        return listener.getsockname()[1] if listener is not None else 0

    def take(self, document) -> None:
        """Listen while a state asks for the forward, and close otherwise.

        Args:
            document: The state; anything but a dict closes the forward.
        """
        is_wanted = isinstance(document, dict) and is_forward_wanted(document)
        with self._lock:
            self._is_wanted = is_wanted
        if is_wanted:
            self.ensure()
        else:
            self.stop()

    def ensure(self) -> None:
        """Listen when the last state asked for the forward and it listens on
        nothing; a port that cannot be had is one line in the log."""
        with self._lock:
            if not self._is_wanted or self._listener is not None:
                return
            try:
                listener = socket.create_server((AGENT_AI_FORWARD_HOST, self._port))
            except OSError as error:
                self._note_locked(
                    f"AI gateway forward cannot listen on "
                    f"{AGENT_AI_FORWARD_HOST}:{self._port}: {error}"
                )
                return
            self._noted = ""
            self._listener = listener
        threading.Thread(
            target=self._accept,
            args=(listener,),
            name="agent_ai_forward_accept",
            daemon=True,
        ).start()
        port = listener.getsockname()[1]
        self._log(f"AI gateway forward listening on {AGENT_AI_FORWARD_HOST}:{port}")

    def stop(self) -> None:
        """Stop listening and close every connection, which ends its stream."""
        with self._lock:
            self._is_wanted = False
            listener = self._listener
            self._listener = None
            connections = list(self._connections)
            self._connections.clear()
        for connection in connections:
            _close_socket(connection)
        if listener is not None:
            _close_socket(listener)
            self._log("AI gateway forward closed")

    def _accept(self, listener: socket.socket) -> None:
        """Accept while there is a channel, until the listener is closed."""
        while self._wait_online(listener):
            try:
                connection, _address = listener.accept()
            except OSError:
                return
            if not self._is_current(listener):
                _close_socket(connection)
                return
            threading.Thread(
                target=self._serve,
                args=(listener, connection),
                name="agent_ai_forward_connection",
                daemon=True,
            ).start()

    def _is_current(self, listener: socket.socket) -> bool:
        """Whether a listener is still the forward's own."""
        with self._lock:
            return self._listener is listener

    def _wait_online(self, listener: socket.socket) -> bool:
        """Wait for a socket to the hub; False once the listener is closed."""
        while self._is_current(listener):
            if self._is_online():
                return True
            time.sleep(self._poll_s)
        return False

    def _serve(self, listener: socket.socket, connection: socket.socket) -> None:
        """Carry one accepted connection over a ``connect`` stream of its own."""
        if not self._wait_online(listener):
            _close_socket(connection)
            return
        try:
            channel = self._open_stream(STREAM_KIND_CONNECT, id=AGENT_AI_ENTRY_ID)
        except GatewayUnreachable as error:
            self._note(f"AI gateway forward opened no stream: {error}")
            _close_socket(connection)
            return
        with self._lock:
            is_current = self._listener is listener
            if is_current:
                self._connections.add(connection)
        if not is_current:
            with contextlib.suppress(GatewayUnreachable):
                channel.close()
            _close_socket(connection)
            return
        try:
            code, params = self._relay(connection, channel)
        finally:
            with self._lock:
                self._connections.discard(connection)
        if code:
            self._note(f"the hub refused the AI gateway forward: {code} {params}")
        else:
            with self._lock:
                self._noted = ""

    def _relay(self, connection: socket.socket, channel) -> tuple:
        """Move bytes both ways until either end ends; the hub's ``(code, params)``."""
        is_done = threading.Event()
        upward = threading.Thread(
            target=self._upward,
            args=(connection, channel, is_done),
            name=f"agent_ai_forward_up_{channel.id}",
            daemon=True,
        )
        try:
            channel.offer_credit(AGENT_WS_STREAM_CREDIT_BYTES)
        except GatewayUnreachable:
            _close_socket(connection)
            return "", {}
        upward.start()
        closed = self._downward(channel, connection, is_done)
        is_done.set()
        _close_socket(connection)
        with contextlib.suppress(GatewayUnreachable):
            channel.close()
        upward.join(timeout=self._poll_s * 4)
        return closed

    def _upward(self, connection: socket.socket, channel, is_done) -> None:
        """Send what the connection reads up the stream; its end closes the stream."""
        while not is_done.is_set():
            try:
                data = connection.recv(AGENT_WS_CHUNK_BYTES)
            except OSError:
                break
            if not data:
                break
            try:
                channel.send_bytes(data)
            except (StreamClosed, GatewayUnreachable):
                break
        with contextlib.suppress(GatewayUnreachable):
            channel.close()
        is_done.set()

    def _downward(self, channel, connection: socket.socket, is_done) -> tuple:
        """Write the hub's bytes into the connection, granting credit as they go."""
        while not is_done.is_set():
            item = channel.recv(timeout=self._poll_s)
            if item is None:
                continue
            if item[0] == "close":
                return str(item[1] or ""), dict(item[2] or {})
            if item[0] != "data":
                continue
            try:
                connection.sendall(item[1])
                channel.offer_credit(len(item[1]))
            except (OSError, GatewayUnreachable):
                break
        return "", {}

    def _note(self, line: str) -> None:
        """Write a failure to the log unless it is the one written last."""
        with self._lock:
            self._note_locked(line)

    def _note_locked(self, line: str) -> None:
        """:meth:`_note` for a caller that holds the lock."""
        if line != self._noted:
            self._noted = line
            self._log(line)
