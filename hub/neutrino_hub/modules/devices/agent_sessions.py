"""Live agent channels: one socket per device, every stream on it.

An agent keeps one WebSocket open to the hub. Text frames are JSON
messages; a binary frame is a stream id followed by the bytes for that
stream. The hub opens every stream, a command or an order; the agent
answers each open with ``opened`` or ``refused``, delivers ``event`` lines
and bytes while the stream runs, and ends it with ``close``.

The registry holds the sessions, keyed by device, and is what the rest of
the hub asks: whether a device is online, to push its desired state, to
open a stream on it. Routes on the hub's loop await the session directly;
threadpool routes and worker threads go through the ``*_from_thread``
methods.
"""

import asyncio
import concurrent.futures
import itertools
import json
import threading
import time

from neutrino_hub.modules.devices.constants import (
    AGENT_WS_CHUNK_BYTES,
    AGENT_WS_CLOSE_REPLACED,
    AGENT_WS_OPEN_TIMEOUT_S,
    AGENT_WS_STREAM_CREDIT_BYTES,
    AGENT_WS_STREAM_ID_LENGTH,
)

STREAM_KIND_COMMAND = "command"
STREAM_KIND_ORDER = "order"

# What an agent sends about one stream.
STREAM_MESSAGE_TYPES = ("opened", "refused", "event", "close", "credit")

CODE_AGENT_OFFLINE = "agent_offline"
CODE_STREAM_OPEN_TIMEOUT = "stream_open_timeout"
CODE_STREAM_TIMEOUT = "agent_never_reported"


class AgentOfflineError(Exception):
    """The device has no live channel."""

    code = CODE_AGENT_OFFLINE

    def __init__(self, device: str):
        super().__init__(device)
        self.params = {"device": device}


class StreamRefusedError(Exception):
    """The agent would not open the stream, or the hub stopped waiting."""

    def __init__(self, code: str, params: "dict | None" = None):
        super().__init__(code)
        self.code = code
        self.params = dict(params or {})


class AgentStream:
    """One stream on one session.

    What arrives from the agent queues up in order: ``("event", message)``
    for a JSON line, ``("data", bytes)`` for a binary frame, and ``None``
    once the stream has closed and the queue is drained. What the hub sends
    goes out at once, except bytes, which wait for the agent's credit.
    """

    def __init__(self, session: "AgentSession", stream_id: str, kind: str):
        self.id = stream_id
        self.kind = kind
        self.close_info: "dict | None" = None
        # Set when the session went away under the stream rather than the
        # agent closing it.
        self.is_abandoned = False
        self._session = session
        self._inbound: asyncio.Queue = asyncio.Queue()
        self._closed = asyncio.Event()
        self._credit = 0
        self._credit_granted = asyncio.Event()

    @property
    def is_closed(self) -> bool:
        """Whether the agent has closed this stream or the session is gone."""
        return self._closed.is_set()

    async def recv(self) -> "tuple | None":
        """The next item from the agent.

        Returns:
            ``("event", message)``, ``("data", bytes)``, or None once the
            stream is closed and nothing is left to read.
        """
        if self._closed.is_set() and self._inbound.empty():
            return None
        item = await self._inbound.get()
        if item is not None and item[0] == "data":
            await self._session.send_json(
                {"type": "credit", "stream": self.id, "bytes": len(item[1])}
            )
        return item

    async def send_bytes(self, data: bytes) -> None:
        """Send bytes to the agent, as far as its credit allows.

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
            size = min(self._credit, AGENT_WS_CHUNK_BYTES, len(view))
            await self._session.send_bytes(self.id, bytes(view[:size]))
            self._credit -= size
            view = view[size:]

    async def resize(self, cols: int, rows: int) -> None:
        """Tell a shell stream its new size.

        Args:
            cols: Columns.
            rows: Rows.
        """
        await self._session.send_json(
            {"type": "resize", "stream": self.id, "cols": int(cols), "rows": int(rows)}
        )

    async def close(self) -> None:
        """Ask the agent to end the stream; the agent's close follows."""
        if self._closed.is_set():
            return
        await self._session.send_json({"type": "close", "stream": self.id})

    async def wait_closed(self) -> "dict | None":
        """Wait for the agent's close.

        Returns:
            What the agent closed with, or None when the session went away.
        """
        await self._closed.wait()
        return self.close_info

    def recv_from_thread(self, timeout: "float | None" = None) -> "tuple | None":
        """:meth:`recv` for a caller outside the loop."""
        return self._session.call(self.recv(), timeout=timeout)

    def send_bytes_from_thread(self, data: bytes, timeout: "float | None" = None):
        """:meth:`send_bytes` for a caller outside the loop."""
        return self._session.call(self.send_bytes(data), timeout=timeout)

    def close_from_thread(self, timeout: "float | None" = 5.0) -> None:
        """:meth:`close` for a caller outside the loop."""
        self._session.call(self.close(), timeout=timeout)

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


class AgentSession:
    """One device's live channel and the streams on it.

    Attributes:
        key: The device key.
        hostname: What the machine called itself in its hello.
        platform: The platform tuple it reported.
        address: Where its channel comes from.
        version: The agent release it reported.
        report: The most recent report, whole.
        reported_at: The monotonic reading of that report.
        state_hash: The desired-state hash the agent last claimed.
        loop: The loop the socket is served on.
    """

    def __init__(
        self,
        *,
        key: str,
        websocket,
        loop: asyncio.AbstractEventLoop,
        hostname: str = "",
        platform: "dict | None" = None,
        address: str = "",
        version: str = "",
    ):
        self.key = key.lower()
        self.hostname = hostname
        self.platform = dict(platform or {})
        self.address = address
        self.version = version
        self.report: dict = {}
        self.reported_at = 0.0
        self.state_hash = ""
        self.loop = loop
        self.opened_at = time.monotonic()
        self._websocket = websocket
        self._streams: dict[str, AgentStream] = {}
        self._pending: dict[str, asyncio.Future] = {}
        self._ids = itertools.count(1)
        self._send_lock = asyncio.Lock()
        self._is_closed = False

    @property
    def is_closed(self) -> bool:
        """Whether the socket is gone."""
        return self._is_closed

    async def send_json(self, message: dict) -> None:
        """Send one text frame.

        Args:
            message: The JSON object, ``type`` included.

        Raises:
            AgentOfflineError: If the socket is gone.
        """
        await self._send(text=json.dumps(message))

    async def send_bytes(self, stream_id: str, data: bytes) -> None:
        """Send one binary frame on a stream.

        Args:
            stream_id: The stream the bytes belong to.
            data: The bytes.

        Raises:
            AgentOfflineError: If the socket is gone.
        """
        await self._send(data=stream_id.encode("ascii") + data)

    async def open_stream(
        self, kind: str, args: dict, credit: int = AGENT_WS_STREAM_CREDIT_BYTES
    ) -> AgentStream:
        """Open a stream on the agent and wait for its answer.

        Args:
            kind: The stream kind.
            args: What the kind takes.
            credit: How many bytes the agent may send before waiting.

        Returns:
            The opened stream.

        Raises:
            AgentOfflineError: If the socket is gone.
            StreamRefusedError: When the agent refused, or did not answer
                in time.
        """
        if self._is_closed:
            raise AgentOfflineError(self.key)
        stream_id = f"{next(self._ids):0{AGENT_WS_STREAM_ID_LENGTH}x}"
        stream = AgentStream(self, stream_id, kind)
        future = self.loop.create_future()
        self._streams[stream_id] = stream
        self._pending[stream_id] = future
        try:
            await self.send_json(
                {
                    "type": "open",
                    "stream": stream_id,
                    "kind": kind,
                    "args": dict(args),
                    "credit": int(credit),
                }
            )
            await asyncio.wait_for(future, AGENT_WS_OPEN_TIMEOUT_S)
        except asyncio.TimeoutError:
            self._streams.pop(stream_id, None)
            raise StreamRefusedError(CODE_STREAM_OPEN_TIMEOUT, {"kind": kind})
        except (AgentOfflineError, StreamRefusedError):
            self._streams.pop(stream_id, None)
            raise
        finally:
            self._pending.pop(stream_id, None)
        return stream

    def record_report(self, report: dict) -> None:
        """Keep the agent's latest report.

        Args:
            report: The whole ``report`` message.
        """
        self.report = dict(report)
        self.reported_at = time.monotonic()
        self.state_hash = str(report.get("state_hash", "") or "")
        platform = report.get("platform")
        if isinstance(platform, dict) and platform:
            self.platform = dict(platform)

    def dispatch_text(self, message: dict) -> bool:
        """Route one stream message from the agent.

        Args:
            message: The decoded frame.

        Returns:
            True when the message was about a stream; False for a type the
            caller handles itself.
        """
        kind = message.get("type")
        if kind not in STREAM_MESSAGE_TYPES:
            return False
        stream_id = str(message.get("stream", ""))
        stream = self._streams.get(stream_id)
        if stream is None:
            return True
        if kind == "opened":
            future = self._pending.get(stream_id)
            if future is not None and not future.done():
                future.set_result(None)
        elif kind == "refused":
            future = self._pending.get(stream_id)
            self._streams.pop(stream_id, None)
            if future is not None and not future.done():
                future.set_exception(
                    StreamRefusedError(
                        str(message.get("code", "") or "stream_refused"),
                        message.get("params") or {},
                    )
                )
        elif kind == "event":
            stream._deliver(("event", message))
        elif kind == "credit":
            stream._grant(message.get("bytes", 0))
        elif kind == "close":
            self._streams.pop(stream_id, None)
            info = {
                name: value
                for name, value in message.items()
                if name not in ("type", "stream")
            }
            stream._finish(info)
        return True

    def dispatch_bytes(self, data: bytes) -> None:
        """Route one binary frame to its stream.

        Args:
            data: The frame: the stream id, then the bytes.
        """
        stream_id = data[:AGENT_WS_STREAM_ID_LENGTH].decode("ascii", "replace")
        stream = self._streams.get(stream_id)
        if stream is not None:
            stream._deliver(("data", bytes(data[AGENT_WS_STREAM_ID_LENGTH:])))

    def fail_streams(self, code: str = CODE_AGENT_OFFLINE) -> None:
        """End every stream and every pending open with one code.

        Args:
            code: What each stream closes with.
        """
        self._is_closed = True
        for stream_id, future in list(self._pending.items()):
            if not future.done():
                future.set_exception(StreamRefusedError(code, {"device": self.key}))
        self._pending.clear()
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
            raise StreamRefusedError(CODE_STREAM_TIMEOUT, {"device": self.key})

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


class AgentSessionRegistry:
    """The live sessions, keyed by device.

    Attributes:
        loop: The loop the sessions are served on, known once one attaches.
    """

    def __init__(self):
        self.loop: "asyncio.AbstractEventLoop | None" = None
        self._lock = threading.Lock()
        self._sessions: dict[str, AgentSession] = {}

    async def attach(self, session: AgentSession) -> None:
        """Make a session the device's current one.

        Args:
            session: The session that just said hello. An older session
                for the same device is closed with the replaced code.
        """
        with self._lock:
            previous = self._sessions.get(session.key)
            self._sessions[session.key] = session
            self.loop = session.loop
        if previous is not None and previous is not session:
            await previous.close(AGENT_WS_CLOSE_REPLACED, "replaced")

    def detach(self, session: AgentSession) -> bool:
        """Drop a session, only when it is still the device's current one.

        Args:
            session: The session whose socket ended.

        Returns:
            True when this was the current session; False for one already
            replaced, whose device is still online through its successor.
        """
        with self._lock:
            if self._sessions.get(session.key) is not session:
                return False
            self._sessions.pop(session.key, None)
        session.fail_streams()
        return True

    def get(self, key: str) -> "AgentSession | None":
        """The device's session, or None while it is offline."""
        with self._lock:
            return self._sessions.get((key or "").lower())

    def is_online(self, key: str) -> bool:
        """Whether the device has a live channel."""
        return self.get(key) is not None

    def keys(self) -> list:
        """Every device with a live channel."""
        with self._lock:
            return list(self._sessions)

    def reports(self) -> dict:
        """The latest report of every online device, by key."""
        with self._lock:
            return {key: session.report for key, session in self._sessions.items()}

    async def open_stream(self, key: str, kind: str, args: dict) -> AgentStream:
        """Open a stream on one device.

        Args:
            key: The device.
            kind: The stream kind.
            args: What the kind takes.

        Returns:
            The opened stream.

        Raises:
            AgentOfflineError: When the device has no channel.
            StreamRefusedError: When the agent refused or did not answer.
        """
        return await self._require(key).open_stream(kind, args)

    async def push_state(self, key: str, state_hash: str, desired: dict) -> None:
        """Send a device its desired state.

        Args:
            key: The device.
            state_hash: The hash of the state.
            desired: The state itself.

        Raises:
            AgentOfflineError: When the device has no channel.
        """
        await self._require(key).send_json(
            {"type": "state", "hash": state_hash, "desired": dict(desired)}
        )

    async def run_command(
        self, key: str, action: str, args: "dict | None" = None, on_line=None
    ) -> dict:
        """Run one command on a device and wait for its close.

        Args:
            key: The device.
            action: The command's action.
            args: The action's arguments.
            on_line: Called with each output line as it arrives.

        Returns:
            What the agent closed the stream with.

        Raises:
            AgentOfflineError: When the device has no channel, or the socket
                ends before the close.
            StreamRefusedError: When the agent refused the stream.
        """
        stream = await self.open_stream(
            key, STREAM_KIND_COMMAND, {"action": action, "args": dict(args or {})}
        )
        return await self._collect(stream, on_line)

    async def run_order(self, key: str, order: dict, on_line=None) -> dict:
        """Run one module order on a device and wait for its close.

        Args:
            key: The device.
            order: The order on the wire, as ``AgentModuleOrder.to_wire``.
            on_line: Called with each output line as it arrives.

        Returns:
            What the agent closed the stream with.

        Raises:
            AgentOfflineError: When the device has no channel, or the socket
                ends before the close.
            StreamRefusedError: When the agent refused the stream.
        """
        stream = await self.open_stream(key, STREAM_KIND_ORDER, order)
        return await self._collect(stream, on_line)

    def open_stream_from_thread(
        self, key: str, kind: str, args: dict, timeout: "float | None" = None
    ) -> AgentStream:
        """:meth:`open_stream` for a caller outside the loop."""
        session = self._require(key)
        return session.call(session.open_stream(kind, args), timeout=timeout)

    def push_state_from_thread(
        self, key: str, state_hash: str, desired: dict, timeout: "float | None" = 5.0
    ) -> None:
        """:meth:`push_state` for a caller outside the loop."""
        session = self._require(key)
        session.call(self.push_state(key, state_hash, desired), timeout=timeout)

    def run_command_from_thread(
        self,
        key: str,
        action: str,
        args: "dict | None" = None,
        on_line=None,
        timeout: "float | None" = None,
    ) -> dict:
        """:meth:`run_command` for a caller outside the loop."""
        session = self._require(key)
        return session.call(
            self.run_command(key, action, args, on_line), timeout=timeout
        )

    def run_order_from_thread(
        self, key: str, order: dict, on_line=None, timeout: "float | None" = None
    ) -> dict:
        """:meth:`run_order` for a caller outside the loop."""
        session = self._require(key)
        return session.call(self.run_order(key, order, on_line), timeout=timeout)

    def close_from_thread(self, key: str, code: int, reason: str = "") -> None:
        """Close a device's socket from outside the loop, if it has one."""
        session = self.get(key)
        if session is None:
            return
        try:
            session.call(session.close(code, reason), timeout=5.0)
        except (StreamRefusedError, RuntimeError):
            return

    def _require(self, key: str) -> AgentSession:
        session = self.get(key)
        if session is None:
            raise AgentOfflineError((key or "").lower())
        return session

    async def _collect(self, stream: AgentStream, on_line) -> dict:
        """Read a stream to its close, handing lines on.

        Args:
            stream: The stream.
            on_line: Called with each event line, or None.

        Returns:
            The close info.

        Raises:
            AgentOfflineError: When the socket ended before the close.
        """
        while True:
            item = await stream.recv()
            if item is None:
                break
            if item[0] == "event" and on_line is not None:
                on_line(str(item[1].get("line", "")))
        if stream.is_abandoned:
            raise AgentOfflineError(stream._session.key)
        return dict(stream.close_info or {})
