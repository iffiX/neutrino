"""One session the agent's transport holds to the hub, frame by frame.

The transport makes the knock and the handshake and says ``session_open``;
this side then writes ``hello`` and takes the ``welcome``, or the
``refused`` that answers in its place. From then on a report goes up every
few seconds and at once when something changed, the hub's ``state`` goes to
the applier whenever its copy changes, and ``persist`` and
``stop_session`` are answered with a ``reply`` from the kept shells. A
``refused`` frame says why the hub ends the session wherever it arrives.

Every stream the hub opens comes as a ``stream`` event: the session takes
it with an ``attach`` connection, and the kind table of
:mod:`neutrino_agent.streams` decides who serves it. An open whose kind is
not in the table is closed ``kind_unknown``.

Errors cross the wire as ``{"code", "params"}``, never an English sentence;
every surface does its own wording.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import functools
import threading

from neutrino_agent.constants import (
    AGENT_CODE_CHANNEL_REFUSED,
    AGENT_CODE_FRAME_UNREADABLE,
    AGENT_HUB_ROLE,
)
from neutrino_agent.exceptions import (
    GatewayRefusedDetail,
    GatewayUnreachable,
    StreamClosed,
    StreamRefused,
)
from neutrino_agent.modules.shared.hub_clock import welcome_time
from neutrino_agent.streams import STREAM_KIND_COMMAND, STREAM_KINDS

FRAME_HELLO = "hello"
FRAME_WELCOME = "welcome"
FRAME_REFUSED = "refused"
FRAME_STATE = "state"
FRAME_REPORT = "report"
FRAME_PERSIST = "persist"
FRAME_STOP_SESSION = "stop_session"
FRAME_REPLY = "reply"
FRAME_PONG = "pong"
# The fields of an open that are not the kind's own arguments.
OPEN_ENVELOPE_FIELDS = ("kind",)


def refusal_of(frame: dict) -> GatewayRefusedDetail:
    """What one ``refused`` frame, or a session's end with a code, says.

    Args:
        frame: ``{code, params}``.

    Returns:
        The refusal, its code ``channel_refused`` when the frame named none.
    """
    params = frame.get("params")
    return GatewayRefusedDetail(
        code=str(frame.get("code", "") or "") or AGENT_CODE_CHANNEL_REFUSED,
        params=dict(params) if isinstance(params, dict) else {},
    )


def given_flag(frame: dict, key: str) -> "bool | None":
    """A flag a frame carries, or None when it names none."""
    return None if frame.get(key) is None else bool(frame[key])


class AgentSession:
    """The hello, the welcome, the frames and the streams of one session.

    Attributes:
        address: The hub's address the session runs to.
        local_address: This machine's own address on the session's
            connection, which the report names as the link.
        hub_id: The hub's id, from the welcome; empty until it arrived.
        hub_name: The hub's name, from the welcome.
        hub_software: The hub's ``software``, from the welcome.
        hub_time: The hub's clock the welcome named, in seconds since the
            epoch; None until it arrived, and for a welcome naming none.
        refusal: The refusal the hub ended the session with, or None.
    """

    def __init__(
        self,
        *,
        control,
        hello: dict,
        address: str = "",
        local_address: str = "",
        run_command=None,
        shells=None,
        on_state=None,
        on_unreadable=None,
        stream_kinds=None,
        log=print,
    ):
        """
        Args:
            control: The :class:`TransportControlClient` the frames and the
                streams go through.
            hello: The identity card: ``{protocol, role, id, name,
                software}``.
            address: The hub's address the session runs to.
            local_address: This machine's own address on the connection.
            run_command: Called with ``(module, verb, args, on_line)`` for
                each ``command`` stream.
            shells: The kept shells ``persist`` and ``stop_session`` act on;
                None answers both ``session_unknown``.
            on_state: Called with each ``state`` frame's document, ``{hash,
                ...sections}``.
            on_unreadable: Called with ``{code, params}`` for a frame this
                build cannot read.
            stream_kinds: Stream kind to its handler factory, called with
                ``(channel, args)``. None serves the kinds of
                :mod:`neutrino_agent.streams`.
            log: Callable used for progress messages.
        """
        self._control = control
        self._hello = dict(hello)
        self.address = address
        self.local_address = local_address
        self._shells = shells
        self._on_state = on_state
        self._on_unreadable = on_unreadable
        self._log = log
        kinds = dict(STREAM_KINDS if stream_kinds is None else stream_kinds)
        if STREAM_KIND_COMMAND in kinds and run_command is not None:
            kinds[STREAM_KIND_COMMAND] = functools.partial(
                kinds[STREAM_KIND_COMMAND], run=run_command
            )
        self._stream_kinds = kinds
        self.hub_id = ""
        self.hub_name = ""
        self.hub_software = ""
        self.hub_time: "float | None" = None
        self.refusal: "GatewayRefusedDetail | None" = None
        self._is_welcomed = threading.Event()
        self._is_ended = threading.Event()
        self._is_settled = threading.Event()

    @property
    def is_open(self) -> bool:
        """Whether the welcome arrived and the session has not ended."""
        return self._is_welcomed.is_set() and not self._is_ended.is_set()

    @property
    def is_ended(self) -> bool:
        """Whether the session ended."""
        return self._is_ended.is_set()

    def say_hello(self) -> None:
        """Write ``hello``, the session's first frame.

        Raises:
            GatewayUnreachable: When the transport is gone.
        """
        self._control.send_frame({"type": FRAME_HELLO, **self._hello})

    def wait_welcome(self, timeout_s: float) -> bool:
        """Wait for the welcome, or for the session's end.

        Args:
            timeout_s: How long to wait.

        Returns:
            True once the welcome arrived on a session that runs on; False
            when the session ended or the wait ran out first.
        """
        self._is_settled.wait(timeout_s)
        return self.is_open

    def report(self, body: dict) -> None:
        """Send one report.

        Args:
            body: ``{state_hash, ...sections}``.

        Raises:
            GatewayUnreachable: When the transport is gone.
        """
        self._control.send_frame({"type": FRAME_REPORT, **body})

    def end(self, refusal: "GatewayRefusedDetail | None" = None) -> None:
        """Mark the session ended, with the refusal that ended it if any.

        Args:
            refusal: Why the hub ended it; a refusal already recorded stays.
        """
        if refusal is not None and self.refusal is None:
            self.refusal = refusal
        self._is_ended.set()
        self._is_settled.set()

    def take(self, frame: dict) -> None:
        """Act on one frame the hub sent.

        Args:
            frame: ``{type, ...body}``.
        """
        kind = frame.get("type")
        if kind == FRAME_WELCOME:
            self._take_welcome(frame)
        elif kind == FRAME_REFUSED:
            self.end(refusal_of(frame))
        elif kind == FRAME_STATE:
            if self._on_state is not None:
                self._on_state(
                    {key: value for key, value in frame.items() if key != "type"}
                )
        elif kind in (FRAME_PERSIST, FRAME_STOP_SESSION):
            self._answer_session(frame)
        elif kind == FRAME_PONG:
            return
        else:
            self._unreadable(kind)

    def serve_stream(self, stream_id: str, open_record) -> None:
        """Take one stream the hub opened and serve it on a thread of its own.

        Args:
            stream_id: The id the ``stream`` event named.
            open_record: The stream's open, ``{kind, ...args}``.
        """
        record = open_record if isinstance(open_record, dict) else {}
        threading.Thread(
            target=self._serve_stream,
            args=(str(stream_id), record),
            name=f"agent_stream_{stream_id}",
            daemon=True,
        ).start()

    def _take_welcome(self, frame: dict) -> None:
        if frame.get("role") != AGENT_HUB_ROLE:
            self._unreadable(FRAME_WELCOME)
            return
        self.hub_id = str(frame.get("id", "") or "")
        self.hub_name = str(frame.get("name", "") or "")
        self.hub_software = str(frame.get("software", "") or "")
        self.hub_time = welcome_time(frame)
        self._is_welcomed.set()
        self._is_settled.set()

    def _answer_session(self, frame: dict) -> None:
        """Answer ``persist`` or ``stop_session`` with a ``reply``."""
        session_id = str(frame.get("session_id", "") or "")
        if self._shells is None:
            is_known = False
        elif frame.get("type") == FRAME_PERSIST:
            is_known = self._shells.persist(
                session_id,
                is_persistent=given_flag(frame, "is_persistent"),
                is_shared=given_flag(frame, "is_shared"),
            )
        else:
            is_known = self._shells.stop(session_id)
        reply = {
            "type": FRAME_REPLY,
            "request": str(frame.get("request", "") or ""),
            "code": "" if is_known else "session_unknown",
            "params": {} if is_known else {"session_id": session_id},
        }
        try:
            self._control.send_frame(reply)
        except GatewayUnreachable:
            return

    def _unreadable(self, kind) -> None:
        """A frame this build cannot read: one log line and a typed error."""
        name = kind if isinstance(kind, str) else ""
        self._log(f"ignoring a frame this agent cannot read: {name or kind!r}")
        if self._on_unreadable is not None:
            self._on_unreadable(
                {"code": AGENT_CODE_FRAME_UNREADABLE, "params": {"type": name}}
            )

    def _serve_stream(self, stream_id: str, open_record: dict) -> None:
        """Attach one stream, open its handler, run it, and close it with its result."""
        try:
            channel = self._control.attach(stream_id)
        except GatewayUnreachable as error:
            self._log(f"stream {stream_id} could not be taken: {error}")
            return
        kind = str(open_record.get("kind", "") or "")
        args = {
            key: value
            for key, value in open_record.items()
            if key not in OPEN_ENVELOPE_FIELDS
        }
        factory = self._stream_kinds.get(kind)
        if factory is None:
            channel.close("kind_unknown", {"kind": kind})
            return
        try:
            try:
                stream = factory(channel, args)
                stream.open()
            except StreamRefused as refused:
                channel.close(refused.code, dict(refused.params))
                return
            channel.accept()
            channel.start()
            info = stream.run()
        except GatewayUnreachable:
            channel.close()
            return
        except StreamClosed:
            info = {"code": "", "params": {}}
        except Exception as error:  # noqa: BLE001 - reported, never fatal
            self._log(f"stream {stream_id} failed: {error}")
            info = {
                "code": "agent_internal",
                "params": {"error": type(error).__name__},
            }
        channel.close(str(info.get("code", "") or ""), dict(info.get("params") or {}))
