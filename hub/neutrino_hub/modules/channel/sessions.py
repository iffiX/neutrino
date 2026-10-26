"""Live sessions: one per binding, held by the transport and judged here.

The transport holds every peer's session and relays every stream's bytes;
the hub's Python keeps, for each admitted session, what the rest of the hub
asks: whether a binding is online, what software it runs, when its last
session ended, its latest report, and the way to push its state, send it a
frame or open a stream on it (protocol.md, "The local channel"). Presence
is memory alone. Routes on the hub's loop await the session directly;
threadpool routes and worker threads go through the ``*_from_thread``
methods.
"""

import asyncio
import concurrent.futures
import threading
from datetime import datetime, timezone

from neutrino_hub.exceptions import AgentOfflineError, StreamRefusedError
from neutrino_hub.modules.channel.constants import (
    CHANNEL_CALL_TIMEOUT_S,
    CHANNEL_CODE_NEVER_REPORTED,
    CHANNEL_COMMAND_SESSION_CLOSE,
    CHANNEL_COMMAND_STREAMS_CLOSE,
    CHANNEL_FRAME_STATE,
)


def _now() -> str:
    """The current time as an ISO 8601 stamp in UTC."""
    return datetime.now(timezone.utc).isoformat()


def version_of_software(software: str) -> str:
    """The version a ``software`` field names, empty when it names none."""
    _, separator, version = software.partition("/")
    return version if separator else ""


class ChannelSession:
    """One binding's live session on the transport.

    Attributes:
        key: The binding id.
        role: What is on the other end, ``agent`` or ``client``.
        session_id: The transport's id of the session.
        name: What the peer called itself in its hello.
        software: The package and version the hello named.
        address: Where its connection comes from.
        listener: The listener it arrived on, ``main`` or a frp vendor's.
        report: The most recent report, whole.
        reported_at: When that report arrived, as an ISO stamp; empty
            before the first one.
        state_hash: The state hash the peer last claimed.
        offered_hash: The hash of the state this session was last handed;
            None before the first report was judged.
        is_admitted: True once its hello was answered with welcome.
        loop: The loop the session is served on.
    """

    def __init__(
        self,
        *,
        key: str,
        role: str,
        session_id: str,
        channel,
        loop: asyncio.AbstractEventLoop,
        name: str = "",
        software: str = "",
        address: str = "",
        listener: str = "",
    ):
        """
        Args:
            key: The binding id.
            role: ``agent`` or ``client``.
            session_id: The transport's id of the session.
            channel: The :class:`LocalChannelClient` the frames go through.
            loop: The loop the session is served on.
            name: The peer's name from its hello.
            software: The peer's software from its hello.
            address: The peer's address.
            listener: The listener it arrived on.
        """
        self.key = key
        self.role = role
        self.session_id = session_id
        self.name = name
        self.software = software
        self.address = address
        self.listener = listener
        self.report: dict = {}
        self.reported_at = ""
        self.report_serial = 0
        self.state_hash = ""
        self.offered_hash: "str | None" = None
        self.is_admitted = False
        self.loop = loop
        self._channel = channel
        self._reported = asyncio.Event()
        self._is_closed = False

    @property
    def is_closed(self) -> bool:
        """Whether the session ended."""
        return self._is_closed

    @property
    def version(self) -> str:
        """The version the peer's software names, empty when it names none."""
        return version_of_software(self.software)

    async def send_json(self, message: dict, *, is_last: bool = False) -> None:
        """Send one frame on the session's control stream.

        Args:
            message: The frame, ``type`` included.
            is_last: Whether the transport ends the session once it is written.

        Raises:
            AgentOfflineError: If the session is gone.
        """
        if self._is_closed:
            raise AgentOfflineError(self.key)
        await self._channel.send_frame(self.session_id, message, is_last=is_last)

    async def open_stream(self, kind: str, args: dict):
        """Open a stream on the peer, as the hub's own.

        Args:
            kind: The stream kind.
            args: What the kind takes, sent beside it in the open.

        Returns:
            The :class:`ChannelStream`, past the peer's ``accept`` or its
            refusing ``close``, which ``close_info`` then holds.

        Raises:
            AgentOfflineError: If the session is gone.
        """
        if self._is_closed:
            raise AgentOfflineError(self.key)
        return await self._channel.open_stream(
            self.session_id, {"kind": kind, **args}, peer_key=self.key
        )

    async def push_state(self, document: dict) -> None:
        """Send the peer its state.

        Args:
            document: The state with its ``hash`` and sections.

        Raises:
            AgentOfflineError: If the session is gone.
        """
        await self.send_json({"type": CHANNEL_FRAME_STATE, **document})
        self.offered_hash = str(document.get("hash", "") or "")

    async def refuse(self, code: str, params: "dict | None" = None) -> None:
        """Turn the peer away: the transport sends ``refused`` and ends the session.

        Args:
            code: Why.
            params: What the code's wording names.
        """
        if self._is_closed:
            return
        self._is_closed = True
        try:
            await self._channel.send_command(
                CHANNEL_COMMAND_SESSION_CLOSE,
                session=self.session_id,
                code=code,
                params=dict(params or {}),
            )
        except StreamRefusedError:
            return

    async def close_streams(
        self,
        *,
        kind: str,
        code: str,
        params: "dict | None" = None,
        device_id: str = "",
        session_id: str = "",
    ) -> None:
        """Close every stream of this binding the transport holds under one kind.

        Args:
            kind: The permission kind the streams fall under.
            code: What each stream closes with.
            params: What the code's wording names.
            device_id: The machine the streams reach; empty for every one.
            session_id: The kept shell the streams are attached to; empty
                for every one.

        Raises:
            StreamRefusedError: When the transport did not take the command.
        """
        await self._channel.send_command(
            CHANNEL_COMMAND_STREAMS_CLOSE,
            binding_id=self.key,
            kind=kind,
            device_id=device_id,
            session_id=session_id,
            code=code,
            params=dict(params or {}),
        )

    def record_report(self, report: dict) -> None:
        """Keep the peer's latest report.

        Args:
            report: The whole ``report`` frame.
        """
        self.report = dict(report)
        self.reported_at = _now()
        self.state_hash = str(report.get("state_hash", "") or "")

    def note_report_recorded(self) -> None:
        """Count a report once everything read from it is in place."""
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
            out or the session ended.
        """
        while self.report_serial <= after_serial and not self._is_closed:
            try:
                await asyncio.wait_for(self._reported.wait(), timeout)
            except asyncio.TimeoutError:
                return False
        return self.report_serial > after_serial

    def mark_ended(self) -> None:
        """Note that the transport ended the session."""
        self._is_closed = True
        self._reported.set()

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


class ChannelSessionRegistry:
    """The live sessions of one role, keyed by binding id.

    Attributes:
        role: The one role this registry holds.
        loop: The loop the sessions are served on, known once one attaches.
        on_presence_change: Called with nothing whenever a binding's session
            opens or ends. The registry knows nothing of the panel; whoever
            wants to hear sets this.
    """

    def __init__(self, role: str):
        self.role = role
        self.loop: "asyncio.AbstractEventLoop | None" = None
        self.on_presence_change = None
        self._lock = threading.Lock()
        self._sessions: dict[str, ChannelSession] = {}
        self._software: dict[str, str] = {}
        self._ended_at: dict[str, str] = {}

    def attach(self, session: ChannelSession) -> None:
        """Make a session the binding's current one.

        An older session of the same binding is left to the transport, which
        ends it with ``replaced`` as it admits the newer one.

        Args:
            session: The session whose hello was admitted.

        Raises:
            ValueError: When the session is of another role than this
                registry holds.
        """
        if session.role != self.role:
            raise ValueError(f"{session.role} session in a {self.role} registry")
        session.is_admitted = True
        with self._lock:
            previous = self._sessions.get(session.key)
            self._sessions[session.key] = session
            self._software[session.key] = session.software
            self._ended_at.pop(session.key, None)
            self.loop = session.loop
        if previous is not None and previous is not session:
            previous.mark_ended()
        self._note_presence()

    def detach(self, session: ChannelSession) -> bool:
        """Drop a session, only when it is still the binding's current one.

        Args:
            session: The session the transport ended.

        Returns:
            True when this was the current session; False for one already
            replaced, whose binding is still online through its successor.
        """
        session.mark_ended()
        with self._lock:
            if self._sessions.get(session.key) is not session:
                return False
            self._sessions.pop(session.key, None)
            self._ended_at[session.key] = _now()
        self._note_presence()
        return True

    def get(self, key: str) -> "ChannelSession | None":
        """The binding's session, or None while it is offline."""
        with self._lock:
            return self._sessions.get(key or "")

    def by_session_id(self, session_id: str) -> "ChannelSession | None":
        """The session the transport names, or None."""
        with self._lock:
            for session in self._sessions.values():
                if session.session_id == session_id:
                    return session
        return None

    def is_online(self, key: str) -> bool:
        """Whether the binding has a live session."""
        return self.get(key) is not None

    def last_seen_at(self, key: str) -> "str | None":
        """When the binding's last session ended; None while online or never seen."""
        with self._lock:
            return self._ended_at.get(key or "")

    def last_report_at(self, key: str) -> "str | None":
        """When the binding's last report arrived; None offline or before the first."""
        session = self.get(key)
        if session is None or not session.reported_at:
            return None
        return session.reported_at

    def software_of(self, key: str) -> str:
        """The software the binding's last hello named, kept after the session ends."""
        with self._lock:
            return self._software.get(key or "", "")

    def version_of(self, key: str) -> str:
        """The version the binding's last hello named, empty for none."""
        return version_of_software(self.software_of(key))

    def keys(self) -> list:
        """Every binding with a live session."""
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

    async def open_stream(self, key: str, kind: str, args: dict):
        """Open a stream on one binding.

        Raises:
            AgentOfflineError: When the binding has no session.
        """
        return await self._require(key).open_stream(kind, args)

    async def push_state(self, key: str, document: dict) -> None:
        """Send a binding its state.

        Raises:
            AgentOfflineError: When the binding has no session.
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
            on_chunk: Called with each data record's bytes as they arrive.

        Returns:
            The close, ``{"code", "params"}``.

        Raises:
            AgentOfflineError: When the binding has no session, or the
                session ends before the close.
        """
        stream = await self.open_stream(key, kind, args)
        if payload and stream.is_accepted:
            await stream.send_bytes(payload)
        return await self._collect(stream, on_chunk)

    def open_stream_from_thread(
        self, key: str, kind: str, args: dict, timeout: "float | None" = None
    ):
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
        """How many reports the binding's live session has counted, 0 offline."""
        session = self.get(key)
        return session.report_serial if session is not None else 0

    def wait_for_report_from_thread(
        self, key: str, after_serial: int, timeout: float
    ) -> bool:
        """:meth:`ChannelSession.wait_for_report` for a caller outside the loop.

        Returns:
            True when a newer report was recorded; False when the wait ran
            out, the session ended, or the binding is offline.
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
        """Hand one frame to a session from outside the loop, not waiting.

        Returns:
            True when the frame was queued on a live session; False when
            there is none.
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
        """Turn a binding's live session away from outside the loop, if it has one."""
        session = self.get(key)
        if session is None:
            return
        try:
            session.call(session.refuse(code, params), timeout=5.0)
        except (StreamRefusedError, RuntimeError):
            return

    def close_streams_from_thread(
        self,
        key: str,
        *,
        kind: str,
        code: str,
        params: "dict | None" = None,
        device_id: str = "",
        session_id: str = "",
    ) -> bool:
        """:meth:`ChannelSession.close_streams` for a caller outside the loop.

        Returns:
            True when the transport took the command; False when the binding
            is offline or the transport refused it.
        """
        session = self.get(key)
        if session is None:
            return False
        try:
            session.call(
                session.close_streams(
                    kind=kind,
                    code=code,
                    params=params,
                    device_id=device_id,
                    session_id=session_id,
                ),
                timeout=CHANNEL_CALL_TIMEOUT_S,
            )
        except (StreamRefusedError, RuntimeError):
            return False
        return True

    def _note_presence(self) -> None:
        """Say a binding came or went, where anybody asked to be told."""
        if self.on_presence_change is not None:
            self.on_presence_change()

    def _require(self, key: str) -> ChannelSession:
        session = self.get(key)
        if session is None:
            raise AgentOfflineError(key or "")
        return session

    async def _collect(self, stream, on_chunk) -> dict:
        """Read a stream to its close, handing bytes on.

        Raises:
            AgentOfflineError: When the session ended before the close.
        """
        while True:
            item = await stream.recv()
            if item is None:
                break
            if on_chunk is not None and item[0] == "data":
                on_chunk(item[1])
        if stream.is_abandoned:
            raise AgentOfflineError(stream.args.get("device", "") or "")
        return dict(stream.close_info or {})
