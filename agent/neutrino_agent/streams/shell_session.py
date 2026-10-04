"""Shells that outlive the stream they were opened on.

A shell is a :class:`ShellSession`: the terminal it runs on, a thread that
reads everything the terminal prints, and the latest 256 KB of that output.
Any number of ``shell`` streams attach to it at once: each gets every byte
of output, each one's input reaches the shell, and the terminal's size is
the smallest attached window's columns and rows. A stream that attaches to
a running shell is sent the kept output first, with the terminal's query
sequences taken out, then the terminal is resized away and back so a
full-screen program draws itself again.

A stream opened with a ``session_id`` names its session in the agent's
:class:`ShellSessionRegistry`: an id the registry holds is attached to, and
an id it does not hold starts a new shell under that id, unless the open
says ``is_resumed``, which is refused ``session_unknown``. When the last
stream closes, a persistent or shared session keeps running and any other
ends. The registry lives as long as the agent's process, so a restart ends
every session.

Not pure: runs a thread per shell.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import collections
import re
import threading
import time

from neutrino_agent.constants import (
    AGENT_SHELL_KEPT_BYTES,
    AGENT_SHELL_KILL_TIMEOUT_S,
    AGENT_SHELL_PENDING_BYTES,
    AGENT_WS_STREAM_CREDIT_BYTES,
)
from neutrino_agent.exceptions import StreamClosed, StreamRefused

DEFAULT_COLUMNS = 80
DEFAULT_ROWS = 24
# How long a wait for output, or for the hub's next item, sleeps before
# looking again.
SESSION_POLL_S = 0.5
# A title a program sets with OSC 0 or OSC 2.
TITLE_PATTERN = re.compile(rb"\x1b\][02];([^\x07\x1b]*)(?:\x07|\x1b\\)")
TITLE_LIMIT = 200
# What a terminal answers when it reads it: device attributes (``ESC [ c``,
# ``ESC [ > c``, ``ESC [ = c``), a status or cursor position report
# (``ESC [ 5 n``, ``ESC [ 6 n``, ``ESC [ ? 6 n``), and the OSC colour queries
# (``ESC ] 10 ; ?`` to ``ESC ] 19 ; ?``, ``ESC ] 4 ; <n> ; ?`` and
# ``ESC ] 5 ; <n> ; ?``) ended by BEL or ST.
QUERY_PATTERN = re.compile(
    rb"\x1b\[[>=]?0?c"
    rb"|\x1b\[\??[56]n"
    rb"|\x1b\](?:1[0-9]|[45];[0-9]+);\?(?:\x07|\x1b\\)"
)


def strip_queries(output: bytes) -> bytes:
    """Kept output with the sequences a terminal answers taken out.

    Args:
        output: The output as the shell printed it.

    Returns:
        The output without its device attribute, status report and colour
        queries; everything else as it was.
    """
    return QUERY_PATTERN.sub(b"", output)


def _started_at(described: dict) -> int:
    return int(described.get("started_at", 0))


class ShellAttachment:
    """The output waiting for one attached stream, its window, and how it ended."""

    def __init__(
        self,
        kept: bytes = b"",
        *,
        cols: int = DEFAULT_COLUMNS,
        rows: int = DEFAULT_ROWS,
    ):
        """
        Args:
            kept: Output to send before anything new.
            cols: The stream's terminal width.
            rows: The stream's terminal height.
        """
        self.cols = cols
        self.rows = rows
        self._condition = threading.Condition()
        self._chunks: collections.deque = collections.deque()
        self._pending = 0
        self._result: "dict | None" = None
        self._is_released = False
        if kept:
            self.push(kept)

    @property
    def result(self) -> "dict | None":
        """What the stream closes with, once every chunk before it was pulled."""
        with self._condition:
            return None if self._chunks else self._result

    def push(self, chunk: bytes) -> None:
        """Queue output for the stream.

        Args:
            chunk: The bytes.
        """
        with self._condition:
            self._chunks.append(bytes(chunk))
            self._pending += len(chunk)
            self._condition.notify_all()

    def wait_for_room(self) -> None:
        """Wait while more output waits than the stream is let fall behind."""
        with self._condition:
            while (
                self._pending > AGENT_SHELL_PENDING_BYTES
                and self._result is None
                and not self._is_released
            ):
                self._condition.wait(SESSION_POLL_S)

    def pull(self, timeout_s: float) -> "bytes | None":
        """The next queued output.

        Args:
            timeout_s: How long to wait for some.

        Returns:
            The bytes, or None when none came in time.
        """
        with self._condition:
            if not self._chunks and self._result is None:
                self._condition.wait(timeout_s)
            if not self._chunks:
                return None
            chunk = self._chunks.popleft()
            self._pending -= len(chunk)
            self._condition.notify_all()
            return chunk

    def end(self, result: dict) -> None:
        """Say how the stream closes once its output is sent.

        Args:
            result: ``{"code", "params"}``.
        """
        with self._condition:
            if self._result is None:
                self._result = dict(result)
            self._condition.notify_all()

    def release(self) -> None:
        """Stop holding the shell back for a stream that left."""
        with self._condition:
            self._is_released = True
            self._condition.notify_all()


class ShellSession:
    """One shell on its terminal, shared by every stream attached to it."""

    def __init__(
        self,
        *,
        session_id: str,
        terminal,
        account: str,
        title: str,
        on_change=None,
        on_end=None,
        clock=time.time,
    ):
        """
        Args:
            session_id: The id the opener gave it; empty for a shell no
                registry holds.
            terminal: The platform's terminal, not yet started: it has
                ``start``, ``read``, ``write``, ``resize``, ``terminate``
                and ``finish``.
            account: The account the shell runs as.
            title: The title until the shell sets one.
            on_change: Called whenever what the report lists of it changes.
            on_end: Called with the session once its shell has ended.
            clock: The wall clock its start time is read from.
        """
        self.session_id = session_id
        self.account = account
        self.started_at = int(clock())
        self.owner = ""
        self.is_persistent = False
        self.is_shared = False
        self._terminal = terminal
        self._title = title
        self._on_change = on_change
        self._on_end = on_end
        self._lock = threading.Lock()
        self._kept = bytearray()
        self._attachments: list = []
        self._size_lock = threading.Lock()
        self._size: "tuple | None" = None
        self._result: "dict | None" = None
        self._is_ended = threading.Event()

    def start(self) -> None:
        """Start the shell and the thread that reads it.

        Raises:
            OSError: When the shell cannot start.
        """
        self._terminal.start()
        threading.Thread(
            target=self._read_forever,
            name=f"agent_shell_session_{self.session_id or 'bare'}",
            daemon=True,
        ).start()

    def attach(self, *, is_resumed: bool, cols: int, rows: int) -> ShellAttachment:
        """Attach a stream beside every stream already attached.

        Args:
            is_resumed: Whether the shell ran before this stream: its kept
                output, without the terminal's queries, is sent first and
                the terminal is nudged to redraw.
            cols: The stream's terminal width.
            rows: The stream's terminal height.

        Returns:
            The stream's attachment.
        """
        with self._lock:
            attachment = ShellAttachment(
                strip_queries(bytes(self._kept)) if is_resumed else b"",
                cols=cols,
                rows=rows,
            )
            if self._result is not None:
                attachment.end(self._result)
            else:
                self._attachments.append(attachment)
        self._fit(is_redrawn=is_resumed)
        self._changed()
        return attachment

    def detach(self, attachment: ShellAttachment) -> bool:
        """Let go of a stream that closed.

        Args:
            attachment: The stream's attachment.

        Returns:
            Whether the shell is to keep running: another stream is still
            attached, or it is persistent or shared.
        """
        attachment.release()
        with self._lock:
            if attachment in self._attachments:
                self._attachments.remove(attachment)
            is_kept = bool(self._attachments) or self.is_persistent or self.is_shared
        self._fit(is_redrawn=False)
        self._changed()
        return is_kept

    def write(self, data: bytes) -> None:
        """Type into the shell.

        Args:
            data: The bytes.
        """
        self._terminal.write(data)

    def resize(self, attachment: ShellAttachment, cols: int, rows: int) -> None:
        """Take a new window size from one attached stream.

        Args:
            attachment: The stream's attachment.
            cols: The stream's new width.
            rows: The stream's new height.
        """
        with self._lock:
            attachment.cols = cols
            attachment.rows = rows
        self._fit(is_redrawn=False)

    def end(self) -> None:
        """End the shell and everything it started."""
        self._terminal.terminate()

    def wait(self, timeout_s: float) -> "dict | None":
        """Wait for the shell to end.

        Args:
            timeout_s: How long to wait.

        Returns:
            ``{"code", "params"}`` with the exit code, or None while it runs.
        """
        self._is_ended.wait(timeout_s)
        with self._lock:
            return dict(self._result) if self._result is not None else None

    def describe(self) -> dict:
        """The session as the report lists it.

        Returns:
            ``{"session_id", "account", "started_at", "title", "owner",
            "is_attached", "is_persistent", "is_shared", "attached_count"}``.
        """
        with self._lock:
            return {
                "session_id": self.session_id,
                "account": self.account,
                "started_at": self.started_at,
                "title": self._title,
                "owner": self.owner,
                "is_attached": bool(self._attachments),
                "is_persistent": self.is_persistent,
                "is_shared": self.is_shared,
                "attached_count": len(self._attachments),
            }

    def _read_forever(self) -> None:
        """Keep and forward the terminal's output until the shell ends."""
        while True:
            try:
                chunk = self._terminal.read()
            except OSError:
                chunk = b""
            if not chunk:
                break
            with self._lock:
                self._kept += chunk
                del self._kept[: max(0, len(self._kept) - AGENT_SHELL_KEPT_BYTES)]
                is_retitled = self._take_title(chunk)
                attachments = list(self._attachments)
                for attachment in attachments:
                    attachment.push(chunk)
            if is_retitled:
                self._changed()
            for attachment in attachments:
                attachment.wait_for_room()
        exit_code = self._terminal.finish()
        result = {"code": "", "params": {"exit_code": exit_code}}
        with self._lock:
            self._result = result
            attachments = self._attachments
            self._attachments = []
        for attachment in attachments:
            attachment.end(result)
        self._is_ended.set()
        if self._on_end is not None:
            self._on_end(self)

    def _fit(self, *, is_redrawn: bool) -> None:
        """Size the terminal to the smallest attached window, once it changed."""
        with self._size_lock:
            with self._lock:
                windows = [(each.cols, each.rows) for each in self._attachments]
            if not windows:
                return
            size = (min(cols for cols, _ in windows), min(rows for _, rows in windows))
            if self._size is None:
                self._size = size
                return
            if is_redrawn:
                self._terminal.resize(size[0], size[1] + 1)
            elif size == self._size:
                return
            self._terminal.resize(*size)
            self._size = size

    def _take_title(self, chunk: bytes) -> bool:
        """Keep the last title the output sets. Call under the lock."""
        found = TITLE_PATTERN.findall(chunk)
        if not found:
            return False
        title = found[-1].decode("utf-8", "replace")[:TITLE_LIMIT]
        is_new = title != self._title
        self._title = title
        return is_new

    def _changed(self) -> None:
        if self._on_change is not None and self.session_id:
            self._on_change()


class ShellSessionRegistry:
    """Every shell this agent keeps by id, for as long as the process runs."""

    def __init__(self, *, on_change=None):
        """
        Args:
            on_change: Called whenever the listed sessions change, so a
                report goes up at once.
        """
        self._on_change = on_change
        self._lock = threading.Lock()
        self._sessions: dict = {}

    def take(self, session_id: str, *, is_resumed: bool, make) -> tuple:
        """The session an id names, or a new one under it.

        Args:
            session_id: The id the stream's open carries.
            is_resumed: Whether the opener asks only for a session the agent
                already holds.
            make: Called with ``on_change`` and ``on_end`` to build a new,
                unstarted session.

        Returns:
            ``(session, is_held)``: the session, and whether it ran before.

        Raises:
            StreamRefused: ``session_unknown`` for a resumed id the registry
                does not hold.
        """
        with self._lock:
            held = self._sessions.get(session_id)
            if held is not None:
                return held, True
            if is_resumed:
                raise StreamRefused("session_unknown", {"session_id": session_id})
            session = make(on_change=self._changed, on_end=self.forget)
            self._sessions[session_id] = session
        self._changed()
        return session, False

    def forget(self, session: ShellSession) -> None:
        """Drop a session whose shell ended or never started.

        Args:
            session: The session.
        """
        with self._lock:
            if self._sessions.get(session.session_id) is session:
                del self._sessions[session.session_id]
        self._changed()

    def persist(
        self,
        session_id: str,
        is_persistent: "bool | None" = None,
        is_shared: "bool | None" = None,
    ) -> bool:
        """Say whether a session outlives its streams and who may list it.

        Args:
            session_id: The session.
            is_persistent: Keep it when its last stream closes; None keeps
                the value it has.
            is_shared: Open it to everyone with terminal rights on this
                machine, which also keeps it when its last stream closes;
                None keeps the value it has.

        Returns:
            False when no session has that id.
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session is not None and is_persistent is not None:
                session.is_persistent = bool(is_persistent)
            if session is not None and is_shared is not None:
                session.is_shared = bool(is_shared)
        if session is None:
            return False
        self._changed()
        return True

    def stop(self, session_id: str) -> bool:
        """End one session's shell; an attached stream closes with its exit.

        Args:
            session_id: The session.

        Returns:
            False when no session has that id.
        """
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            return False
        session.end()
        return True

    def describe(self) -> list:
        """Every session, oldest first, as the report lists them.

        Returns:
            One :meth:`ShellSession.describe` each.
        """
        with self._lock:
            sessions = list(self._sessions.values())
        described = [session.describe() for session in sessions]
        return sorted(described, key=_started_at)

    def _changed(self) -> None:
        if self._on_change is not None:
            self._on_change()


class SessionShellStream:
    """One ``shell`` stream, attached to a shell kept by id or started for it.

    A subclass names the platform's terminal and account; the stream reads
    ``session_id``, ``is_resumed``, ``owner`` and ``is_shared`` from its open.
    """

    def __init__(self, channel, args: dict, *, sessions=None):
        """
        Args:
            channel: The stream's channel.
            args: ``{"cols", "rows"}``, the terminal's size, with
                ``session_id`` and ``is_resumed`` for a kept shell, and
                ``owner``, the hub's stamp kept as given, and ``is_shared``
                for a new one.
            sessions: The agent's :class:`ShellSessionRegistry`; None keeps
                no shell past its stream.
        """
        self._channel = channel
        self._columns = max(1, int(args.get("cols", DEFAULT_COLUMNS) or 0))
        self._rows = max(1, int(args.get("rows", DEFAULT_ROWS) or 0))
        self._session_id = str(args.get("session_id", "") or "")
        self._is_resumed = bool(args.get("is_resumed", False))
        self._owner = str(args.get("owner", "") or "")
        self._is_shared = bool(args.get("is_shared", False))
        self._sessions = sessions
        self._session: "ShellSession | None" = None
        self._is_held = False
        self._is_done = threading.Event()

    def open(self) -> None:
        """Check the platform, then find or make the session.

        Raises:
            StreamRefused: ``session_unknown`` for a resumed id the agent
                does not hold, or the platform's own refusal.
        """
        self._check_platform()
        if self._sessions is None or not self._session_id:
            self._session = self._make_session()
            return
        self._session, self._is_held = self._sessions.take(
            self._session_id, is_resumed=self._is_resumed, make=self._make_kept_session
        )

    def run(self) -> dict:
        """Serve the shell until it ends or the stream closes.

        Returns:
            ``{"code", "params"}``: ``exit_code`` once the shell ended,
            empty params when the stream closed on a shell that keeps
            running, and ``shell_failed`` with ``detail`` when it could not
            start.
        """
        session = self._session
        # Attached before it starts, so the stream sees a new shell's first
        # output.
        attachment = session.attach(
            is_resumed=self._is_held, cols=self._columns, rows=self._rows
        )
        if not self._is_held:
            try:
                session.start()
            except OSError as error:
                session.detach(attachment)
                if self._sessions is not None and self._session_id:
                    self._sessions.forget(session)
                return {"code": "shell_failed", "params": {"detail": str(error)[:200]}}
        self._channel.offer_credit(AGENT_WS_STREAM_CREDIT_BYTES)
        feeder = threading.Thread(
            target=self._feed_input,
            args=(session, attachment),
            name=f"agent_shell_input_{self._channel.id}",
            daemon=True,
        )
        feeder.start()
        result = self._pump_output(attachment)
        self._is_done.set()
        feeder.join(timeout=AGENT_SHELL_KILL_TIMEOUT_S)
        if result is not None:
            return result
        if session.detach(attachment):
            return {"code": "", "params": {}}
        session.end()
        ended = session.wait(AGENT_SHELL_KILL_TIMEOUT_S * 3)
        return ended if ended is not None else {"code": "", "params": {}}

    def _check_platform(self) -> None:
        """Refuse on a platform that cannot serve the shell."""

    def _make_session(self, *, on_change=None, on_end=None) -> ShellSession:
        """A new, unstarted session on the platform's terminal."""
        raise NotImplementedError

    def _make_kept_session(self, *, on_change=None, on_end=None) -> ShellSession:
        """A new session the registry holds, with the open's owner and sharing."""
        session = self._make_session(on_change=on_change, on_end=on_end)
        session.owner = self._owner
        session.is_shared = self._is_shared
        return session

    def _pump_output(self, attachment: ShellAttachment) -> "dict | None":
        """Send the attachment's output; None once the stream itself closed."""
        while True:
            chunk = attachment.pull(SESSION_POLL_S)
            if chunk:
                try:
                    self._channel.send_bytes(chunk)
                except StreamClosed:
                    return None
                continue
            result = attachment.result
            if result is not None:
                return result
            if self._is_done.is_set():
                return None

    def _feed_input(self, session: ShellSession, attachment: ShellAttachment) -> None:
        """Type the hub's bytes into the shell and pass on its resizes."""
        while not self._is_done.is_set():
            item = self._channel.recv(timeout=SESSION_POLL_S)
            if item is None:
                continue
            if item[0] == "data":
                session.write(item[1])
                self._channel.offer_credit(len(item[1]))
            elif item[0] == "resize":
                self._columns = max(1, int(item[1]))
                self._rows = max(1, int(item[2]))
                session.resize(attachment, self._columns, self._rows)
            elif item[0] == "close":
                self._is_done.set()
                return
