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
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

from neutrino_client.exceptions import GatewayRefusedDetail, GatewayUnreachable

# How much one read from the typing side takes.
TERMINAL_READ_BYTES = 4096
# How long one wait for the hub's output lasts before the stream is looked
# at again.
TERMINAL_WAIT_S = 0.5
# How much output already arrived is handed on in one piece.
TERMINAL_BATCH_BYTES = 65536


class TerminalBridge:
    """One shell stream, pumped to and from the terminal it is shown on."""

    def __init__(self, *, stream, session_id: str = ""):
        """
        Args:
            stream: The open ``shell`` stream.
            session_id: The shell session the stream is attached to.
        """
        self._stream = stream
        self._session_id = session_id
        self._is_closed_here = False

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

    def close(self) -> None:
        """End the shell from this side. Idempotent."""
        self._is_closed_here = self._is_closed_here or not self._stream.is_done
        self._stream.close()

    def pump_in(self, read) -> None:
        """Send what is typed to the hub until the typing side ends.

        The stream is closed from this side when it does.

        Args:
            read: ``read(size)`` returns the next bytes typed, empty at the
                end; an ``OSError`` counts as the end.
        """
        while True:
            try:
                data = read(TERMINAL_READ_BYTES)
            except OSError:
                data = b""
            if not data:
                break
            try:
                self._stream.send(data)
            except (GatewayUnreachable, TimeoutError):
                break
        self._is_closed_here = not self._stream.is_done
        self._stream.close()

    def pump_out(self, write) -> None:
        """Write the hub's output until the stream ends.

        What has already arrived is written in one piece, up to
        ``TERMINAL_BATCH_BYTES``.

        Args:
            write: ``write(data)`` puts bytes on the terminal; an
                ``OSError`` ends the stream from this side.
        """
        while True:
            data = self._stream.read(TERMINAL_WAIT_S)
            if data is None:
                continue
            if not data:
                return
            while len(data) < TERMINAL_BATCH_BYTES:
                more = self._stream.read(0)
                if not more:
                    break
                data += more
            try:
                write(data)
            except OSError:
                self._is_closed_here = not self._stream.is_done
                self._stream.close()
                return

    def outcome(self) -> dict:
        """How the shell ended, once it has.

        Returns:
            ``{"exit_code"}`` for a shell the hub closed with a result or
            one closed from here, its code None when the hub named none;
            ``{"code", "params"}`` for a refusal or a socket that ended
            first.
        """
        if self._is_closed_here:
            return {"exit_code": None}
        try:
            params = self._stream.wait_close(0)
        except GatewayRefusedDetail as refused:
            return {"code": refused.code, "params": dict(refused.params)}
        except GatewayUnreachable:
            return {"code": "hub_unreachable", "params": {}}
        return {"exit_code": params.get("exit_code")}
