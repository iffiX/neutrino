"""One connection to the hub, from its hello to its last frame.

The socket carries everything: the hello that opens it and the welcome that
answers, a report every few seconds and at once when something changed, the
hub's desired state, and every stream the hub opens. A reader thread takes
frames off the socket and dispatches them; the caller's thread runs the
report loop; each stream runs on a thread of its own so a long install
never blocks the reader.

Errors cross the wire as ``{"code", "params"}``, never an English sentence;
every surface does its own wording.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import json
import threading

from neutrino_agent import AGENT_VERSION
from neutrino_agent.constants import (
    AGENT_HEARTBEAT_INTERVAL_S,
    AGENT_WIRE_GENERATION,
    AGENT_WS_STREAM_ID_LENGTH,
)
from neutrino_agent.core.channel import GatewayUnreachable
from neutrino_agent.core.ws_client import SocketClosed, close_error

STREAM_KIND_ORDER = "order"
STREAM_KIND_COMMAND = "command"


class AgentSession:
    """The live socket: hello, reports, and the streams the hub opens.

    Attributes:
        hub_version: What the welcome named, empty until it arrived.
        state_hash: The desired-state hash the welcome named.
    """

    def __init__(
        self,
        *,
        client,
        token: str,
        hello: dict,
        report,
        run_order,
        run_command,
        news: threading.Event,
        log=print,
        interval_s: float = AGENT_HEARTBEAT_INTERVAL_S,
        on_tick=None,
    ):
        """
        Args:
            client: A connected-or-not ``WebSocketClient``.
            token: This machine's device token.
            hello: What the hello carries besides its type and token.
            report: Called for each report's body.
            run_order: Called with ``(order, on_line)``; runs one module
                order and returns ``{"state", "code", "params", "output"}``.
            run_command: Called with ``(action, args)``; returns
                ``{"exit_code", "code", "params", "output"}``.
            news: Set whenever a report should go up at once.
            log: Callable used for progress messages.
            interval_s: How often a report goes up while nothing changes.
            on_tick: Called once per report interval, before the report.
        """
        self._client = client
        self._token = token
        self._hello = dict(hello)
        self._report = report
        self._run_order = run_order
        self._run_command = run_command
        self._news = news
        self._log = log
        self._interval_s = interval_s
        self._on_tick = on_tick
        self.hub_version = ""
        self.state_hash = ""
        self._lock = threading.Lock()
        self._is_closed = threading.Event()
        self._failure: "Exception | None" = None
        self._open_streams: set = set()
        self._reader: "threading.Thread | None" = None

    @property
    def is_open(self) -> bool:
        """Whether the socket is up and the welcome has arrived."""
        return self._reader is not None and not self._is_closed.is_set()

    def connect(self) -> None:
        """Connect, say hello, and take the welcome.

        Raises:
            GatewayUntrusted: When the peer failed the fingerprint check.
            GatewayRefused: When the hub does not know this token.
            GatewayWireStale: When the hub refused this build's wire.
            GatewayVersionRefused: When the hub refused this agent as newer.
            GatewayUnreachable: On any network error, or a first frame that
                is not a welcome.
        """
        self._client.connect()
        try:
            self._send({"type": "hello", "token": self._token, **self._hello_fields()})
            welcome = self._take_welcome()
        except SocketClosed as closed:
            raise close_error(closed.code, closed.reason) from closed
        except Exception:
            self._client.close()
            raise
        self.hub_version = str(welcome.get("hub_version", "") or "")
        self.state_hash = str(welcome.get("state_hash", "") or "")
        self._reader = threading.Thread(
            target=self._read_forever, name="agent_session_reader", daemon=True
        )
        self._reader.start()
        if self.state_hash != str(self._hello.get("state_hash", "") or ""):
            self.request_state()

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

    def request_state(self) -> None:
        """Ask the hub for this machine's desired state.

        Raises:
            GatewayUnreachable: When the socket is gone.
        """
        self._send({"type": "state_request"})

    def close(self) -> None:
        """End the socket from this side."""
        self._is_closed.set()
        self._client.close()
        self._news.set()

    def _hello_fields(self) -> dict:
        fields = dict(self._hello)
        fields.setdefault("client_version", AGENT_VERSION)
        fields.setdefault("wire", AGENT_WIRE_GENERATION)
        fields.setdefault("state_hash", "")
        return fields

    def _take_welcome(self) -> dict:
        kind, payload = self._client.recv()
        message = _decode(kind, payload)
        if message is None or message.get("type") != "welcome":
            raise GatewayUnreachable("the hub's first frame is not a welcome")
        return message

    def _send(self, message: dict) -> None:
        self._client.send_text(json.dumps(message))

    def _end(self, failure: "Exception | None") -> None:
        with self._lock:
            if self._failure is None:
                self._failure = failure
        self._is_closed.set()
        self._client.close()
        self._news.set()

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
            # No stream kind takes bytes downward yet.
            return
        message = _decode(kind, payload)
        if message is None:
            return
        message_type = message.get("type")
        if message_type == "open":
            self._open(message)
        elif message_type == "close":
            with self._lock:
                self._open_streams.discard(str(message.get("stream", "")))
        elif message_type == "state":
            self.state_hash = str(message.get("hash", "") or "")
        elif message_type in ("resize", "credit"):
            return
        else:
            self._log(f"ignoring a {message_type!r} frame from the hub")

    def _open(self, message: dict) -> None:
        stream_id = str(message.get("stream", ""))
        kind = str(message.get("kind", ""))
        args = message.get("args") if isinstance(message.get("args"), dict) else {}
        handlers = {
            STREAM_KIND_ORDER: self._serve_order,
            STREAM_KIND_COMMAND: self._serve_command,
        }
        handler = handlers.get(kind)
        if handler is None or len(stream_id) != AGENT_WS_STREAM_ID_LENGTH:
            self._send(
                {
                    "type": "refused",
                    "stream": stream_id,
                    "code": "unknown_stream_kind",
                    "params": {"kind": kind},
                }
            )
            return
        with self._lock:
            self._open_streams.add(stream_id)
        self._send({"type": "opened", "stream": stream_id})
        threading.Thread(
            target=self._guarded,
            args=(handler, stream_id, args),
            name=f"agent_stream_{stream_id}",
            daemon=True,
        ).start()

    def _guarded(self, handler, stream_id: str, args: dict) -> None:
        try:
            handler(stream_id, args)
        except GatewayUnreachable:
            return
        except Exception as error:  # noqa: BLE001 - reported, never fatal
            self._log(f"stream {stream_id} failed: {error}")
            self._finish(
                stream_id,
                {
                    "state": "failed",
                    "exit_code": 1,
                    "code": "agent_internal",
                    "params": {"error": type(error).__name__},
                    "output": "",
                },
            )

    def _serve_order(self, stream_id: str, args: dict) -> None:
        def on_line(line: str) -> None:
            self._event(stream_id, line)

        result = self._run_order(args, on_line)
        self._finish(
            stream_id,
            {
                "state": str(result.get("state", "failed")),
                "code": str(result.get("code", "") or ""),
                "params": dict(result.get("params") or {}),
                "output": str(result.get("output", "") or ""),
            },
        )

    def _serve_command(self, stream_id: str, args: dict) -> None:
        outcome = self._run_command(
            str(args.get("action", "")),
            args.get("args") if isinstance(args.get("args"), dict) else {},
        )
        self._finish(
            stream_id,
            {
                "exit_code": int(outcome.get("exit_code", 1)),
                "code": str(outcome.get("code", "") or ""),
                "params": dict(outcome.get("params") or {}),
                "output": str(outcome.get("output", "") or ""),
            },
        )

    def _event(self, stream_id: str, line: str) -> None:
        with self._lock:
            if stream_id not in self._open_streams:
                return
        self._send({"type": "event", "stream": stream_id, "line": line})

    def _finish(self, stream_id: str, info: dict) -> None:
        with self._lock:
            self._open_streams.discard(stream_id)
        self._send({"type": "close", "stream": stream_id, **info})


def _decode(kind: str, payload) -> "dict | None":
    """One text frame as the object it carries, or None."""
    if kind != "text":
        return None
    try:
        message = json.loads(payload)
    except ValueError:
        return None
    return message if isinstance(message, dict) else None
