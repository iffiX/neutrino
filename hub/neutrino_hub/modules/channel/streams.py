"""One stream of the channel, as the hub's Python holds it over its transport.

A stream the hub's Python takes or opens rides one local connection to the
transport, which copies the stream's records both ways unchanged. Each
record is ``<u8 type><u32 length, big-endian><payload>``: the opener's
``open``, the other side's ``accept`` or refusing ``close``, then ``data``,
``stderr``, ``eof``, ``resize`` and ``datagram`` as the kind takes them,
and a ``close`` whose ``params`` are the result (transport.md, "The stream
layer"). What arrives queues up in order and ``None`` follows the end.
"""

import asyncio
import concurrent.futures
import json
import struct

from neutrino_hub.exceptions import AgentOfflineError, StreamRefusedError
from neutrino_hub.modules.channel.constants import (
    CHANNEL_CALL_TIMEOUT_S,
    CHANNEL_CODE_NEVER_REPORTED,
    CHANNEL_ITEM_DATA,
    CHANNEL_ITEM_DATAGRAM,
    CHANNEL_ITEM_EOF,
    CHANNEL_ITEM_RESIZE,
    CHANNEL_ITEM_STDERR,
    CHANNEL_RECORD_ACCEPT,
    CHANNEL_RECORD_BYTES_MAX,
    CHANNEL_RECORD_CLOSE,
    CHANNEL_RECORD_DATA,
    CHANNEL_RECORD_DATAGRAM,
    CHANNEL_RECORD_EOF,
    CHANNEL_RECORD_HEADER_BYTES,
    CHANNEL_RECORD_OPEN,
    CHANNEL_RECORD_RESIZE,
    CHANNEL_RECORD_STDERR,
)
from neutrino_hub.utils.owned_tasks import start_owned_task

# The record types recv() hands on, by the name each item carries.
ITEM_NAMES = {
    CHANNEL_RECORD_DATA: CHANNEL_ITEM_DATA,
    CHANNEL_RECORD_STDERR: CHANNEL_ITEM_STDERR,
    CHANNEL_RECORD_EOF: CHANNEL_ITEM_EOF,
    CHANNEL_RECORD_RESIZE: CHANNEL_ITEM_RESIZE,
    CHANNEL_RECORD_DATAGRAM: CHANNEL_ITEM_DATAGRAM,
}
HEADER = struct.Struct("!BI")


def encode_record(record_type: int, payload: bytes = b"") -> bytes:
    """One record as the wire carries it.

    Args:
        record_type: The type byte.
        payload: The payload, at most :data:`CHANNEL_RECORD_BYTES_MAX`.

    Returns:
        The header and the payload.

    Raises:
        ValueError: If the payload is longer than a record holds.
    """
    if len(payload) > CHANNEL_RECORD_BYTES_MAX:
        raise ValueError(f"a record holds {CHANNEL_RECORD_BYTES_MAX} bytes at most")
    return HEADER.pack(record_type, len(payload)) + payload


def encode_json_record(record_type: int, body: dict) -> bytes:
    """One record whose payload is a JSON object."""
    return encode_record(
        record_type, json.dumps(body, separators=(",", ":")).encode("utf-8")
    )


def decode_json(payload: bytes) -> dict:
    """A JSON record's object, empty for anything that is not one."""
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


async def read_record(reader: asyncio.StreamReader) -> "tuple | None":
    """Read one record from a connection.

    Args:
        reader: The connection's reader.

    Returns:
        ``(type, payload)``, or None at end of file.

    Raises:
        ValueError: If a record is longer than one may be.
    """
    try:
        header = await reader.readexactly(CHANNEL_RECORD_HEADER_BYTES)
    except (asyncio.IncompleteReadError, ConnectionError, OSError):
        return None
    record_type, length = HEADER.unpack(header)
    if length > CHANNEL_RECORD_BYTES_MAX:
        raise ValueError(f"a record of {length} bytes is longer than one may be")
    try:
        payload = await reader.readexactly(length) if length else b""
    except (asyncio.IncompleteReadError, ConnectionError, OSError):
        return None
    return record_type, payload


class ChannelStream:
    """One stream on one session, carried by one local connection.

    Attributes:
        id: The transport's id of a stream a peer opened; 0 for one the hub
            opened.
        kind: The stream kind.
        args: What the open carried beside the kind.
        close_info: ``{"code", "params"}`` once the stream closed.
        is_abandoned: True when the connection ended under the stream.
        is_accepted: True once the far side accepted the stream, or this
            side did.
    """

    def __init__(
        self,
        *,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        kind: str,
        args: "dict | None" = None,
        stream_id: int = 0,
        peer_key: str = "",
    ):
        """
        Args:
            reader: The local connection's reader, past its first line.
            writer: The local connection's writer.
            kind: The stream kind.
            args: What the open carried beside the kind.
            stream_id: The transport's id of a stream a peer opened.
            peer_key: The binding on the other end, which a dropped
                connection names in its ``agent_offline``.
        """
        self.id = int(stream_id)
        self.kind = kind
        self.args = dict(args or {})
        self.close_info: "dict | None" = None
        self.is_abandoned = False
        self.is_accepted = False
        self._reader = reader
        self._writer = writer
        self._peer_key = peer_key
        self._loop = asyncio.get_running_loop()
        self._inbound: asyncio.Queue = asyncio.Queue()
        self._closed = asyncio.Event()
        self._answered = asyncio.Event()
        self._write_lock = asyncio.Lock()
        self._pump = start_owned_task(self._read_forever())

    @property
    def is_closed(self) -> bool:
        """Whether the stream ended, from either side, or the connection is gone."""
        return self._closed.is_set()

    async def opened(self) -> bool:
        """Wait for the far side's answer to an open this side wrote.

        Returns:
            True on ``accept``; False when the far side refused, the refusal
            in :attr:`close_info`, or the connection ended first.
        """
        await self._answered.wait()
        return self.is_accepted

    async def recv(self) -> "tuple | None":
        """The next item from the peer.

        Returns:
            ``(name, payload)``: ``("data", bytes)``, ``("stderr", bytes)``,
            ``("eof", b"")``, ``("resize", {cols, rows})`` or ``("datagram",
            bytes)``, or None once the stream is closed and nothing is left
            to read.
        """
        if self._closed.is_set() and self._inbound.empty():
            return None
        return await self._inbound.get()

    async def accept(self) -> None:
        """Answer a peer's open with ``accept``.

        Raises:
            AgentOfflineError: If the connection is gone.
        """
        self.is_accepted = True
        await self._write(encode_record(CHANNEL_RECORD_ACCEPT))

    async def send_bytes(self, data: bytes) -> None:
        """Send bytes to the peer as ``data`` records.

        Args:
            data: The bytes, split into records of a record's size.

        Raises:
            AgentOfflineError: If the stream closes before everything is sent.
        """
        await self.send_record(CHANNEL_RECORD_DATA, data)

    async def send_record(self, record_type: int, payload: bytes = b"") -> None:
        """Send one kind of record, split where the payload is longer than one.

        Args:
            record_type: The type byte.
            payload: The payload.

        Raises:
            AgentOfflineError: If the stream is closed or the connection gone.
        """
        view = memoryview(payload)
        if not view:
            await self._write(encode_record(record_type))
            return
        while view:
            if self._closed.is_set():
                raise AgentOfflineError(self._peer_key)
            chunk = bytes(view[:CHANNEL_RECORD_BYTES_MAX])
            view = view[CHANNEL_RECORD_BYTES_MAX:]
            await self._write(encode_record(record_type, chunk))

    async def send_resize(self, cols: int, rows: int) -> None:
        """Send a terminal's later size.

        Raises:
            AgentOfflineError: If the stream is closed or the connection gone.
        """
        await self._write(
            encode_json_record(
                CHANNEL_RECORD_RESIZE, {"cols": int(cols), "rows": int(rows)}
            )
        )

    async def send_eof(self) -> None:
        """Tell the peer no more input follows on this stream.

        Raises:
            AgentOfflineError: If the stream is closed or the connection gone.
        """
        await self._write(encode_record(CHANNEL_RECORD_EOF))

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
        try:
            await self._write(encode_json_record(CHANNEL_RECORD_CLOSE, info))
        except AgentOfflineError:
            pass
        self._finish(info)
        await self._end_connection()

    async def wait_closed(self) -> "dict | None":
        """Wait for the stream's end.

        Returns:
            What it closed with, or None when the connection went away.
        """
        await self._closed.wait()
        return None if self.is_abandoned else self.close_info

    def recv_from_thread(self, timeout: "float | None" = None) -> "tuple | None":
        """:meth:`recv` for a caller outside the loop."""
        return self.call(self.recv(), timeout=timeout)

    def send_bytes_from_thread(self, data: bytes, timeout: "float | None" = None):
        """:meth:`send_bytes` for a caller outside the loop."""
        return self.call(self.send_bytes(data), timeout=timeout)

    def close_from_thread(
        self, code: str = "", params: "dict | None" = None, timeout: float = 5.0
    ) -> None:
        """:meth:`close` for a caller outside the loop."""
        self.call(self.close(code, params), timeout=timeout)

    def wait_closed_from_thread(self, timeout: "float | None" = None) -> "dict | None":
        """:meth:`wait_closed` for a caller outside the loop."""
        return self.call(self.wait_closed(), timeout=timeout)

    def call(self, coroutine, timeout: "float | None" = None):
        """Run a coroutine on the stream's loop from another thread.

        Args:
            coroutine: What to run.
            timeout: How long to wait for its result.

        Returns:
            The coroutine's result.

        Raises:
            StreamRefusedError: With ``agent_never_reported`` when the wait
                runs out; the coroutine is cancelled.
        """
        future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        try:
            return future.result(timeout)
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise StreamRefusedError(
                CHANNEL_CODE_NEVER_REPORTED, {"device": self._peer_key}
            )

    async def _read_forever(self) -> None:
        """Queue every record from the connection until it ends."""
        try:
            while True:
                try:
                    record = await read_record(self._reader)
                except ValueError:
                    record = None
                if record is None:
                    self._finish(
                        {
                            "code": AgentOfflineError.code,
                            "params": {"device": self._peer_key},
                        },
                        is_abandoned=True,
                    )
                    return
                record_type, payload = record
                if record_type == CHANNEL_RECORD_ACCEPT:
                    self.is_accepted = True
                    self._answered.set()
                elif record_type == CHANNEL_RECORD_CLOSE:
                    info = decode_json(payload)
                    params = info.get("params")
                    self._finish(
                        {
                            "code": str(info.get("code", "") or ""),
                            "params": dict(params) if isinstance(params, dict) else {},
                        }
                    )
                    await self._end_connection()
                    return
                elif record_type == CHANNEL_RECORD_RESIZE:
                    self._deliver((CHANNEL_ITEM_RESIZE, decode_json(payload)))
                elif record_type in ITEM_NAMES:
                    self._deliver((ITEM_NAMES[record_type], payload))
                elif record_type == CHANNEL_RECORD_OPEN:
                    continue
        except asyncio.CancelledError:
            raise

    def _deliver(self, item: tuple) -> None:
        if self._closed.is_set():
            return
        self._inbound.put_nowait(item)

    def _finish(self, info: dict, *, is_abandoned: bool = False) -> None:
        if self._closed.is_set():
            return
        self.is_abandoned = is_abandoned
        self.close_info = dict(info)
        self._closed.set()
        self._answered.set()
        self._inbound.put_nowait(None)

    async def _write(self, data: bytes) -> None:
        if self._closed.is_set():
            raise AgentOfflineError(self._peer_key)
        async with self._write_lock:
            try:
                self._writer.write(data)
                await self._writer.drain()
            except (ConnectionError, OSError, RuntimeError) as error:
                raise AgentOfflineError(self._peer_key) from error

    async def _end_connection(self) -> None:
        """Close the local connection once the stream is over."""
        try:
            self._writer.close()
        except (ConnectionError, OSError, RuntimeError):
            return
