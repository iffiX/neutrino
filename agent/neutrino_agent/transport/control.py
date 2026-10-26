"""The control connection to the agent's transport, and the streams beside it.

Every local connection opens with one JSON line holding the secret the
transport was started with. The control connection, ``op: control``, then
carries JSON lines both ways: this side's commands, answered by the
transport's line of the same ``id``; the transport's events and the hub's
frames, which go to one dispatching thread in the order they came; and the
transport's questions, each answered on a thread of its own so a slow event
never holds one back. A stream the hub opened is taken with an ``attach``
connection, and one this side opens with an ``open`` connection, each
carrying records after its first line.

Not pure: holds connections and threads.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import itertools
import json
import queue
import threading

from neutrino_agent.exceptions import GatewayUnreachable
from neutrino_agent.streams.channel import StreamChannel
from neutrino_agent.transport.constants import (
    TRANSPORT_CODE_CONTROL_UNAVAILABLE,
    TRANSPORT_COMMAND_TIMEOUT_S,
    TRANSPORT_LINE_BYTES_MAX,
    TRANSPORT_OP_ATTACH,
    TRANSPORT_OP_CONTROL,
    TRANSPORT_OP_OPEN,
    TRANSPORT_RECORD_BYTES_MAX,
)
from neutrino_agent.transport.records import RecordReader

# What the dispatching thread is handed once the connection ended.
CLOSED = object()


def encode_line(value: dict) -> bytes:
    """One JSON line's bytes.

    Args:
        value: The object.

    Returns:
        Compact JSON and a newline.
    """
    return json.dumps(value, separators=(",", ":")).encode("utf-8") + b"\n"


class LineReader:
    """Reads JSON lines off a connection, one object at a time."""

    def __init__(self, connection):
        """
        Args:
            connection: What the lines come from, with ``recv(size)``
                returning empty bytes at its end.
        """
        self._connection = connection
        self._buffer = bytearray()

    def read(self) -> "dict | None":
        """The next line's object.

        Returns:
            The object; None at the connection's end or past the line limit.
            A line that is no JSON object is skipped.

        Raises:
            OSError: When the connection fails.
        """
        while True:
            end = self._buffer.find(b"\n")
            if end < 0:
                if len(self._buffer) > TRANSPORT_LINE_BYTES_MAX:
                    return None
                chunk = self._connection.recv(TRANSPORT_RECORD_BYTES_MAX)
                if not chunk:
                    return None
                self._buffer.extend(chunk)
                continue
            line = bytes(self._buffer[:end])
            del self._buffer[: end + 1]
            try:
                value = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                continue
            if isinstance(value, dict):
                return value


class TransportControlClient:
    """The control connection: commands out, events, frames and questions in.

    The callbacks run on threads of this client's own, never on the thread
    that reads the connection, so a callback may send a command and wait
    for its answer.
    """

    def __init__(
        self,
        *,
        connect,
        secret: str,
        on_event,
        on_frame,
        on_question,
        on_closed=None,
        log=print,
        command_timeout_s: float = TRANSPORT_COMMAND_TIMEOUT_S,
    ):
        """
        Args:
            connect: Called with nothing for a new local connection to the
                transport's listener.
            secret: The secret the transport was started with.
            on_event: Called with each event line, ``{event, ...}``.
            on_frame: Called with each frame the hub sent, ``{type, ...}``.
            on_question: Called with each question line, ``{id, question,
                ...}``; returns the answer's fields.
            on_closed: Called once after the connection ended.
            log: Callable used for progress messages.
            command_timeout_s: How long a command waits for its answer by
                default.
        """
        self._connect = connect
        self._secret = secret
        self._on_event = on_event
        self._on_frame = on_frame
        self._on_question = on_question
        self._on_closed = on_closed
        self._log = log
        self._command_timeout_s = command_timeout_s
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._ids = itertools.count(1)
        self._pending: dict = {}
        self._connection = None
        self._is_closed = threading.Event()
        self._inbound: queue.Queue = queue.Queue()

    @property
    def is_open(self) -> bool:
        """Whether the control connection is up."""
        return self._connection is not None and not self._is_closed.is_set()

    def start(self) -> None:
        """Open the control connection and start reading it.

        Raises:
            OSError: When the transport's listener does not answer.
        """
        connection = self._connect()
        try:
            connection.sendall(
                encode_line({"secret": self._secret, "op": TRANSPORT_OP_CONTROL})
            )
        except OSError:
            connection.close()
            raise
        self._connection = connection
        threading.Thread(
            target=self._read_forever,
            args=(connection,),
            name="agent_transport_reader",
            daemon=True,
        ).start()
        threading.Thread(
            target=self._dispatch_forever,
            name="agent_transport_dispatch",
            daemon=True,
        ).start()

    def close(self) -> None:
        """Close the control connection; every command waiting fails."""
        connection = self._connection
        if connection is not None:
            connection.close()

    def command(
        self, name: str, /, *, timeout_s: "float | None" = None, **fields
    ) -> dict:
        """Send one command and wait for its answer.

        Args:
            name: The command, such as ``dial`` or ``forward_start``.
            timeout_s: How long to wait; None takes the client's own.
            **fields: The command's fields, ``name`` among them for a
                ``join``.

        Returns:
            The answer's fields, ``code`` and ``params`` among them when the
            transport refused.

        Raises:
            GatewayUnreachable: When the connection is gone, or no answer
                came in time.
        """
        command_id = str(next(self._ids))
        waiter: dict = {"event": threading.Event()}
        with self._lock:
            if self._is_closed.is_set() or self._connection is None:
                raise GatewayUnreachable("the transport's control connection is closed")
            self._pending[command_id] = waiter
        try:
            self._write({"id": command_id, "command": name, **fields})
            if not waiter["event"].wait(
                self._command_timeout_s if timeout_s is None else timeout_s
            ):
                raise GatewayUnreachable(f"the transport did not answer {name}")
        finally:
            with self._lock:
                self._pending.pop(command_id, None)
        answer = waiter.get("answer")
        if answer is None:
            raise GatewayUnreachable("the transport's control connection closed")
        return {key: value for key, value in answer.items() if key != "id"}

    def send_frame(self, frame: dict, *, is_last: bool = False) -> None:
        """Send one frame of the control stream to the hub.

        Args:
            frame: The frame, ``{type, ...body}``.
            is_last: Whether the transport ends the session once it is written.

        Raises:
            GatewayUnreachable: When the connection is gone.
        """
        line: dict = {"frame": frame}
        if is_last:
            line["is_last"] = True
        self._write(line)

    def attach(self, stream_id: str) -> StreamChannel:
        """Take a stream the hub opened, on a connection of its own.

        Args:
            stream_id: The id the ``stream`` event named.

        Returns:
            The stream's channel, its first line written; the caller writes
            ``accept`` or a refusing close first.

        Raises:
            GatewayUnreachable: When the transport's listener does not answer.
        """
        connection = self._open_connection(
            {"secret": self._secret, "op": TRANSPORT_OP_ATTACH, "stream": stream_id}
        )
        return StreamChannel(connection, stream_id)

    def open_stream(self, open_record: dict) -> StreamChannel:
        """Open a stream to the hub, on a connection of its own.

        Args:
            open_record: The open, ``{kind, ...args}``.

        Returns:
            The stream's channel, reading the hub's records once accepted.
            A stream the hub refused holds its ``close`` as the first item.

        Raises:
            GatewayUnreachable: When the transport's listener does not answer.
        """
        connection = self._open_connection(
            {"secret": self._secret, "op": TRANSPORT_OP_OPEN, "open": open_record}
        )
        reader = RecordReader(connection)
        channel = StreamChannel(connection, reader=reader)
        if channel.take_answer()[0] == "accept":
            channel.start()
        return channel

    def _open_connection(self, first_line: dict):
        try:
            connection = self._connect()
        except OSError as error:
            raise GatewayUnreachable(
                f"the transport does not answer: {error}"
            ) from error
        try:
            connection.sendall(encode_line(first_line))
        except OSError as error:
            connection.close()
            raise GatewayUnreachable(
                f"the transport does not answer: {error}"
            ) from error
        return connection

    def _write(self, line: dict) -> None:
        connection = self._connection
        if connection is None or self._is_closed.is_set():
            raise GatewayUnreachable("the transport's control connection is closed")
        try:
            with self._write_lock:
                connection.sendall(encode_line(line))
        except OSError as error:
            raise GatewayUnreachable(
                f"the transport's control connection failed: {error}"
            ) from error

    def _read_forever(self, connection) -> None:
        reader = LineReader(connection)
        try:
            while True:
                try:
                    line = reader.read()
                except OSError:
                    line = None
                if line is None:
                    return
                self._take(line)
        finally:
            self._is_closed.set()
            with self._lock:
                waiters = list(self._pending.values())
            for waiter in waiters:
                waiter["event"].set()
            connection.close()
            self._inbound.put(CLOSED)

    def _take(self, line: dict) -> None:
        if "question" in line:
            threading.Thread(
                target=self._answer,
                args=(line,),
                name="agent_transport_question",
                daemon=True,
            ).start()
            return
        if "event" in line or "frame" in line:
            self._inbound.put(line)
            return
        line_id = str(line.get("id", ""))
        with self._lock:
            waiter = self._pending.get(line_id)
        if waiter is None:
            self._log(f"transport: an answer to no command, id {line_id!r}")
            return
        waiter["answer"] = line
        waiter["event"].set()

    def _answer(self, question: dict) -> None:
        try:
            answer = dict(self._on_question(question) or {})
        except Exception as error:  # noqa: BLE001 - a question is always answered
            self._log(
                f"transport: could not answer {question.get('question')!r}: {error}"
            )
            answer = {"code": TRANSPORT_CODE_CONTROL_UNAVAILABLE, "params": {}}
        answer["id"] = question.get("id", "")
        with contextlib.suppress(GatewayUnreachable):
            self._write(answer)

    def _dispatch_forever(self) -> None:
        while True:
            line = self._inbound.get()
            if line is CLOSED:
                if self._on_closed is not None:
                    self._on_closed()
                return
            try:
                if "frame" in line:
                    frame = line.get("frame")
                    self._on_frame(frame if isinstance(frame, dict) else {})
                else:
                    self._on_event(line)
            except Exception as error:  # noqa: BLE001 - the dispatcher must survive
                self._log(f"transport: could not handle a line: {error}")
