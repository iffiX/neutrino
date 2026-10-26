"""The hub's end of the local channel to its transport.

The transport listens on a Unix socket, a named pipe on Windows, and the
hub's Python connects. One control connection carries the transport's
questions, the Python's commands and the events and frames of every
session as JSON lines; every stream the Python takes or opens is one more
connection, ``attach`` for a stream a peer opened and ``open`` for one the
hub opens (protocol.md, "The local channel"). Every connection opens with
one line holding the secret the transport received at its start.

A transport that is not there yet, or that restarted, is dialled again
after a pause; the sessions it held ended with it, and the handler hears
``session_open`` for each live one on a new control connection. A question
nobody answers in time is the transport's own ``control_unavailable``, so
the Python answers each as soon as it can and never waits on a frame to do
it.

Not pure: holds sockets.
"""

import asyncio
import json
import logging
import secrets
import sys

from neutrino_hub.exceptions import AgentOfflineError, StreamRefusedError
from neutrino_hub.modules.channel.constants import (
    CHANNEL_CODE_CONTROL_UNAVAILABLE,
    CHANNEL_CONTROL_COMMAND_TIMEOUT_S,
    CHANNEL_CONTROL_LINE_BYTES_MAX,
    CHANNEL_CONTROL_REDIAL_MAX_S,
    CHANNEL_CONTROL_REDIAL_MIN_S,
    CHANNEL_EVENT_SESSION_END,
    CHANNEL_EVENT_SESSION_OPEN,
    CHANNEL_EVENT_STREAM,
    CHANNEL_FRAME_IS_LAST,
    CHANNEL_LOCAL_OP_ATTACH,
    CHANNEL_LOCAL_OP_CONTROL,
    CHANNEL_LOCAL_OP_OPEN,
    CHANNEL_RECORD_OPEN,
)
from neutrino_hub.modules.channel.streams import ChannelStream, encode_json_record

LOGGER = logging.getLogger(__name__)


async def open_local_connection(address: str) -> tuple:
    """Connect to the transport's listener.

    Args:
        address: The socket's path, or the pipe's name on Windows.

    Returns:
        ``(reader, writer)``.

    Raises:
        OSError: When nothing listens there.
    """
    if sys.platform == "win32":
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader(limit=CHANNEL_CONTROL_LINE_BYTES_MAX)
        protocol = asyncio.StreamReaderProtocol(reader)
        transport, _ = await loop.create_pipe_connection(lambda: protocol, address)
        writer = asyncio.StreamWriter(transport, protocol, reader, loop)
        return reader, writer
    return await asyncio.open_unix_connection(
        address, limit=CHANNEL_CONTROL_LINE_BYTES_MAX
    )


def encode_line(body: dict) -> bytes:
    """One local line: the object as JSON with a newline after it."""
    return json.dumps(body, separators=(",", ":")).encode("utf-8") + b"\n"


def decode_line(line: bytes) -> "dict | None":
    """The object one local line carries, None for a line that is not one."""
    try:
        decoded = json.loads(line.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return decoded if isinstance(decoded, dict) else None


class LocalChannelClient:
    """The control connection and the stream connections to one transport.

    Attributes:
        is_connected: Whether a control connection is open now.
        loop: The loop the client runs on, set by :meth:`run`.
    """

    def __init__(self, *, address, secret_of, handler, connect=open_local_connection):
        """
        Args:
            address: The transport's listener, or a callable returning it.
            secret_of: Returns the secret every connection opens with, read
                afresh at each connect, since the transport's start makes it.
            handler: Takes what the transport sends: ``answer_question(
                question, fields)`` returns the answer's fields; ``take_event(
                event, fields)``; ``take_frame(session, frame)``; and
                ``control_opened()`` once a control connection is live.
            connect: ``connect(address)`` returns ``(reader, writer)``.
        """
        self._address = address
        self._secret_of = secret_of
        self._handler = handler
        self._connect = connect
        self.is_connected = False
        self.loop: "asyncio.AbstractEventLoop | None" = None
        self._writer: "asyncio.StreamWriter | None" = None
        self._write_lock: "asyncio.Lock | None" = None
        self._commands: dict = {}
        self._sessions: dict = {}
        self._stopping = False
        self._ids = 0

    def address(self) -> str:
        """The listener the client dials."""
        return self._address() if callable(self._address) else str(self._address)

    async def run(self) -> None:
        """Keep a control connection to the transport until :meth:`stop`."""
        self.loop = asyncio.get_running_loop()
        self._write_lock = asyncio.Lock()
        pause = CHANNEL_CONTROL_REDIAL_MIN_S
        while not self._stopping:
            try:
                reader, writer = await self._connect(self.address())
            except (OSError, RuntimeError, ValueError) as error:
                LOGGER.debug("transport not reached at %s: %s", self.address(), error)
                await asyncio.sleep(pause)
                pause = min(pause * 2, CHANNEL_CONTROL_REDIAL_MAX_S)
                continue
            pause = CHANNEL_CONTROL_REDIAL_MIN_S
            try:
                await self._serve_control(reader, writer)
            finally:
                self._drop_control()
                try:
                    writer.close()
                except (OSError, RuntimeError):
                    pass
            if not self._stopping:
                await asyncio.sleep(CHANNEL_CONTROL_REDIAL_MIN_S)

    def stop(self) -> None:
        """End the control connection and dial no more."""
        self._stopping = True
        if self._writer is not None:
            try:
                self._writer.close()
            except (OSError, RuntimeError):
                pass

    async def send_frame(self, session: str, frame: dict, *, is_last: bool = False):
        """Write one frame of a session's control stream.

        Args:
            session: The transport's session id.
            frame: The frame, ``type`` included.
            is_last: Whether the transport ends the session once it is written.

        Raises:
            AgentOfflineError: If no control connection is open.
        """
        line = {"frame": frame, "session": session}
        if is_last:
            line[CHANNEL_FRAME_IS_LAST] = True
        try:
            await self._write(line)
        except StreamRefusedError as error:
            raise AgentOfflineError(session) from error

    async def send_command(self, command: str, **fields) -> dict:
        """Send one command and wait for the transport's answer.

        Args:
            command: ``session_close``, ``streams_close`` or ``keys_reload``.
            **fields: The command's fields.

        Returns:
            The answer's fields beside its id.

        Raises:
            StreamRefusedError: With the transport's code, or
                ``control_unavailable`` when no control connection is open or
                none answered in time.
        """
        loop = asyncio.get_running_loop()
        command_id = self._next_id()
        future = loop.create_future()
        self._commands[command_id] = future
        try:
            await self._write({"id": command_id, "command": command, **fields})
            answer = await asyncio.wait_for(future, CHANNEL_CONTROL_COMMAND_TIMEOUT_S)
        except asyncio.TimeoutError:
            raise StreamRefusedError(CHANNEL_CODE_CONTROL_UNAVAILABLE, {})
        finally:
            self._commands.pop(command_id, None)
        if answer.get("code"):
            params = answer.get("params")
            raise StreamRefusedError(
                str(answer["code"]), dict(params) if isinstance(params, dict) else {}
            )
        return {key: value for key, value in answer.items() if key != "id"}

    async def open_stream(self, session: str, open_body: dict, *, peer_key: str = ""):
        """Open a stream on one session, as the hub's own.

        Args:
            session: The transport's session id.
            open_body: The open record's object, ``kind`` first.
            peer_key: The binding on the session, for the stream's codes.

        Returns:
            The :class:`ChannelStream`, after the far side's ``accept`` or
            refusing ``close``; a refused stream is closed with the refusal
            in ``close_info``.

        Raises:
            AgentOfflineError: If the transport cannot be reached.
        """
        reader, writer = await self._open_connection(
            {"op": CHANNEL_LOCAL_OP_OPEN, "session": session, "open": open_body}
        )
        stream = ChannelStream(
            reader=reader,
            writer=writer,
            kind=str(open_body.get("kind", "") or ""),
            args={key: value for key, value in open_body.items() if key != "kind"},
            peer_key=peer_key,
        )
        await stream.opened()
        return stream

    async def attach_stream(self, stream_id, open_body: dict, *, peer_key: str = ""):
        """Take a stream a peer opened, which the transport announced.

        Args:
            stream_id: The stream the ``stream`` event named.
            open_body: The open record's object the event carried.
            peer_key: The binding on the session, for the stream's codes.

        Returns:
            The :class:`ChannelStream`, before this side's ``accept``.

        Raises:
            AgentOfflineError: If the transport cannot be reached.
        """
        reader, writer = await self._open_connection(
            {"op": CHANNEL_LOCAL_OP_ATTACH, "stream": stream_id}
        )
        return ChannelStream(
            reader=reader,
            writer=writer,
            kind=str(open_body.get("kind", "") or ""),
            args={key: value for key, value in open_body.items() if key != "kind"},
            stream_id=int(stream_id) if isinstance(stream_id, int) else 0,
            peer_key=peer_key,
        )

    async def _open_connection(self, first: dict) -> tuple:
        """One more connection, opened with the secret and its first line."""
        try:
            reader, writer = await self._connect(self.address())
            writer.write(encode_line({"secret": self._secret_of(), **first}))
            await writer.drain()
        except (OSError, RuntimeError, ValueError) as error:
            raise AgentOfflineError(str(first.get("session", "")) or "") from error
        return reader, writer

    async def _serve_control(self, reader, writer) -> None:
        """Read one control connection to its end."""
        writer.write(
            encode_line({"secret": self._secret_of(), "op": CHANNEL_LOCAL_OP_CONTROL})
        )
        await writer.drain()
        self._writer = writer
        self.is_connected = True
        LOGGER.info("transport reached at %s", self.address())
        await self._handler.control_opened()
        while True:
            try:
                line = await reader.readline()
            except (asyncio.LimitOverrunError, ValueError):
                LOGGER.warning("the transport sent a line longer than one may be")
                return
            except (ConnectionError, OSError):
                return
            if not line:
                return
            message = decode_line(line)
            if message is None:
                continue
            self._dispatch(message)

    def _dispatch(self, message: dict) -> None:
        """Hand one line to its taker without holding the reader."""
        if "question" in message:
            asyncio.get_running_loop().create_task(self._answer(message))
        elif "event" in message:
            self._take_event(message)
        elif "frame" in message:
            session = str(message.get("session", "") or "")
            frame = message.get("frame")
            if session and isinstance(frame, dict):
                self._queue(session, ("frame", frame))
        elif "id" in message and message["id"] in self._commands:
            future = self._commands[message["id"]]
            if not future.done():
                future.set_result(message)

    def _take_event(self, message: dict) -> None:
        event = str(message.get("event", "") or "")
        fields = {key: value for key, value in message.items() if key != "event"}
        session = str(fields.get("session", "") or "")
        if event == CHANNEL_EVENT_SESSION_OPEN and session:
            self._start_session(session)
            self._queue(session, ("event", event, fields))
        elif event == CHANNEL_EVENT_SESSION_END and session:
            self._queue(session, ("event", event, fields))
            self._queue(session, None)
        elif event == CHANNEL_EVENT_STREAM:
            asyncio.get_running_loop().create_task(
                self._handler.take_event(event, fields)
            )
        else:
            asyncio.get_running_loop().create_task(
                self._handler.take_event(event, fields)
            )

    def _start_session(self, session: str) -> None:
        """One worker per session, so its frames are taken in order."""
        if session in self._sessions:
            return
        queue: asyncio.Queue = asyncio.Queue()
        task = asyncio.get_running_loop().create_task(
            self._serve_session(session, queue)
        )
        self._sessions[session] = (queue, task)

    def _queue(self, session: str, item) -> None:
        held = self._sessions.get(session)
        if held is None:
            if item is None:
                return
            self._start_session(session)
            held = self._sessions[session]
        held[0].put_nowait(item)

    async def _serve_session(self, session: str, queue: asyncio.Queue) -> None:
        """Take one session's events and frames, in order, to its end."""
        try:
            while True:
                item = await queue.get()
                if item is None:
                    return
                try:
                    if item[0] == "frame":
                        await self._handler.take_frame(session, item[1])
                    else:
                        await self._handler.take_event(item[1], item[2])
                except Exception:  # noqa: BLE001 - one bad frame ends no session
                    LOGGER.exception("session %s: a frame was not taken", session)
        finally:
            self._sessions.pop(session, None)

    async def _answer(self, message: dict) -> None:
        """Answer one question, ``control_unavailable`` on a failure of our own."""
        question = str(message.get("question", "") or "")
        fields = {
            key: value
            for key, value in message.items()
            if key not in ("id", "question")
        }
        try:
            answer = await self._handler.answer_question(question, fields)
        except Exception:  # noqa: BLE001 - the transport must hear an answer
            LOGGER.exception("question %s was not answered", question)
            answer = {"code": CHANNEL_CODE_CONTROL_UNAVAILABLE, "params": {}}
        try:
            await self._write({"id": message.get("id"), **answer})
        except StreamRefusedError:
            return

    async def _write(self, body: dict) -> None:
        if self._writer is None or self._write_lock is None or not self.is_connected:
            raise StreamRefusedError(CHANNEL_CODE_CONTROL_UNAVAILABLE, {})
        async with self._write_lock:
            try:
                self._writer.write(encode_line(body))
                await self._writer.drain()
            except (ConnectionError, OSError, RuntimeError) as error:
                raise StreamRefusedError(
                    CHANNEL_CODE_CONTROL_UNAVAILABLE, {}
                ) from error

    def _drop_control(self) -> None:
        """Forget the control connection: every session and command ended with it."""
        self.is_connected = False
        self._writer = None
        for future in list(self._commands.values()):
            if not future.done():
                future.set_result(
                    {"code": CHANNEL_CODE_CONTROL_UNAVAILABLE, "params": {}}
                )
        self._commands.clear()
        for session, (queue, _) in list(self._sessions.items()):
            queue.put_nowait(
                (
                    "event",
                    CHANNEL_EVENT_SESSION_END,
                    {"session": session, "reason": CHANNEL_CODE_CONTROL_UNAVAILABLE},
                )
            )
            queue.put_nowait(None)

    def _next_id(self) -> str:
        self._ids += 1
        return f"{self._ids}-{secrets.token_hex(4)}"


__all__ = [
    "LocalChannelClient",
    "open_local_connection",
    "encode_line",
    "decode_line",
    "encode_json_record",
    "CHANNEL_RECORD_OPEN",
]
