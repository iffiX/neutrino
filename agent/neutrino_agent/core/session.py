"""One connection to the hub, from its hello to its last frame.

The socket carries everything: the hello that opens it and the welcome that
answers, a report every few seconds and at once when something changed, the
hub's state whenever its copy changes, and every stream either side opens.
A reader thread takes frames off the socket and dispatches them; the
caller's thread runs the report loop; each stream the hub opens runs on a
thread of its own so a long command never blocks the reader.

A stream exists as soon as its open arrives, and its close is its result:
``{stream, code, params}``, with a code making it a refusal. The hub's
streams number even, this side's odd. Every stream sits behind a
:class:`StreamChannel`: bytes go out no faster than the hub's credit
allows, and a stream's text output is its binary frames, one line each.
The kind table of :mod:`neutrino_agent.streams` is the whole vocabulary:
an open whose kind is not in it is closed ``kind_unknown``.

Errors cross the wire as ``{"code", "params"}``, never an English sentence;
every surface does its own wording.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import functools
import json
import threading

from neutrino_agent.constants import (
    AGENT_CODE_CHANNEL_REFUSED,
    AGENT_REPORT_INTERVAL_S,
    AGENT_HUB_ROLE,
    AGENT_WS_STREAM_ID_BYTES,
)
from neutrino_agent.core.ws_client import close_error
from neutrino_agent.exceptions import (
    GatewayRefusedDetail,
    GatewayUnreachable,
    SocketClosed,
    StreamClosed,
    StreamRefused,
)
from neutrino_agent.streams import STREAM_KIND_COMMAND, STREAM_KINDS
from neutrino_agent.streams.channel import StreamChannel

# The fields of an open that are not the kind's own arguments.
OPEN_ENVELOPE_FIELDS = ("type", "stream", "kind")
# The first id this side allots; the hub counts from an even one.
FIRST_OWN_STREAM_ID = 1
STREAM_ID_LIMIT = 1 << (8 * AGENT_WS_STREAM_ID_BYTES)


class AgentSession:
    """The live socket: hello, reports, and the streams on it.

    Attributes:
        hub_id: The hub's id, from the welcome; empty until it arrived.
        hub_name: The hub's name, from the welcome.
        hub_software: The hub's ``software``, from the welcome.
        state_hash: The hash the last state frame named.
    """

    def __init__(
        self,
        *,
        client,
        hello: dict,
        report,
        run_command,
        news: threading.Event,
        log=print,
        interval_s: float = AGENT_REPORT_INTERVAL_S,
        on_tick=None,
        on_state=None,
        stream_kinds=None,
    ):
        """
        Args:
            client: A connected-or-not ``WebSocketClient``.
            hello: The identity card the hello carries: ``{protocol, role,
                id, name, software, token}``.
            report: Called for each report's body.
            run_command: Called with ``(module, verb, args, on_line)`` for
                each ``command`` stream; returns ``{"exit_code", "code",
                "params", "output"}``, with ``result`` beside them for a
                verb that reads.
            news: Set whenever a report should go up at once.
            log: Callable used for progress messages.
            interval_s: How often a report goes up while nothing changes.
            on_tick: Called once per report interval, before the report.
            on_state: Called with the state document, ``{hash, modules,
                desktop}``, for each state frame the hub sends. None takes
                the hash and nothing else.
            stream_kinds: Stream kind to its handler factory, called with
                ``(channel, args)``. A handler has ``open()``, which may
                raise :class:`StreamRefused`, and ``run()``, which returns
                ``{"code", "params"}``, what the stream closes with. The
                command kind's factory is bound to ``run_command``. None
                serves the kinds of :mod:`neutrino_agent.streams`.
        """
        self._client = client
        self._hello = dict(hello)
        self._report = report
        self._run_command = run_command
        self._news = news
        self._log = log
        self._interval_s = interval_s
        self._on_tick = on_tick
        self._on_state = on_state
        kinds = dict(STREAM_KINDS if stream_kinds is None else stream_kinds)
        if STREAM_KIND_COMMAND in kinds:
            kinds[STREAM_KIND_COMMAND] = functools.partial(
                kinds[STREAM_KIND_COMMAND], run=run_command
            )
        self._stream_kinds = kinds
        self.hub_id = ""
        self.hub_name = ""
        self.hub_software = ""
        self.state_hash = ""
        self._lock = threading.Lock()
        self._is_closed = threading.Event()
        self._failure: "Exception | None" = None
        self._channels: dict = {}
        self._next_stream_id = FIRST_OWN_STREAM_ID
        self._reader: "threading.Thread | None" = None

    @property
    def is_open(self) -> bool:
        """Whether the socket is up and the welcome has arrived."""
        return self._reader is not None and not self._is_closed.is_set()

    @property
    def local_address(self) -> str:
        """This machine's own address on the socket, empty while it is closed."""
        return self._client.local_address

    def connect(self) -> None:
        """Connect, say hello, and take the welcome.

        Raises:
            GatewayUntrusted: When the peer failed the fingerprint check.
            GatewayRefusedDetail: When the hub answered ``refused``, with
                its code and params, or closed 4000 without one.
            GatewayUnreachable: On any network error, or a first frame that
                is neither a welcome from a hub nor a refusal.
        """
        self._client.connect()
        try:
            self._send({"type": "hello", **self._hello})
            welcome = self._take_welcome()
        except SocketClosed as closed:
            raise close_error(closed.code, closed.reason) from closed
        except Exception:
            self._client.close()
            raise
        self.hub_id = str(welcome.get("id", "") or "")
        self.hub_name = str(welcome.get("name", "") or "")
        self.hub_software = str(welcome.get("software", "") or "")
        self._reader = threading.Thread(
            target=self._read_forever, name="agent_session_reader", daemon=True
        )
        self._reader.start()

    def serve(self) -> "Exception | None":
        """Report until the socket ends.

        Returns:
            What ended it: the gateway error the close or the wire failure
            maps to, or None when :meth:`close` ended it from here.
        """
        while not self._is_closed.is_set():
            try:
                self._send({"type": "report", **self._report()})
            except GatewayUnreachable as error:
                self._end(error)
                break
            self._news.wait(timeout=self._interval_s)
            self._news.clear()
            if self._on_tick is not None:
                self._on_tick()
        if self._reader is not None:
            self._reader.join(timeout=self._interval_s)
        return self._failure

    def close(self) -> None:
        """End the socket from this side."""
        self._is_closed.set()
        self._client.close()
        self._news.set()

    def resize_stream(self, stream_id, cols: int, rows: int) -> bool:
        """Give one stream the hub opened a new terminal size.

        Args:
            stream_id: The stream's id.
            cols: The new width.
            rows: The new height.

        Returns:
            True when a live stream of that id took it.
        """
        channel = self._channel(stream_id)
        if channel is None:
            return False
        channel._feed(("resize", int(cols), int(rows)))
        return True

    def open_stream(self, kind: str, **args) -> StreamChannel:
        """Open a stream to the hub, on the next odd id.

        Args:
            kind: The stream kind.
            **args: The kind's arguments, sent beside it in the open.

        Returns:
            The stream's channel; closing it ends the stream with its result.

        Raises:
            GatewayUnreachable: When the socket is gone.
        """
        with self._lock:
            stream_id = self._next_stream_id
            self._next_stream_id += 2
            channel = StreamChannel(self, stream_id)
            self._channels[stream_id] = channel
        try:
            self._send({"type": "open", "stream": stream_id, "kind": kind, **args})
        except GatewayUnreachable:
            with self._lock:
                self._channels.pop(stream_id, None)
            raise
        return channel

    def _take_welcome(self) -> dict:
        """The hub's first frame: its identity card, or why it said no."""
        kind, payload = self._client.recv()
        message = _decode(kind, payload)
        if message is None:
            raise GatewayUnreachable("the hub's first frame is not a welcome")
        if message.get("type") == "refused":
            params = message.get("params")
            raise GatewayRefusedDetail(
                code=str(message.get("code", "") or "") or AGENT_CODE_CHANNEL_REFUSED,
                params=dict(params) if isinstance(params, dict) else {},
            )
        if message.get("type") != "welcome" or message.get("role") != AGENT_HUB_ROLE:
            raise GatewayUnreachable("the hub's first frame is not a hub's welcome")
        return message

    def _send(self, message: dict) -> None:
        self._client.send_text(json.dumps(message))

    def _send_bytes(self, stream_id: int, data: bytes) -> None:
        self._client.send_bytes(
            stream_id.to_bytes(AGENT_WS_STREAM_ID_BYTES, "big") + data
        )

    def _close_stream(self, stream_id: int, code: str, params: dict) -> None:
        """Send a stream's close and forget it."""
        with self._lock:
            self._channels.pop(stream_id, None)
        self._send(
            {"type": "close", "stream": stream_id, "code": code, "params": params}
        )

    def _end(self, failure: "Exception | None") -> None:
        with self._lock:
            if self._failure is None:
                self._failure = failure
            channels = list(self._channels.values())
        self._is_closed.set()
        self._client.close()
        self._news.set()
        for channel in channels:
            channel._end()

    def _read_forever(self) -> None:
        while not self._is_closed.is_set():
            try:
                kind, payload = self._client.recv()
            except SocketClosed as closed:
                if not self._is_closed.is_set():
                    self._end(close_error(closed.code, closed.reason))
                return
            except GatewayUnreachable as error:
                if not self._is_closed.is_set():
                    self._end(error)
                return
            try:
                self._dispatch(kind, payload)
            except Exception as error:  # noqa: BLE001 - the reader must survive
                self._log(f"could not handle a frame from the hub: {error}")

    def _dispatch(self, kind: str, payload) -> None:
        if kind == "binary":
            self._dispatch_bytes(payload)
            return
        message = _decode(kind, payload)
        if message is None:
            return
        message_type = message.get("type")
        stream_id = message.get("stream")
        if message_type == "open":
            self._open(message)
        elif message_type == "close":
            with self._lock:
                channel = self._channels.pop(stream_id, None)
            if channel is not None:
                params = message.get("params")
                channel._end(
                    str(message.get("code", "") or ""),
                    dict(params) if isinstance(params, dict) else {},
                )
        elif message_type == "state":
            self.state_hash = str(message.get("hash", "") or "")
            if self._on_state is not None:
                self._on_state(
                    {key: value for key, value in message.items() if key != "type"}
                )
        elif message_type == "credit":
            channel = self._channel(stream_id)
            if channel is not None:
                channel._grant(message.get("bytes", 0))
        else:
            self._log(f"ignoring a {message_type!r} frame from the hub")

    def _dispatch_bytes(self, payload: bytes) -> None:
        if len(payload) < AGENT_WS_STREAM_ID_BYTES:
            self._log(f"dropping a binary frame of {len(payload)} bytes")
            return
        stream_id = int.from_bytes(payload[:AGENT_WS_STREAM_ID_BYTES], "big")
        channel = self._channel(stream_id)
        if channel is not None:
            channel._feed(("data", bytes(payload[AGENT_WS_STREAM_ID_BYTES:])))

    def _channel(self, stream_id) -> "StreamChannel | None":
        with self._lock:
            return self._channels.get(stream_id)

    def _open(self, message: dict) -> None:
        """Serve one stream the hub opened: the kind table decides how."""
        stream_id = message.get("stream")
        if not isinstance(stream_id, int) or not 0 <= stream_id < STREAM_ID_LIMIT:
            self._log(f"dropping an open with stream id {stream_id!r}")
            return
        kind = str(message.get("kind", ""))
        args = {
            key: value
            for key, value in message.items()
            if key not in OPEN_ENVELOPE_FIELDS
        }
        factory = self._stream_kinds.get(kind)
        if factory is None:
            self._close_stream(stream_id, "kind_unknown", {"kind": kind})
            return
        channel = StreamChannel(self, stream_id)
        with self._lock:
            self._channels[stream_id] = channel
        threading.Thread(
            target=self._serve_channel,
            args=(factory, channel, args),
            name=f"agent_stream_{stream_id}",
            daemon=True,
        ).start()

    def _serve_channel(self, factory, channel: StreamChannel, args: dict) -> None:
        """Open one stream, run it, and close it with its result."""
        try:
            try:
                stream = factory(channel, args)
                stream.open()
            except StreamRefused as refused:
                channel.close(refused.code, dict(refused.params))
                return
            info = stream.run()
        except GatewayUnreachable:
            return
        except StreamClosed:
            info = {"code": "", "params": {}}
        except Exception as error:  # noqa: BLE001 - reported, never fatal
            self._log(f"stream {channel.id} failed: {error}")
            info = {
                "code": "agent_internal",
                "params": {"error": type(error).__name__},
            }
        try:
            channel.close(
                str(info.get("code", "") or ""), dict(info.get("params") or {})
            )
        except GatewayUnreachable:
            return


def _decode(kind: str, payload) -> "dict | None":
    """One text frame as the object it carries, or None."""
    if kind != "text":
        return None
    try:
        message = json.loads(payload)
    except ValueError:
        return None
    return message if isinstance(message, dict) else None
