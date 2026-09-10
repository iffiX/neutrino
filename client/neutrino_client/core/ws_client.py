"""A WebSocket client over the pinned socket, with the standard library.

One connection to the hub's client channel: an HTTP/1.1 upgrade, then RFC
6455 frames. Text and binary frames go up masked, as a client's must; control
frames are answered here so the caller only ever sees text, binary and the
close. Silence past the timeout is a dead socket.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import base64
import hashlib
import os
import select
import socket
import struct
import threading
import time

from neutrino_client import CLIENT_VERSION
from neutrino_client.constants import (
    CLIENT_REQUEST_TIMEOUT_S,
    CLIENT_WS_CLOSE_REFUSED,
    CLIENT_WS_CLOSE_UNKNOWN_TOKEN,
    CLIENT_WS_SILENCE_TIMEOUT_S,
)
from neutrino_client.core.channel import error_detail, pinned_socket
from neutrino_client.exceptions import (
    GatewayRefused,
    GatewayRefusedDetail,
    GatewayUnreachable,
    GatewayUntrusted,
    GatewayVersionRefused,
    SocketClosed,
)

# How long one wait for bytes lasts before the socket is looked at again.
WAIT_TURN_S = 0.5

OPCODE_CONTINUATION = 0x0
OPCODE_TEXT = 0x1
OPCODE_BINARY = 0x2
OPCODE_CLOSE = 0x8
OPCODE_PING = 0x9
OPCODE_PONG = 0xA

CONTROL_OPCODES = (OPCODE_CLOSE, OPCODE_PING, OPCODE_PONG)

# RFC 6455's fixed key suffix.
HANDSHAKE_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
HANDSHAKE_HEADER_LIMIT = 64 * 1024
CONTROL_PAYLOAD_LIMIT = 125
# How much one frame may carry before it is refused as unreasonable.
FRAME_PAYLOAD_LIMIT = 64 * 1024 * 1024

CLOSE_NORMAL = 1000


class Frame:
    """One decoded frame.

    Attributes:
        opcode: The frame's opcode.
        payload: The unmasked payload.
        is_final: Whether this frame ends its message.
    """

    def __init__(self, *, opcode: int, payload: bytes, is_final: bool = True):
        self.opcode = opcode
        self.payload = payload
        self.is_final = is_final


def encode_frame(
    opcode: int,
    payload: bytes,
    *,
    is_final: bool = True,
    mask_key: "bytes | None" = None,
) -> bytes:
    """One frame as bytes on the wire.

    Args:
        opcode: The frame's opcode.
        payload: The payload.
        is_final: Whether the frame ends its message.
        mask_key: Four bytes to mask with; None sends the frame unmasked,
            which only a server may.

    Returns:
        The encoded frame.

    Raises:
        ValueError: For a control frame carrying more than 125 bytes.
    """
    if opcode in CONTROL_OPCODES and len(payload) > CONTROL_PAYLOAD_LIMIT:
        raise ValueError("a control frame carries at most 125 bytes")
    head = bytearray([(0x80 if is_final else 0) | opcode])
    mask_bit = 0x80 if mask_key is not None else 0
    length = len(payload)
    if length < 126:
        head.append(mask_bit | length)
    elif length < 1 << 16:
        head.append(mask_bit | 126)
        head += struct.pack("!H", length)
    else:
        head.append(mask_bit | 127)
        head += struct.pack("!Q", length)
    if mask_key is None:
        return bytes(head) + payload
    return bytes(head) + mask_key + _mask(payload, mask_key)


def decode_frame(data: bytes) -> "tuple[Frame, int] | None":
    """One frame off the front of a buffer.

    Args:
        data: Bytes received so far.

    Returns:
        The frame and how many bytes it took, or None while the buffer
        holds less than one whole frame.

    Raises:
        ValueError: For a frame that cannot be right: a reserved bit set,
            a control frame over 125 bytes or fragmented, a payload past
            the limit.
    """
    if len(data) < 2:
        return None
    first, second = data[0], data[1]
    if first & 0x70:
        raise ValueError("reserved bits set with no extension negotiated")
    is_final = bool(first & 0x80)
    opcode = first & 0x0F
    is_masked = bool(second & 0x80)
    length = second & 0x7F
    offset = 2
    if length == 126:
        if len(data) < 4:
            return None
        length = struct.unpack("!H", data[2:4])[0]
        offset = 4
    elif length == 127:
        if len(data) < 10:
            return None
        length = struct.unpack("!Q", data[2:10])[0]
        offset = 10
    if opcode in CONTROL_OPCODES and (length > CONTROL_PAYLOAD_LIMIT or not is_final):
        raise ValueError("a control frame is small and whole")
    if length > FRAME_PAYLOAD_LIMIT:
        raise ValueError("frame payload past the limit")
    mask_key = b""
    if is_masked:
        if len(data) < offset + 4:
            return None
        mask_key = bytes(data[offset : offset + 4])
        offset += 4
    if len(data) < offset + length:
        return None
    payload = bytes(data[offset : offset + length])
    if is_masked:
        payload = _mask(payload, mask_key)
    return Frame(opcode=opcode, payload=payload, is_final=is_final), offset + length


def accept_key(key: str) -> str:
    """The ``Sec-WebSocket-Accept`` a server must answer one key with.

    Args:
        key: The ``Sec-WebSocket-Key`` sent.

    Returns:
        The expected accept value.
    """
    digest = hashlib.sha1((key + HANDSHAKE_GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def close_error(code: int, reason: str) -> Exception:
    """What a hub's close means to the caller.

    Args:
        code: The close code.
        reason: The reason word.

    Returns:
        The channel error the code maps to: a refused token for 4401, the
        named refusal for 4409, and an unreachable hub for anything else,
        the replaced code included.
    """
    if code == CLIENT_WS_CLOSE_UNKNOWN_TOKEN:
        return GatewayRefused(f"hub refused this client's token ({code})")
    if code == CLIENT_WS_CLOSE_REFUSED:
        return _refusal(reason, {})
    return GatewayUnreachable(f"hub closed the socket ({code}) {reason}".rstrip())


def _refusal(code: str, params: dict) -> Exception:
    """The channel error one refusal code word maps to."""
    if code == "client_newer_than_hub":
        return GatewayVersionRefused(
            hub_version=str(params.get("hub_version", "")),
            client_version=str(params.get("client_version", CLIENT_VERSION)),
        )
    if code:
        return GatewayRefusedDetail(code=code, params=dict(params))
    return GatewayUnreachable("hub refused the socket without a code")


def _mask(payload: bytes, key: bytes) -> bytes:
    """XOR a payload with a four-byte key, both ways."""
    if not payload:
        return b""
    repeated = (key * (len(payload) // 4 + 1))[: len(payload)]
    return bytes(a ^ b for a, b in zip(payload, repeated))


class WebSocketClient:
    """One socket to the hub: handshake, frames, and the close."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        path: str,
        fingerprint: str,
        timeout_s: float = CLIENT_REQUEST_TIMEOUT_S,
        silence_timeout_s: float = CLIENT_WS_SILENCE_TIMEOUT_S,
    ):
        """
        Args:
            host: The hub's address.
            port: The client channel's port.
            path: The socket's path on the hub.
            fingerprint: SHA-256 hex the hub's certificate must digest to.
            timeout_s: How long connecting and the handshake may take.
            silence_timeout_s: How long the open socket may stay silent.
        """
        self._host = host
        self._port = port
        self._path = path
        self._fingerprint = fingerprint
        self._timeout_s = timeout_s
        self._silence_timeout_s = silence_timeout_s
        self._sock: "socket.socket | None" = None
        self._buffer = b""
        # One TLS socket, two threads: the reader waits for bytes with the
        # lock released and holds it only to read; every write holds it.
        self._io_lock = threading.RLock()
        self._fragments: list = []
        self._fragment_opcode = 0

    @property
    def is_open(self) -> bool:
        """Whether the socket is connected."""
        return self._sock is not None

    def connect(self) -> None:
        """Connect over the pin and upgrade to a WebSocket.

        Raises:
            GatewayUntrusted: When the peer failed the fingerprint check.
            GatewayRefused: On a 401 or 403.
            GatewayVersionRefused: On a 409 naming this client as too new.
            GatewayUnreachable: On any network error, another status, or a
                handshake that does not check out.
        """
        try:
            sock = pinned_socket(
                self._host, self._port, self._fingerprint, timeout=self._timeout_s
            )
        except GatewayUntrusted:
            raise
        except OSError as error:
            raise GatewayUnreachable(f"cannot reach hub: {error}") from error
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {self._path} HTTP/1.1\r\n"
            f"Host: {self._host}:{self._port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        try:
            sock.sendall(request.encode("ascii"))
            status, headers, rest = self._read_handshake(sock)
            if status != 101:
                body = self._read_body(sock, headers, rest)
                sock.close()
                raise self._handshake_error(status, body)
            if headers.get("sec-websocket-accept", "") != accept_key(key):
                sock.close()
                raise GatewayUnreachable("hub answered a bad websocket accept")
        except (GatewayRefused, GatewayUnreachable):
            sock.close()
            raise
        except OSError as error:
            sock.close()
            raise GatewayUnreachable(f"websocket handshake failed: {error}") from error
        sock.settimeout(self._silence_timeout_s)
        self._sock = sock
        self._buffer = rest

    def send_text(self, text: str) -> None:
        """Send one text frame.

        Args:
            text: The text.

        Raises:
            GatewayUnreachable: When the socket is gone.
        """
        self._send(OPCODE_TEXT, text.encode("utf-8"))

    def send_bytes(self, data: bytes) -> None:
        """Send one binary frame.

        Args:
            data: The bytes.

        Raises:
            GatewayUnreachable: When the socket is gone.
        """
        self._send(OPCODE_BINARY, data)

    def recv(self) -> "tuple[str, object]":
        """The next message from the hub.

        Pings are answered here and never returned; pongs are dropped.

        Returns:
            ``("text", str)`` or ``("binary", bytes)``.

        Raises:
            SocketClosed: When the hub sent a close; the close is answered
                and the socket shut.
            GatewayUnreachable: On a network error, a silence past the
                timeout, or a frame that cannot be right.
        """
        while True:
            frame = self._read_frame()
            if frame.opcode == OPCODE_PING:
                self._send(OPCODE_PONG, frame.payload)
                continue
            if frame.opcode == OPCODE_PONG:
                continue
            if frame.opcode == OPCODE_CLOSE:
                code, reason = self._close_payload(frame.payload)
                self._shutdown(code)
                raise SocketClosed(code, reason)
            message = self._assemble(frame)
            if message is not None:
                return message

    def close(self, code: int = CLOSE_NORMAL, reason: str = "") -> None:
        """Send a close and shut the socket.

        Args:
            code: The close code.
            reason: The reason text.
        """
        self._shutdown(code, reason)

    def _send(self, opcode: int, payload: bytes) -> None:
        sock = self._sock
        if sock is None:
            raise GatewayUnreachable("the socket is closed")
        frame = encode_frame(opcode, payload, mask_key=os.urandom(4))
        with self._io_lock:
            try:
                sock.sendall(frame)
            except OSError as error:
                self._drop()
                raise GatewayUnreachable(f"socket send failed: {error}") from error

    def _read_frame(self) -> Frame:
        while True:
            try:
                decoded = decode_frame(self._buffer)
            except ValueError as error:
                self._drop()
                raise GatewayUnreachable(f"bad frame from hub: {error}") from error
            if decoded is not None:
                frame, taken = decoded
                self._buffer = self._buffer[taken:]
                return frame
            sock = self._sock
            if sock is None:
                raise GatewayUnreachable("the socket is closed")
            if not self._wait_readable(sock):
                self._drop()
                raise GatewayUnreachable(
                    f"no frame from hub in {self._silence_timeout_s}s"
                )
            try:
                with self._io_lock:
                    chunk = sock.recv(65536)
            except socket.timeout as error:
                self._drop()
                raise GatewayUnreachable(
                    f"no frame from hub in {self._silence_timeout_s}s"
                ) from error
            except OSError as error:
                self._drop()
                raise GatewayUnreachable(f"socket read failed: {error}") from error
            if not chunk:
                self._drop()
                raise GatewayUnreachable("hub hung up")
            self._buffer += chunk

    def _wait_readable(self, sock) -> bool:
        """Wait, without the lock, until a read would find bytes.

        Args:
            sock: The open socket. One without a descriptor is read at once.

        Returns:
            False when the silence timeout passed first.
        """
        if not hasattr(sock, "fileno"):
            return True
        pending = getattr(sock, "pending", None)
        if pending is not None and pending() > 0:
            return True
        # Waited in short turns: a socket another thread closed does not
        # wake a pending select on Windows, and a closing resident must
        # not wait out the silence timeout for its reader.
        deadline = time.monotonic() + self._silence_timeout_s
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            try:
                ready, _, _ = select.select([sock], [], [], min(remaining, WAIT_TURN_S))
            except (OSError, ValueError):
                return True
            if ready or self._sock is None:
                return True

    def _assemble(self, frame: Frame) -> "tuple[str, object] | None":
        """Put fragments together; a whole message comes back as one."""
        if frame.opcode == OPCODE_CONTINUATION:
            if not self._fragments:
                raise GatewayUnreachable("continuation with nothing to continue")
            self._fragments.append(frame.payload)
            if not frame.is_final:
                return None
            payload = b"".join(self._fragments)
            opcode = self._fragment_opcode
            self._fragments = []
        elif frame.opcode in (OPCODE_TEXT, OPCODE_BINARY):
            if not frame.is_final:
                self._fragments = [frame.payload]
                self._fragment_opcode = frame.opcode
                return None
            payload = frame.payload
            opcode = frame.opcode
        else:
            raise GatewayUnreachable(f"unknown opcode {frame.opcode}")
        if opcode == OPCODE_TEXT:
            try:
                return "text", payload.decode("utf-8")
            except UnicodeDecodeError as error:
                raise GatewayUnreachable("text frame is not UTF-8") from error
        return "binary", payload

    def _shutdown(self, code: int, reason: str = "") -> None:
        sock = self._sock
        if sock is None:
            return
        payload = struct.pack("!H", code) + reason.encode("utf-8")[:120]
        with self._io_lock:
            try:
                sock.sendall(
                    encode_frame(OPCODE_CLOSE, payload, mask_key=os.urandom(4))
                )
            except OSError:
                pass
        self._drop()

    def _drop(self) -> None:
        with self._io_lock:
            sock = self._sock
            self._sock = None
            if sock is None:
                return
            # The shutdown is what wakes a reader waiting on the socket
            # from another thread; a close alone leaves it waiting on
            # Windows.
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass

    def _read_handshake(self, sock) -> "tuple[int, dict, bytes]":
        """The status, the headers lower-cased, and whatever followed them."""
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = sock.recv(4096)
            if not chunk:
                raise GatewayUnreachable("hub hung up during the handshake")
            data += chunk
            if len(data) > HANDSHAKE_HEADER_LIMIT:
                raise GatewayUnreachable("handshake headers past the limit")
        head, rest = data.split(b"\r\n\r\n", 1)
        lines = head.decode("iso-8859-1").split("\r\n")
        parts = lines[0].split(" ", 2)
        try:
            status = int(parts[1])
        except (IndexError, ValueError) as error:
            raise GatewayUnreachable("hub sent no HTTP status") from error
        headers = {}
        for line in lines[1:]:
            name, _, value = line.partition(":")
            headers[name.strip().lower()] = value.strip()
        return status, headers, rest

    def _read_body(self, sock, headers: dict, rest: bytes) -> bytes:
        """The rest of a refusal's body, as far as its length says."""
        try:
            length = int(headers.get("content-length", "0") or 0)
        except ValueError:
            length = 0
        body = rest
        while len(body) < length:
            chunk = sock.recv(4096)
            if not chunk:
                break
            body += chunk
        return body[:length]

    def _handshake_error(self, status: int, body: bytes) -> Exception:
        if status in (401, 403):
            return GatewayRefused(f"hub refused this client's token ({status})")
        if status == 409:
            detail = error_detail(body)
            return _refusal(str(detail.get("code", "")), detail.get("params") or {})
        return GatewayUnreachable(f"hub answered {status} to the upgrade")

    def _close_payload(self, payload: bytes) -> "tuple[int, str]":
        if len(payload) < 2:
            return 1005, ""
        code = struct.unpack("!H", payload[:2])[0]
        return code, payload[2:].decode("utf-8", "replace")
