"""A fake transport: the local channel's listener, played by a test.

It listens on a Unix socket as ``neutrino_transport`` does, takes the
control connection, the ``attach`` and ``open`` connections, and lets a test
raise the events a real transport would (``session_open``, a frame,
``session_end``, ``stream``), ask the four questions and read what the hub's
Python wrote: its answers, its commands and its frames (transport.md, "The
local channel"). It judges nothing itself.
"""

import asyncio
import json

from neutrino_hub.modules.channel.local_channel import decode_line, encode_line
from neutrino_hub.modules.channel.streams import (
    encode_json_record,
    encode_record,
    read_record,
)

SECRET = "ab" * 32


class FakeTransport:
    """One fake transport on one socket path.

    Attributes:
        answers: Every answer the Python wrote to a question, by the
            question's id.
        commands: Every command line the Python wrote, in order.
        frames: Every frame line the Python wrote, in order.
        opens: Every ``open`` connection's first line, in order.
        attaches: Every ``attach`` connection's first line, in order.
        refused_secrets: How many connections opened with a wrong secret.
    """

    def __init__(self, path: str, *, secret: str = SECRET):
        self.path = path
        self.secret = secret
        self.answers: dict = {}
        self.commands: list = []
        self.frames: list = []
        self.opens: list = []
        self.attaches: list = []
        self.refused_secrets = 0
        self.control_writer = None
        self.control_count = 0
        self._server = None
        self._ids = 0
        self._waiters: dict = {}
        self._stream_connections: dict = {}
        self._open_connections: list = []
        self._control_opened = asyncio.Event()
        self._command_arrived = asyncio.Event()
        self._frame_arrived = asyncio.Event()

    async def start(self) -> None:
        """Listen on the path."""
        self._server = await asyncio.start_unix_server(self._serve, path=self.path)

    async def stop(self) -> None:
        """Close the listener and every connection."""
        if self.control_writer is not None:
            self.control_writer.close()
            self.control_writer = None
        if self._server is not None:
            self._server.close()
            await asyncio.sleep(0)

    async def wait_control(self, timeout: float = 5.0) -> None:
        """Wait until the Python opened its control connection."""
        await asyncio.wait_for(self._control_opened.wait(), timeout)

    async def drop_control(self) -> None:
        """End the control connection, as a restarting transport does."""
        if self.control_writer is not None:
            self.control_writer.close()
            self.control_writer = None
        self._control_opened.clear()

    async def ask(self, question: str, timeout: float = 5.0, **fields) -> dict:
        """Ask one question and wait for the Python's answer.

        Returns:
            The answer's fields beside its id.
        """
        self._ids += 1
        question_id = f"q{self._ids}"
        future = asyncio.get_running_loop().create_future()
        self._waiters[question_id] = future
        await self._write({"id": question_id, "question": question, **fields})
        answer = await asyncio.wait_for(future, timeout)
        return {key: value for key, value in answer.items() if key != "id"}

    async def event(self, event: str, **fields) -> None:
        """Raise one event."""
        await self._write({"event": event, **fields})

    async def frame(self, session: str, frame: dict) -> None:
        """Pass one frame of a session up to the Python."""
        await self._write({"frame": frame, "session": session})

    async def next_frame(self, timeout: float = 5.0) -> dict:
        """The next frame line the Python writes, waited for."""
        while not self.frames:
            self._frame_arrived.clear()
            await asyncio.wait_for(self._frame_arrived.wait(), timeout)
        return self.frames.pop(0)

    async def next_command(self, timeout: float = 5.0) -> dict:
        """The next command line the Python writes, waited for and answered ``{id}``."""
        while not self.commands:
            self._command_arrived.clear()
            await asyncio.wait_for(self._command_arrived.wait(), timeout)
        command = self.commands.pop(0)
        await self._write({"id": command["id"]})
        return command

    async def refuse_next_command(self, code: str, timeout: float = 5.0) -> dict:
        """The next command line, answered with a refusal."""
        while not self.commands:
            self._command_arrived.clear()
            await asyncio.wait_for(self._command_arrived.wait(), timeout)
        command = self.commands.pop(0)
        await self._write({"id": command["id"], "code": code, "params": {}})
        return command

    async def next_open(self, timeout: float = 5.0) -> "FakeStreamEnd":
        """The next ``open`` connection the Python made, as the far side."""
        deadline = asyncio.get_running_loop().time() + timeout
        while not self._open_connections:
            if asyncio.get_running_loop().time() > deadline:
                raise asyncio.TimeoutError()
            await asyncio.sleep(0.01)
        return self._open_connections.pop(0)

    async def announce_stream(self, stream_id: int, session: str, open_body: dict):
        """Raise ``stream`` and hand back the far side once the Python attached.

        Returns:
            The :class:`FakeStreamEnd` the Python's attach connection became.
        """
        future = asyncio.get_running_loop().create_future()
        self._stream_connections[stream_id] = future
        await self.event("stream", stream=stream_id, session=session, open=open_body)
        return await asyncio.wait_for(future, 5.0)

    async def _serve(self, reader, writer) -> None:
        line = await reader.readline()
        first = decode_line(line) or {}
        if first.get("secret") != self.secret:
            self.refused_secrets += 1
            writer.close()
            return
        op = first.get("op")
        if op == "control":
            await self._serve_control(reader, writer)
        elif op == "attach":
            self.attaches.append(first)
            end = FakeStreamEnd(reader, writer, first)
            future = self._stream_connections.pop(first.get("stream"), None)
            if future is not None and not future.done():
                future.set_result(end)
        elif op == "open":
            self.opens.append(first)
            self._open_connections.append(FakeStreamEnd(reader, writer, first))
        else:
            writer.close()

    async def _serve_control(self, reader, writer) -> None:
        self.control_writer = writer
        self.control_count += 1
        self._control_opened.set()
        try:
            while True:
                line = await reader.readline()
                if not line:
                    return
                message = decode_line(line)
                if message is None:
                    continue
                if "command" in message:
                    self.commands.append(message)
                    self._command_arrived.set()
                elif "frame" in message:
                    self.frames.append(message)
                    self._frame_arrived.set()
                elif "id" in message:
                    self.answers[message["id"]] = message
                    future = self._waiters.pop(message["id"], None)
                    if future is not None and not future.done():
                        future.set_result(message)
        except (ConnectionError, OSError):
            return
        finally:
            if self.control_writer is writer:
                self.control_writer = None
                self._control_opened.clear()

    async def _write(self, body: dict) -> None:
        if self.control_writer is None:
            raise RuntimeError("no control connection")
        self.control_writer.write(encode_line(body))
        await self.control_writer.drain()


class FakeStreamEnd:
    """The far side of one stream connection the Python holds.

    Attributes:
        first: The connection's first line.
    """

    def __init__(self, reader, writer, first: dict):
        self.first = first
        self._reader = reader
        self._writer = writer

    async def read(self) -> "tuple | None":
        """The next record the Python wrote, ``(type, payload)``, None at the end."""
        return await read_record(self._reader)

    async def read_json(self) -> tuple:
        """The next record with its payload decoded as JSON."""
        record = await self.read()
        if record is None:
            return None
        return record[0], json.loads(record[1].decode("utf-8")) if record[1] else {}

    async def accept(self) -> None:
        """Answer the Python's open with ``accept``."""
        self._writer.write(encode_record(2))
        await self._writer.drain()

    async def send(self, record_type: int, payload: bytes = b"") -> None:
        """Write one record towards the Python."""
        self._writer.write(encode_record(record_type, payload))
        await self._writer.drain()

    async def close(self, code: str = "", params: "dict | None" = None) -> None:
        """Write a close towards the Python and end the connection."""
        self._writer.write(
            encode_json_record(8, {"code": code, "params": dict(params or {})})
        )
        await self._writer.drain()
        self._writer.close()

    def drop(self) -> None:
        """End the connection with no close."""
        self._writer.close()
