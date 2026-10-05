"""A hub's shell carried to a terminal on this machine.

The resident opens a ``shell`` stream to a managed machine through its hub
and bridges it to one of two terminals. ``nclient terminal`` holds two
control connections: one carries the keys typed to the hub, the other the
hub's output back, one direction each, because a Windows pipe handle serves
one blocking operation at a time. The window's own terminal sends its keys
as requests and takes the output as pushes. The typing side ending closes
the stream; the hub closing it ends the output side, which ends the
terminal. Each stream is attached to one shell session by its id; a session
kept on the machine outlives the stream and is attached to again by that id.

A Clear sends Ctrl+C after what was typed before it, and the output is
dropped, what had arrived and was not yet written among it, until the stream
has been quiet for ``CLIENT_TERMINAL_CLEAR_QUIET_S``, for
``CLIENT_TERMINAL_CLEAR_MAX_S`` at most.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import threading
import time

from neutrino_client.constants import (
    CLIENT_TERMINAL_CLEAR_MAX_S,
    CLIENT_TERMINAL_CLEAR_QUIET_S,
)
from neutrino_client.exceptions import GatewayRefusedDetail, GatewayUnreachable

# How much one read from the typing side takes.
TERMINAL_READ_BYTES = 4096
# How long one wait for the hub's output lasts before the stream is looked
# at again.
TERMINAL_WAIT_S = 0.5
# How much output already arrived is handed on in one piece.
TERMINAL_BATCH_BYTES = 65536
# The key a Clear sends first.
TERMINAL_CTRL_C = b"\x03"


def _nobody(*_args) -> None:
    """Nobody listening."""


class TerminalBridge:
    """One shell stream, pumped to and from the terminal it is shown on."""

    def __init__(self, *, stream, session_id: str = "", clock=time.monotonic):
        """
        Args:
            stream: The open ``shell`` stream.
            session_id: The shell session the stream is attached to.
            clock: The monotonic clock a Clear's quiet is measured on.
        """
        self._stream = stream
        self._session_id = session_id
        self._clock = clock
        self._is_closed_here = False
        # Why this side ended the shell when it did so on a failure of its
        # own, as ``{"code", "params"}``; empty otherwise.
        self._failure: dict = {}
        self._drop_lock = threading.Lock()
        # While a Clear drops the output: when it began, and when the last
        # dropped bytes arrived; None otherwise.
        self._drop_since: "float | None" = None
        self._drop_last = 0.0

    @property
    def stream_id(self) -> int:
        """The shell stream's id, which a resize names."""
        return self._stream.stream_id

    @property
    def session_id(self) -> str:
        """The shell session's id, which ``persist`` and ``stop_session`` name."""
        return self._session_id

    @property
    def is_done(self) -> bool:
        """Whether the stream has ended, from either side."""
        return self._stream.is_done

    def send(self, data: bytes) -> bool:
        """Send keys typed on the window's terminal to the hub.

        Args:
            data: The bytes typed.

        Returns:
            Whether they went; False once the stream has ended or the hub
            granted no credit in time.
        """
        try:
            self._stream.send(data)
        except (GatewayUnreachable, TimeoutError):
            return False
        return True

    @property
    def is_clearing(self) -> bool:
        """Whether a Clear is dropping the output."""
        with self._drop_lock:
            return self._drop_since is not None

    def clear(self) -> bool:
        """Start a Clear: drop the output from now, and send Ctrl+C.

        Returns:
            Whether Ctrl+C went.
        """
        now = self._clock()
        with self._drop_lock:
            self._drop_since = now
            self._drop_last = now
        return self.send(TERMINAL_CTRL_C)

    def close(self) -> None:
        """End the shell from this side. Idempotent."""
        self._is_closed_here = self._is_closed_here or not self._stream.is_done
        self._stream.close()

    def pump_in(self, read) -> None:
        """Send what is typed to the hub until the typing side ends.

        The stream is closed from this side when it does.

        Args:
            read: ``read(size)`` returns the next bytes typed, empty at the
                end; an ``OSError`` ends it too, and the shell's outcome
                then says ``terminal_input_failed``.
        """
        while True:
            try:
                data = read(TERMINAL_READ_BYTES)
            except OSError as error:
                if not self._stream.is_done:
                    self._failure = {
                        "code": "terminal_input_failed",
                        "params": {"detail": str(error)[:200] or type(error).__name__},
                    }
                data = b""
            if not data:
                break
            try:
                self._stream.send(data)
            except (GatewayUnreachable, TimeoutError):
                break
        self._is_closed_here = not self._stream.is_done
        self._stream.close()

    def pump_out(self, write, on_cleared=None) -> None:
        """Write the hub's output until the stream ends.

        What has already arrived is written in one piece, up to
        ``TERMINAL_BATCH_BYTES``. While a Clear drops the output nothing is
        written, and ``on_cleared`` is called once the stream has been
        quiet long enough.

        Args:
            write: ``write(data)`` puts bytes on the terminal; an
                ``OSError`` ends the stream from this side.
            on_cleared: Called with no arguments when a Clear stops
                dropping; None for nobody listening.
        """
        on_cleared = on_cleared if on_cleared is not None else _nobody
        while True:
            data = self._stream.read(self._wait_s())
            if self._is_dropping(data, on_cleared):
                if data == b"":
                    return
                continue
            if data is None:
                continue
            if not data:
                return
            while len(data) < TERMINAL_BATCH_BYTES:
                more = self._stream.read(0)
                if not more:
                    break
                data += more
            if self._is_dropping(data, on_cleared):
                continue
            try:
                write(data)
            except OSError:
                self._is_closed_here = not self._stream.is_done
                self._stream.close()
                return

    def _wait_s(self) -> float:
        """How long the next read may wait: until a Clear's drop could end."""
        with self._drop_lock:
            if self._drop_since is None:
                return TERMINAL_WAIT_S
            ends_at = min(
                self._drop_last + CLIENT_TERMINAL_CLEAR_QUIET_S,
                self._drop_since + CLIENT_TERMINAL_CLEAR_MAX_S,
            )
        return min(TERMINAL_WAIT_S, max(ends_at - self._clock(), 0.0))

    def _is_dropping(self, data, on_cleared) -> bool:
        """Whether a Clear takes these bytes; ends the drop once it is due.

        Args:
            data: What the last read gave: bytes, empty at the end, or None.
            on_cleared: Called when the drop ends here.

        Returns:
            True when the bytes are dropped, or nothing came while dropping.
        """
        now = self._clock()
        with self._drop_lock:
            if self._drop_since is None:
                return False
            if data:
                self._drop_last = now
            is_due = (
                now >= self._drop_last + CLIENT_TERMINAL_CLEAR_QUIET_S
                or now >= self._drop_since + CLIENT_TERMINAL_CLEAR_MAX_S
            )
            if is_due:
                self._drop_since = None
        if is_due:
            on_cleared()
        return True

    def outcome(self) -> dict:
        """How the shell ended, once it has.

        Returns:
            ``{"exit_code"}`` for a shell the hub closed with a result or
            one closed from here, its code None when the hub named none;
            ``{"code", "params"}`` for a refusal, a socket that ended
            first, or keys this side could no longer read.
        """
        if self._failure:
            return dict(self._failure)
        if self._is_closed_here:
            return {"exit_code": None}
        try:
            params = self._stream.wait_close(0)
        except GatewayRefusedDetail as refused:
            return {"code": refused.code, "params": dict(refused.params)}
        except GatewayUnreachable:
            return {"code": "hub_unreachable", "params": {}}
        return {"exit_code": params.get("exit_code")}
