"""Live channels: one socket per binding, every stream on it.

An agent or a client keeps one WebSocket open to the hub. Text frames are
JSON messages; a binary frame is a big-endian u32 stream id followed by the
bytes for that stream. Either side opens a stream with ``open``, the hub
on even ids and the peer on odd ones, and ends it with ``close``, whose
``params`` are its result. Bytes travel under ``credit``: the receiving
side grants as it consumes.

The registry holds the sessions of one role, keyed by binding id, and is
what the rest of the hub asks: whether a binding is online, what software
it runs, when its last session ended, to push its state, to open a stream
on it. Presence is memory alone. Routes on the hub's loop await the session
directly; threadpool routes and worker threads go through the
``*_from_thread`` methods.
"""

import asyncio
import concurrent.futures
import itertools
import json
import threading
import time
from datetime import datetime, timezone

from neutrino_hub.exceptions import AgentOfflineError, StreamRefusedError
from neutrino_hub.modules.channel.constants import (
    CHANNEL_CALL_TIMEOUT_S,
    CHANNEL_CHUNK_BYTES,
    CHANNEL_CLOSE_REFUSED,
    CHANNEL_CLOSE_REPLACED,
    CHANNEL_CODE_KIND_UNKNOWN,
    CHANNEL_CODE_NEVER_REPORTED,
    CHANNEL_CODE_REPLACED,
    CHANNEL_FIRST_HUB_STREAM_ID,
    CHANNEL_FRAME_CLOSE,
    CHANNEL_FRAME_CREDIT,
    CHANNEL_FRAME_OPEN,
    CHANNEL_FRAME_REFUSED,
    CHANNEL_FRAME_STATE,
    CHANNEL_STREAM_CREDIT_BYTES,
    CHANNEL_STREAM_ID_BYTES,
)

# The fields of an open that are not the kind's own arguments.
OPEN_ENVELOPE_FIELDS = ("type", "stream", "kind")
# What the session routes to a stream by itself.
STREAM_MESSAGE_TYPES = (CHANNEL_FRAME_CLOSE, CHANNEL_FRAME_CREDIT)


def _now() -> str:
    """The current time as an ISO 8601 stamp in UTC."""
    return datetime.now(timezone.utc).isoformat()


def version_of_software(software: str) -> str:
    """The version a ``software`` field names, empty when it names none."""
    _, separator, version = software.partition("/")
    return version if separator else ""


class ChannelStream:
    """One stream on one session.

    What arrives from the peer queues up in order: ``("data", bytes)`` for
    a binary frame, and ``None`` once the stream has closed and the queue
    is drained. What the hub sends goes out at once, except bytes, which
    wait for the peer's credit.

    Attributes:
        id: The stream id.
        kind: The stream kind.
        args: What the open carried beside the kind.
        close_info: ``{"code", "params"}`` once the stream closed.
        is_abandoned: True when the session went away under the stream.
    """

    def __init__(self, session: "ChannelSession", stream_id: int, kind: str, args=None):
        self.id = int(stream_id)
        self.kind = kind
        self.args = dict(args or {})
        self.close_info: "dict | None" = None
        self.is_abandoned = False
        self._session = session
        self._inbound: asyncio.Queue = asyncio.Queue()
        self._closed = asyncio.Event()
        self._credit = 0
        self._credit_granted = asyncio.Event()

    @property
    def is_closed(self) -> bool:
        """Whether the stream ended, from either side, or the session is gone."""
        return self._closed.is_set()

    async def recv(self) -> "tuple | None":
        """The next item from the peer, granting it room for as much again.

        Returns:
            ``("data", bytes)``, or None once the stream is closed and
            nothing is left to read.
        """
        if self._closed.is_set() and self._inbound.empty():
            return None
        item = await self._inbound.get()
        if item is not None and not self._closed.is_set():
            await self._session.send_credit(self.id, len(item[1]))
        return item

    async def send_bytes(self, data: bytes) -> None:
        """Send bytes to the peer, as far as its credit allows.

        Args:
            data: The bytes; sent in chunks, waiting on credit between them.

        Raises:
            AgentOfflineError: If the stream closes before everything is sent.
        """
        view = memoryview(data)
        while view:
            if self._closed.is_set():
                raise AgentOfflineError(self._session.key)
            if self._credit <= 0:
                self._credit_granted.clear()
                await self._credit_granted.wait()
                continue
            size = min(self._credit, CHANNEL_CHUNK_BYTES, len(view))
            await self._session.send_bytes(self.id, bytes(view[:size]))
            self._credit -= size
            view = view[size:]

    async def close(self, code: str = "", params: "dict | None" = None) -> None:
        """End the stream from this side, with its result.

        A stream the peer already ended sends nothing.

        Args:
            code: The refusal; empty when the stream did what it was asked.
            params: The result, or what the code's wording names.
        """
        if self._closed.is_set():
            return
        info = {"code": code, "params": dict(params or {})}
        self._finish(info)
        await self._session.send_json(
            {"type": CHANNEL_FRAME_CLOSE, "stream": self.id, **info}
        )

    async def wait_closed(self) -> "dict | None":
        """Wait for the stream's end.

        Returns:
            What it closed with, or None when the session went away.
        """
        await self._closed.wait()
        return self.close_info

    def recv_from_thread(self, timeout: "float | None" = None) -> "tuple | None":
        """:meth:`recv` for a caller outside the loop."""
        return self._session.call(self.recv(), timeout=timeout)

    def send_bytes_from_thread(self, data: bytes, timeout: "float | None" = None):
        """:meth:`send_bytes` for a caller outside the loop."""
        return self._session.call(self.send_bytes(data), timeout=timeout)

    def close_from_thread(
        self, code: str = "", params: "dict | None" = None, timeout: float = 5.0
    ) -> None:
        """:meth:`close` for a caller outside the loop."""
        self._session.call(self.close(code, params), timeout=timeout)

    def wait_closed_from_thread(self, timeout: "float | None" = None) -> "dict | None":
        """:meth:`wait_closed` for a caller outside the loop."""
        return self._session.call(self.wait_closed(), timeout=timeout)

    def _deliver(self, item: tuple) -> None:
        if self._closed.is_set():
            return
        self._inbound.put_nowait(item)

    def _grant(self, size: int) -> None:
        self._credit += max(0, int(size))
        if self._credit > 0:
            self._credit_granted.set()

    def _finish(self, info: dict, *, is_abandoned: bool = False) -> None:
        if self._closed.is_set():
            return
        self.is_abandoned = is_abandoned
        self.close_info = dict(info)
        self._closed.set()
        self._credit_granted.set()
        self._inbound.put_nowait(None)


class ChannelSession:
    """One binding's live channel and the streams on it.

    Attributes:
        key: The binding id.
        role: What is on the other end, ``agent`` or ``client``.
        name: What the peer called itself in its hello.
        software: The package and version the hello named.
        address: Where its channel comes from.
        report: The most recent report, whole.
        reported_at: When that report arrived, as an ISO stamp; empty
            before the first one.
        state_hash: The state hash the peer last claimed.
        offered_hash: The hash of the state this connection was last handed;
            None before the first report was judged.
        stream_handlers: Stream kind to the coroutine function serving a
            stream the peer opens, called with ``(session, stream)``.
        loop: The loop the socket is served on.
    """

    def __init__(
        self,
        *,
        key: str,
        role: str,
        websocket,
        loop: asyncio.AbstractEventLoop,
        name: str = "",
        software: str = "",
        address: str = "",
    ):
        self.key = key
        self.role = role
        self.name = name
        self.software = software
        self.address = address
        self.report: dict = {}
        self.reported_at = ""
        self.report_serial = 0
        self.state_hash = ""
        self.offered_hash: "str | None" = None
        self.stream_handlers: dict = {}
        self.loop = loop
        self.opened_at = time.monotonic()
        self._reported = asyncio.Event()
        self._websocket = websocket
        self._streams: dict[int, ChannelStream] = {}
        self._ids = itertools.count(CHANNEL_FIRST_HUB_STREAM_ID, 2)
        self._send_lock = asyncio.Lock()
        self._is_closed = False

    @property
    def is_closed(self) -> bool:
        """Whether the socket is gone."""
        return self._is_closed

    @property
    def version(self) -> str:
        """The version the peer's software names, empty when it names none."""
        return version_of_software(self.software)

    async def send_json(self, message: dict) -> None:
        """Send one text frame.

        Args:
            message: The JSON object, ``type`` included.

        Raises:
            AgentOfflineError: If the socket is gone.
        """
        await self._send(text=json.dumps(message))

    async def send_bytes(self, stream_id: int, data: bytes) -> None:
        """Send one binary frame on a stream.

        Args:
            stream_id: The stream the bytes belong to.
            data: The bytes.

        Raises:
            AgentOfflineError: If the socket is gone.
        """
        await self._send(
            data=int(stream_id).to_bytes(CHANNEL_STREAM_ID_BYTES, "big") + data
        )

    async def send_credit(self, stream_id: int, size: int) -> None:
        """Let the peer send this many more bytes on a stream.

        Args:
            stream_id: The stream.
            size: The bytes granted.

        Raises:
            AgentOfflineError: If the socket is gone.
        """
        await self.send_json(
            {"type": CHANNEL_FRAME_CREDIT, "stream": int(stream_id), "bytes": int(size)}
        )

    async def open_stream(
        self, kind: str, args: dict, credit: int = CHANNEL_STREAM_CREDIT_BYTES
    ) -> ChannelStream:
        """Open a stream on the peer and grant its first window.

        Args:
            kind: The stream kind.
            args: What the kind takes, sent beside it in the open.
            credit: How many bytes the peer may send before waiting.

        Returns:
            The stream; its close is the peer's answer.

        Raises:
            AgentOfflineError: If the socket is gone.
        """
        if self._is_closed:
            raise AgentOfflineError(self.key)
        stream_id = next(self._ids)
        stream = ChannelStream(self, stream_id, kind, args)
        self._streams[stream_id] = stream
        try:
            await self.send_json(
                {"type": CHANNEL_FRAME_OPEN, "stream": stream_id, "kind": kind, **args}
            )
            await self.send_credit(stream_id, credit)
        except AgentOfflineError:
            self._streams.pop(stream_id, None)
            raise
        return stream

    async def accept_stream(
        self, open_frame: dict, credit: int = CHANNEL_STREAM_CREDIT_BYTES
    ) -> "ChannelStream | None":
        """Take a stream the peer opened and hand it to its kind's handler.

        Args:
            open_frame: The decoded open.
            credit: How many bytes the peer may send before waiting.

        Returns:
            The stream, or None when the open named no usable id, or a kind
            with no handler, which is closed ``kind_unknown``.

        Raises:
            AgentOfflineError: If the socket is gone.
        """
        stream_id = open_frame.get("stream")
        if not isinstance(stream_id, int) or stream_id in self._streams:
            return None
        kind = str(open_frame.get("kind", "") or "")
        handler = self.stream_handlers.get(kind)
        if handler is None:
            await self.send_json(
                {
                    "type": CHANNEL_FRAME_CLOSE,
                    "stream": stream_id,
                    "code": CHANNEL_CODE_KIND_UNKNOWN,
                    "params": {"kind": kind},
                }
            )
            return None
        args = {
            name: value
            for name, value in open_frame.items()
            if name not in OPEN_ENVELOPE_FIELDS
        }
        stream = ChannelStream(self, stream_id, kind, args)
        self._streams[stream_id] = stream
        await self.send_credit(stream_id, credit)
        self.loop.create_task(self._serve_accepted(handler, stream))
        return stream

    async def push_state(self, document: dict) -> None:
        """Send the peer its state.

        Args:
            document: The state with its ``hash`` and sections.

        Raises:
            AgentOfflineError: If the socket is gone.
        """
        await self.send_json({"type": CHANNEL_FRAME_STATE, **document})
        self.offered_hash = str(document.get("hash", "") or "")

    async def refuse(self, code: str, params: "dict | None" = None) -> None:
        """Turn the peer away: a refused frame, then the refused close.

        Args:
            code: Why.
            params: What the code's wording names.
        """
        try:
            await self.send_json(
                {
                    "type": CHANNEL_FRAME_REFUSED,
                    "code": code,
                    "params": dict(params or {}),
                }
            )
        except AgentOfflineError:
            return
        await self.close(CHANNEL_CLOSE_REFUSED, code)

    def record_report(self, report: dict) -> None:
        """Keep the peer's latest report.

        Args:
            report: The whole ``report`` message.
        """
        self.report = dict(report)
        self.reported_at = _now()
        self.state_hash = str(report.get("state_hash", "") or "")

    def note_report_recorded(self) -> None:
        """Count a report once everything read from it is in place.

        Called on the loop after the report is recorded everywhere the
        routes read, so a waiter woken here reads what the report said.
        """
        self.report_serial += 1
        self._reported.set()
        self._reported.clear()

    async def wait_for_report(self, after_serial: int, timeout: float) -> bool:
        """Wait for a report newer than the one counted.

        Args:
            after_serial: The serial the caller read before what it did.
            timeout: How long to wait.

        Returns:
            True when a newer report was recorded, False when the wait ran
            out or the channel closed.
        """
        while self.report_serial <= after_serial and not self._is_closed:
            try:
                await asyncio.wait_for(self._reported.wait(), timeout)
            except asyncio.TimeoutError:
                return False
        return self.report_serial > after_serial

    def dispatch_text(self, message: dict) -> bool:
        """Route one stream message from the peer.

        Args:
            message: The decoded frame.

        Returns:
            True when the message was a close or a credit; False for a type
            the caller handles itself.
        """
        kind = message.get("type")
        if kind not in STREAM_MESSAGE_TYPES:
            return False
        stream = self._streams.get(message.get("stream"))
        if stream is None:
            return True
        if kind == CHANNEL_FRAME_CREDIT:
            stream._grant(message.get("bytes", 0))
        else:
            self._streams.pop(stream.id, None)
            params = message.get("params")
            stream._finish(
                {
                    "code": str(message.get("code", "") or ""),
                    "params": dict(params) if isinstance(params, dict) else {},
                }
            )
        return True

    def dispatch_bytes(self, data: bytes) -> None:
        """Route one binary frame to its stream.

        Args:
            data: The frame: the stream id, then the bytes.
        """
        if len(data) < CHANNEL_STREAM_ID_BYTES:
            return
        stream = self._streams.get(
            int.from_bytes(data[:CHANNEL_STREAM_ID_BYTES], "big")
        )
        if stream is not None:
            stream._deliver(("data", bytes(data[CHANNEL_STREAM_ID_BYTES:])))

    def fail_streams(self, code: str = AgentOfflineError.code) -> None:
        """End every stream with one code.

        Args:
            code: What each stream closes with.
        """
        self._is_closed = True
        for stream in list(self._streams.values()):
            stream._finish(
                {"code": code, "params": {"device": self.key}}, is_abandoned=True
            )
        self._streams.clear()

    async def close(self, code: int, reason: str = "") -> None:
        """Close the socket, failing every open stream with ``agent_offline``.

        Args:
            code: The close code.
            reason: The reason word.
        """
        self.fail_streams()
        try:
            await self._websocket.close(code=code, reason=reason)
        except Exception:  # noqa: BLE001 - the peer may be gone already
            return

    def call(self, coroutine, timeout: "float | None" = None):
        """Run a coroutine on the session's loop from another thread.

        Args:
            coroutine: What to run.
            timeout: How long to wait for its result.

        Returns:
            The coroutine's result.

        Raises:
            StreamRefusedError: With ``agent_never_reported`` when the wait
                runs out; the coroutine is cancelled.
        """
        future = asyncio.run_coroutine_threadsafe(coroutine, self.loop)
        try:
            return future.result(timeout)
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise StreamRefusedError(CHANNEL_CODE_NEVER_REPORTED, {"device": self.key})

    async def _serve_accepted(self, handler, stream: ChannelStream) -> None:
        """Run one handler over a stream the peer opened, to its close."""
        try:
            await handler(self, stream)
        except AgentOfflineError:
            return
        finally:
            self._streams.pop(stream.id, None)
            if not stream.is_closed:
                try:
                    await stream.close()
                except AgentOfflineError:
                    return

    async def _send(self, *, text: "str | None" = None, data: "bytes | None" = None):
        if self._is_closed:
            raise AgentOfflineError(self.key)
        async with self._send_lock:
            try:
                if text is not None:
                    await self._websocket.send_text(text)
                else:
                    await self._websocket.send_bytes(data)
            except Exception as error:  # noqa: BLE001 - any failure is a dead socket
                raise AgentOfflineError(self.key) from error


class ChannelSessionRegistry:
    """The live sessions of one role, keyed by binding id.

    Attributes:
        role: The one role this registry holds.
        loop: The loop the sessions are served on, known once one attaches.
        on_presence_change: Called with nothing whenever a binding's channel
            opens or ends. The registry knows nothing of the panel; whoever
            wants to hear sets this.
        stream_handlers: Stream kind to the coroutine function serving a
            stream a peer opens; every attached session shares it.
    """

    def __init__(self, role: str):
        self.role = role
        self.loop: "asyncio.AbstractEventLoop | None" = None
        self.on_presence_change = None
        self.stream_handlers: dict = {}
        self._lock = threading.Lock()
        self._sessions: dict[str, ChannelSession] = {}
        self._software: dict[str, str] = {}
        self._ended_at: dict[str, str] = {}

    async def attach(self, session: ChannelSession) -> None:
        """Make a session the binding's current one.

        Args:
            session: The session that just said hello. An older session
                for the same binding is closed with the replaced code.

        Raises:
            ValueError: When the session is of another role than this
                registry holds.
        """
        if session.role != self.role:
            raise ValueError(f"{session.role} session in a {self.role} registry")
        session.stream_handlers = self.stream_handlers
        with self._lock:
            previous = self._sessions.get(session.key)
            self._sessions[session.key] = session
            self._software[session.key] = session.software
            self._ended_at.pop(session.key, None)
            self.loop = session.loop
        if previous is not None and previous is not session:
            await previous.close(CHANNEL_CLOSE_REPLACED, CHANNEL_CODE_REPLACED)
        self._note_presence()

    def detach(self, session: ChannelSession) -> bool:
        """Drop a session, only when it is still the binding's current one.

        Args:
            session: The session whose socket ended.

        Returns:
            True when this was the current session; False for one already
            replaced, whose binding is still online through its successor.
        """
        with self._lock:
            if self._sessions.get(session.key) is not session:
                return False
            self._sessions.pop(session.key, None)
            self._ended_at[session.key] = _now()
        session.fail_streams()
        self._note_presence()
        return True

    def get(self, key: str) -> "ChannelSession | None":
        """The binding's session, or None while it is offline."""
        with self._lock:
            return self._sessions.get(key or "")

    def is_online(self, key: str) -> bool:
        """Whether the binding has a live channel."""
        return self.get(key) is not None

    def last_seen_at(self, key: str) -> "str | None":
        """When the binding's last channel ended.

        Args:
            key: The binding.

        Returns:
            The ISO stamp the session detached at, or None while it is
            online and for one this hub has not seen since it started.
        """
        with self._lock:
            return self._ended_at.get(key or "")

    def last_report_at(self, key: str) -> "str | None":
        """When the binding's last report arrived.

        Args:
            key: The binding.

        Returns:
            The ISO stamp of the newest report on its live channel, or None
            while it is offline and before its first report.
        """
        session = self.get(key)
        if session is None or not session.reported_at:
            return None
        return session.reported_at

    def software_of(self, key: str) -> str:
        """The software the binding's last hello named.

        Args:
            key: The binding.

        Returns:
            The ``software`` field, kept after the channel ends; empty for a
            binding this hub has not seen since it started.
        """
        with self._lock:
            return self._software.get(key or "", "")

    def version_of(self, key: str) -> str:
        """The version the binding's last hello named, empty for none."""
        return version_of_software(self.software_of(key))

    def keys(self) -> list:
        """Every binding with a live channel."""
        with self._lock:
            return list(self._sessions)

    def sessions(self) -> list:
        """Every live session."""
        with self._lock:
            return list(self._sessions.values())

    def reports(self) -> dict:
        """The latest report of every online binding, by key."""
        with self._lock:
            return {key: session.report for key, session in self._sessions.items()}

    async def open_stream(self, key: str, kind: str, args: dict) -> ChannelStream:
        """Open a stream on one binding.

        Args:
            key: The binding.
            kind: The stream kind.
            args: What the kind takes.

        Returns:
            The opened stream.

        Raises:
            AgentOfflineError: When the binding has no channel.
        """
        return await self._require(key).open_stream(kind, args)

    async def push_state(self, key: str, document: dict) -> None:
        """Send a binding its state.

        Args:
            key: The binding.
            document: The state with its ``hash`` and sections.

        Raises:
            AgentOfflineError: When the binding has no channel.
        """
        await self._require(key).push_state(document)

    async def run_stream(
        self,
        key: str,
        kind: str,
        args: dict,
        payload: "bytes | None" = None,
        on_chunk=None,
    ) -> dict:
        """Open a stream, hand it what it takes, and wait for its close.

        Args:
            key: The binding.
            kind: The stream kind.
            args: What the kind takes.
            payload: Bytes to send on the stream after the open, if any.
            on_chunk: Called with each binary frame's bytes as they arrive.

        Returns:
            The close, ``{"code", "params"}``.

        Raises:
            AgentOfflineError: When the binding has no channel, or the socket
                ends before the close.
        """
        stream = await self.open_stream(key, kind, args)
        if payload:
            await stream.send_bytes(payload)
        return await self._collect(stream, on_chunk)

    def open_stream_from_thread(
        self, key: str, kind: str, args: dict, timeout: "float | None" = None
    ) -> ChannelStream:
        """:meth:`open_stream` for a caller outside the loop."""
        session = self._require(key)
        return session.call(session.open_stream(kind, args), timeout=timeout)

    def push_state_from_thread(
        self, key: str, document: dict, timeout: "float | None" = 5.0
    ) -> None:
        """:meth:`push_state` for a caller outside the loop."""
        session = self._require(key)
        session.call(session.push_state(document), timeout=timeout)

    def run_stream_from_thread(
        self,
        key: str,
        kind: str,
        args: dict,
        payload: "bytes | None" = None,
        on_chunk=None,
        timeout: "float | None" = CHANNEL_CALL_TIMEOUT_S,
    ) -> dict:
        """:meth:`run_stream` for a caller outside the loop."""
        session = self._require(key)
        return session.call(
            self.run_stream(key, kind, args, payload, on_chunk), timeout=timeout
        )

    def report_serial_of(self, key: str) -> int:
        """How many reports the binding's live channel has counted.

        Args:
            key: The binding.

        Returns:
            The count, 0 while it is offline.
        """
        session = self.get(key)
        return session.report_serial if session is not None else 0

    def wait_for_report_from_thread(
        self, key: str, after_serial: int, timeout: float
    ) -> bool:
        """:meth:`ChannelSession.wait_for_report` for a caller outside the loop.

        Args:
            key: The binding.
            after_serial: The serial read before what the caller did.
            timeout: How long to wait.

        Returns:
            True when a newer report was recorded; False when the wait ran
            out, the channel closed, or the binding is offline.
        """
        session = self.get(key)
        if session is None:
            return False
        try:
            return session.call(
                session.wait_for_report(after_serial, timeout), timeout=timeout + 1
            )
        except StreamRefusedError:
            return False

    def send_json_from_thread(self, key: str, message: dict) -> bool:
        """Hand one text frame to a session from outside the loop, not waiting.

        Args:
            key: The binding.
            message: The JSON object, ``type`` included.

        Returns:
            True when the frame was queued on a live session; False when
            there is none. A socket that dies under the frame drops it.
        """
        session = self.get(key)
        if session is None:
            return False
        try:
            asyncio.run_coroutine_threadsafe(session.send_json(message), session.loop)
        except RuntimeError:
            return False
        return True

    def refuse_from_thread(
        self, key: str, code: str, params: "dict | None" = None
    ) -> None:
        """Turn a binding's live socket away from outside the loop, if it has one.

        Args:
            key: The binding.
            code: Why.
            params: What the code's wording names.
        """
        session = self.get(key)
        if session is None:
            return
        try:
            session.call(session.refuse(code, params), timeout=5.0)
        except (StreamRefusedError, RuntimeError):
            return

    def close_from_thread(self, key: str, code: int, reason: str = "") -> None:
        """Close a binding's socket from outside the loop, if it has one."""
        session = self.get(key)
        if session is None:
            return
        try:
            session.call(session.close(code, reason), timeout=5.0)
        except (StreamRefusedError, RuntimeError):
            return

    def _note_presence(self) -> None:
        """Say a binding came or went, where anybody asked to be told."""
        if self.on_presence_change is not None:
            self.on_presence_change()

    def _require(self, key: str) -> ChannelSession:
        session = self.get(key)
        if session is None:
            raise AgentOfflineError(key or "")
        return session

    async def _collect(self, stream: ChannelStream, on_chunk) -> dict:
        """Read a stream to its close, handing bytes on.

        Args:
            stream: The stream.
            on_chunk: Called with each binary frame's bytes, or None.

        Returns:
            The close, ``{"code", "params"}``.

        Raises:
            AgentOfflineError: When the socket ended before the close.
        """
        while True:
            item = await stream.recv()
            if item is None:
                break
            if on_chunk is not None:
                on_chunk(item[1])
        if stream.is_abandoned:
            raise AgentOfflineError(stream._session.key)
        return dict(stream.close_info or {})
