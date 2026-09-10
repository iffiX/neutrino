"""The WebSocket client: the frame codec, the handshake, and the refusals.

The codec is exercised as pure functions: every length form, client
masking, fragments put back together, and control frames kept small. The
handshake and the live rules run against a stub server on a runtime
generated certificate, the same pin the channel tests use, so nothing here
touches the network beyond the loopback.
"""

import hashlib
import json
import os
import shutil
import socket
import socketserver
import ssl
import struct
import subprocess
import threading

import pytest

from neutrino_client.constants import CLIENT_WS_CLOSE_REPLACED
from neutrino_client.core.channel import (
    GatewayRefused,
    GatewayRefusedDetail,
    GatewayUnreachable,
    GatewayUntrusted,
    GatewayVersionRefused,
)
from neutrino_client.core.ws_client import (
    OPCODE_BINARY,
    OPCODE_CLOSE,
    OPCODE_CONTINUATION,
    OPCODE_PING,
    OPCODE_PONG,
    OPCODE_TEXT,
    SocketClosed,
    WebSocketClient,
    accept_key,
    close_error,
    decode_frame,
    encode_frame,
)

WRONG_FINGERPRINT = "0" * 64


# --- the codec ---


@pytest.mark.parametrize("length", [0, 1, 125, 126, 65535, 65536, 70000])
def test_every_length_form_round_trips(length):
    payload = os.urandom(length)

    wire = encode_frame(OPCODE_BINARY, payload, mask_key=b"\x01\x02\x03\x04")
    frame, taken = decode_frame(wire)

    assert taken == len(wire)
    assert frame.opcode == OPCODE_BINARY
    assert frame.is_final
    assert frame.payload == payload


def test_a_client_frame_is_masked_on_the_wire():
    wire = encode_frame(OPCODE_TEXT, b"hello", mask_key=b"\xff\x00\xff\x00")

    assert wire[1] & 0x80
    assert wire[2:6] == b"\xff\x00\xff\x00"
    assert wire[6:] != b"hello"
    assert decode_frame(wire)[0].payload == b"hello"


def test_a_server_frame_comes_unmasked():
    wire = encode_frame(OPCODE_TEXT, b"hello")

    assert not wire[1] & 0x80
    assert wire[2:] == b"hello"


def test_a_partial_buffer_decodes_to_nothing_yet():
    wire = encode_frame(OPCODE_BINARY, b"x" * 300)

    assert decode_frame(wire[:1]) is None
    assert decode_frame(wire[:3]) is None
    assert decode_frame(wire[:-1]) is None
    assert decode_frame(wire) is not None


def test_a_control_frame_over_125_bytes_is_refused_both_ways():
    with pytest.raises(ValueError):
        encode_frame(OPCODE_PING, b"x" * 126)
    wire = bytes([0x80 | OPCODE_PING, 126]) + struct.pack("!H", 126) + b"x" * 126
    with pytest.raises(ValueError):
        decode_frame(wire)


def test_a_reserved_bit_is_refused():
    wire = bytearray(encode_frame(OPCODE_TEXT, b"x"))
    wire[0] |= 0x40

    with pytest.raises(ValueError):
        decode_frame(bytes(wire))


def test_the_accept_key_is_the_rfc_example():
    key = "dGhlIHNhbXBsZSBub25jZQ=="  # scan: allow
    expected = "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="  # scan: allow

    assert accept_key(key) == expected


# --- the live rules, over a scripted socket ---


class ScriptedSocket:
    """A socket whose reads come from a script and whose writes are kept."""

    def __init__(self, frames):
        self.inbound = b"".join(frames)
        self.sent = b""
        self.timeout = None
        self.is_closed = False

    def recv(self, size):
        if not self.inbound:
            raise socket.timeout("silence")
        chunk, self.inbound = self.inbound[:size], self.inbound[size:]
        return chunk

    def sendall(self, data):
        self.sent += data

    def settimeout(self, timeout):
        self.timeout = timeout

    def close(self):
        self.is_closed = True


def scripted_client(*frames) -> WebSocketClient:
    made = WebSocketClient(host="hub", port=1, path="/ws", fingerprint="f")
    made._sock = ScriptedSocket(frames)
    return made


def sent_frames(made: WebSocketClient, sock=None) -> list:
    """Every frame the client wrote, decoded."""
    data = (sock or made._sock).sent
    frames = []
    while data:
        frame, taken = decode_frame(data)
        frames.append(frame)
        data = data[taken:]
    return frames


def test_a_ping_is_answered_with_its_payload_and_never_returned():
    made = scripted_client(
        encode_frame(OPCODE_PING, b"keepalive"),
        encode_frame(OPCODE_TEXT, b'{"type": "welcome"}'),
    )

    kind, payload = made.recv()

    assert (kind, payload) == ("text", '{"type": "welcome"}')
    (pong,) = sent_frames(made)
    assert (pong.opcode, pong.payload) == (OPCODE_PONG, b"keepalive")


def test_fragmented_text_is_put_back_together():
    made = scripted_client(
        encode_frame(OPCODE_TEXT, "héllo ".encode("utf-8"), is_final=False),
        encode_frame(OPCODE_PONG, b""),
        encode_frame(OPCODE_CONTINUATION, b"wor", is_final=False),
        encode_frame(OPCODE_CONTINUATION, b"ld", is_final=True),
    )

    assert made.recv() == ("text", "héllo world")


def test_binary_comes_back_as_bytes():
    made = scripted_client(encode_frame(OPCODE_BINARY, b"\x00\x01"))

    assert made.recv() == ("binary", b"\x00\x01")


def test_a_close_from_the_hub_is_answered_and_raised():
    made = scripted_client(
        encode_frame(OPCODE_CLOSE, struct.pack("!H", 4401) + b"unknown_token")
    )
    sock = made._sock

    with pytest.raises(SocketClosed) as closed:
        made.recv()

    assert (closed.value.code, closed.value.reason) == (4401, "unknown_token")
    assert sock.is_closed
    (answer,) = sent_frames(made, sock)
    assert answer.opcode == OPCODE_CLOSE
    assert struct.unpack("!H", answer.payload[:2])[0] == 4401
    assert not made.is_open


def test_silence_past_the_timeout_is_a_dead_socket():
    made = scripted_client()

    with pytest.raises(GatewayUnreachable) as dead:
        made.recv()

    assert "no frame" in str(dead.value)
    assert not made.is_open


def test_what_the_client_sends_is_masked_text_and_binary():
    made = scripted_client()

    made.send_text('{"type": "hello"}')
    made.send_bytes(b"\x00\xff")

    text, binary = sent_frames(made)
    assert (text.opcode, text.payload) == (OPCODE_TEXT, b'{"type": "hello"}')
    assert (binary.opcode, binary.payload) == (OPCODE_BINARY, b"\x00\xff")
    assert made._sock.sent[1] & 0x80


def test_close_sends_the_code_and_shuts_the_socket():
    made = scripted_client()
    sock = made._sock

    made.close(1000, "bye")

    assert sock.is_closed
    (frame,) = sent_frames(made, sock)
    assert frame.opcode == OPCODE_CLOSE
    assert frame.payload == struct.pack("!H", 1000) + b"bye"
    assert not made.is_open
    with pytest.raises(GatewayUnreachable):
        made.send_text("x")


# --- what a close code means ---


def test_close_4401_is_a_refused_token():
    assert isinstance(close_error(4401, "unknown_token"), GatewayRefused)


def test_close_4409_names_the_refusal():
    newer = close_error(4409, "client_newer_than_hub")
    other = close_error(4409, "something_else")

    assert isinstance(newer, GatewayVersionRefused)
    assert isinstance(other, GatewayRefusedDetail)
    assert other.code == "something_else"


def test_close_4410_and_anything_else_is_unreachable():
    assert isinstance(
        close_error(CLIENT_WS_CLOSE_REPLACED, "replaced"), GatewayUnreachable
    )
    assert isinstance(close_error(1006, ""), GatewayUnreachable)


# --- the handshake, against a stub on a pinned certificate ---


class StubUpgradeHandler(socketserver.BaseRequestHandler):
    """Answers one upgrade the way the script says, then serves one frame."""

    answer = b""
    after = b""
    requests: list = []

    def handle(self):
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = self.request.recv(4096)
            if not chunk:
                return
            data += chunk
        StubUpgradeHandler.requests.append(data)
        answer = StubUpgradeHandler.answer
        if answer == b"accept":
            key = ""
            for line in data.split(b"\r\n"):
                if line.lower().startswith(b"sec-websocket-key:"):
                    key = line.split(b":", 1)[1].strip().decode()
            answer = (
                b"HTTP/1.1 101 Switching Protocols\r\n"
                b"Upgrade: websocket\r\nConnection: Upgrade\r\n"
                b"Sec-WebSocket-Accept: " + accept_key(key).encode() + b"\r\n\r\n"
            )
        self.request.sendall(answer + StubUpgradeHandler.after)
        try:
            self.request.recv(4096)
        except OSError:
            return


class QuietServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        """A connection dropped after the handshake is the pin working."""


@pytest.fixture
def tls_stub(tmp_path):
    """A TLS stub server and the fingerprint of its runtime-made certificate."""
    if shutil.which("openssl") is None:
        pytest.skip("openssl is not installed; the pin needs a certificate")
    certificate_path = tmp_path / "certificate.pem"
    key_path = tmp_path / "key.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(key_path),
            "-out",
            str(certificate_path),
            "-days",
            "2",
            "-nodes",
            "-subj",
            "/CN=test",
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    der = ssl.PEM_cert_to_DER_cert(certificate_path.read_text(encoding="utf-8"))
    fingerprint = hashlib.sha256(der).hexdigest()
    StubUpgradeHandler.requests = []
    StubUpgradeHandler.answer = b"accept"
    StubUpgradeHandler.after = b""
    server = QuietServer(("127.0.0.1", 0), StubUpgradeHandler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(certificate_path), str(key_path))
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1], fingerprint
    finally:
        server.shutdown()
        server.server_close()


def client_for(port: int, fingerprint: str) -> WebSocketClient:
    return WebSocketClient(
        host="127.0.0.1",
        port=port,
        path="/api/client/ws",
        fingerprint=fingerprint,
        timeout_s=5,
        silence_timeout_s=5,
    )


def test_the_upgrade_asks_for_a_websocket_and_checks_the_accept(tls_stub):
    port, fingerprint = tls_stub
    StubUpgradeHandler.after = encode_frame(OPCODE_TEXT, b'{"type": "welcome"}')
    made = client_for(port, fingerprint)

    made.connect()

    assert made.is_open
    (request,) = StubUpgradeHandler.requests
    head = request.decode()
    assert head.startswith("GET /api/client/ws HTTP/1.1\r\n")
    assert "Upgrade: websocket" in head
    assert "Sec-WebSocket-Version: 13" in head
    assert "Sec-WebSocket-Key: " in head
    # The frame that followed the handshake is not lost.
    assert made.recv() == ("text", '{"type": "welcome"}')
    made.close()


def test_a_wrong_fingerprint_is_refused_before_anything_is_sent(tls_stub):
    port, _ = tls_stub

    with pytest.raises(GatewayUntrusted):
        client_for(port, WRONG_FINGERPRINT).connect()

    assert StubUpgradeHandler.requests == []


def test_a_bad_accept_is_unreachable(tls_stub):
    port, fingerprint = tls_stub
    StubUpgradeHandler.answer = (
        b"HTTP/1.1 101 Switching Protocols\r\n"
        b"Sec-WebSocket-Accept: bm90IHJpZ2h0\r\n\r\n"
    )

    with pytest.raises(GatewayUnreachable):
        client_for(port, fingerprint).connect()


@pytest.mark.parametrize("status", [401, 403])
def test_a_refused_upgrade_is_a_refused_token(tls_stub, status):
    port, fingerprint = tls_stub
    StubUpgradeHandler.answer = (
        f"HTTP/1.1 {status} Nope\r\nContent-Length: 0\r\n\r\n".encode()
    )

    with pytest.raises(GatewayRefused):
        client_for(port, fingerprint).connect()


def test_a_409_upgrade_carries_its_code(tls_stub):
    port, fingerprint = tls_stub
    body = json.dumps(
        {
            "detail": {
                "code": "client_newer_than_hub",
                "params": {"hub_version": "0.1.0", "client_version": "0.2.0"},
            }
        }
    ).encode()
    StubUpgradeHandler.answer = (
        b"HTTP/1.1 409 Conflict\r\nContent-Length: "
        + str(len(body)).encode()
        + b"\r\n\r\n"
        + body
    )

    with pytest.raises(GatewayVersionRefused) as refused:
        client_for(port, fingerprint).connect()

    assert (refused.value.hub_version, refused.value.client_version) == (
        "0.1.0",
        "0.2.0",
    )


def test_another_status_is_unreachable(tls_stub):
    port, fingerprint = tls_stub
    StubUpgradeHandler.answer = b"HTTP/1.1 503 Busy\r\nContent-Length: 0\r\n\r\n"

    with pytest.raises(GatewayUnreachable):
        client_for(port, fingerprint).connect()


def test_a_dead_port_is_unreachable():
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()

    with pytest.raises(GatewayUnreachable):
        client_for(port, "ab" * 32).connect()


def test_the_silence_rule_is_the_open_sockets_timeout(tls_stub):
    port, fingerprint = tls_stub
    made = client_for(port, fingerprint)
    made._silence_timeout_s = 0.2

    made.connect()

    with pytest.raises(GatewayUnreachable):
        made.recv()
    assert not made.is_open
