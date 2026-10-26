"""A stand-in for the client's transport: its local channel, scripted by a test.

It listens on a Unix socket under a short temporary directory and speaks
the client's local channel as protocol.md "The local channel" gives it: a
first line with the secret and an ``op``, then on the control connection
the client's commands, answered by the line naming the command's ``id``,
the events and frames the test emits, and the frames the client writes; on
an ``open`` connection the stream's records, the test answering ``accept``
or a refusing ``close`` and then records, or raw bytes after the accept of
a ``connect``. A command the test scripted no answer for is answered
``{id}``; a scripted answer of None leaves it unanswered.
"""

import json
import os
import queue
import shutil
import socket
import struct
import tempfile
import threading

RECORD_HEADER = struct.Struct("!BI")
RECORD_ACCEPT = 2
RECORD_DATA = 3
RECORD_STDERR = 4
RECORD_EOF = 5
RECORD_RESIZE = 6
RECORD_DATAGRAM = 7
RECORD_CLOSE = 8
WAIT_S = 5


def unix_connect(path: str) -> socket.socket:
    """One connection to a Unix socket, as the platform opens the transport's."""
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        connection.connect(path)
    except OSError:
        connection.close()
        raise
    return connection


def read_exactly(connection, size: int) -> "bytes | None":
    data = b""
    while len(data) < size:
        more = connection.recv(size - len(data))
        if not more:
            return None
        data += more
    return data


class FakeStreamPeer:
    """The transport's end of one ``open`` connection.

    Attributes:
        binding: The binding the open named.
        open: The open record.
    """

    def __init__(self, connection, line: dict):
        self.binding = str(line.get("binding", ""))
        self.open = dict(line.get("open") or {})
        self._connection = connection

    def accept(self) -> None:
        self.send_record(RECORD_ACCEPT)

    def close(self, code: str = "", params: "dict | None" = None) -> None:
        payload = json.dumps({"code": code, "params": params or {}}).encode()
        self.send_record(RECORD_CLOSE, payload)

    def send_record(self, record_type: int, payload: bytes = b"") -> None:
        self._connection.sendall(
            RECORD_HEADER.pack(record_type, len(payload)) + payload
        )

    def send_raw(self, data: bytes) -> None:
        self._connection.sendall(data)

    def read_record(self) -> "tuple[int, bytes] | None":
        header = read_exactly(self._connection, RECORD_HEADER.size)
        if header is None:
            return None
        record_type, length = RECORD_HEADER.unpack(header)
        payload = read_exactly(self._connection, length) if length else b""
        return record_type, payload or b""

    def read_raw(self, size: int = 65536) -> bytes:
        return self._connection.recv(size)

    def end(self) -> None:
        try:
            self._connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self._connection.close()


class FakeTransport:
    """The client's transport, as one test scripts it.

    Attributes:
        listen: The socket path it listens on.
        secret: The secret every connection's first line must hold.
        answers: ``{command: callable(line) -> answer}``; an answer without
            ``id``, or None for none.
    """

    def __init__(self, secret: str = "ab" * 32):
        self.directory = tempfile.mkdtemp(prefix="nt", dir="/tmp")
        self.listen = os.path.join(self.directory, "t.sock")
        self.secret = secret
        self.answers: dict = {}
        self.commands: queue.Queue = queue.Queue()
        self.frames: queue.Queue = queue.Queue()
        self.opens: queue.Queue = queue.Queue()
        self.refused_connections = 0
        self._control = None
        self._control_ready = threading.Event()
        self._lock = threading.Lock()
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(self.listen)
        self._server.listen(16)
        self._is_closed = False
        threading.Thread(target=self._accept_forever, daemon=True).start()

    # --- what a test does ---

    def wait_control(self, timeout_s: float = WAIT_S) -> bool:
        return self._control_ready.wait(timeout_s)

    def emit(self, line: dict) -> None:
        self.wait_control()
        with self._lock:
            control = self._control
        control.sendall(json.dumps(line).encode() + b"\n")

    def frame(self, binding: str, frame: dict) -> None:
        self.emit({"frame": frame, "binding": binding})

    def next_command(self, name: str = "", timeout_s: float = WAIT_S) -> dict:
        """The next command the client sent, of one name when given; others are skipped."""
        while True:
            line = self.commands.get(timeout=timeout_s)
            if not name or line.get("command") == name:
                return line

    def next_frame(self, frame_type: str = "", timeout_s: float = WAIT_S) -> dict:
        """The next frame line the client sent, of one type when given."""
        while True:
            line = self.frames.get(timeout=timeout_s)
            if not frame_type or line["frame"].get("type") == frame_type:
                return line

    def next_open(self, timeout_s: float = WAIT_S) -> FakeStreamPeer:
        return self.opens.get(timeout=timeout_s)

    def drop_control(self) -> None:
        with self._lock:
            control, self._control = self._control, None
            self._control_ready.clear()
        if control is not None:
            try:
                control.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            control.close()

    def close(self) -> None:
        self._is_closed = True
        self.drop_control()
        try:
            self._server.close()
        except OSError:
            pass
        shutil.rmtree(self.directory, ignore_errors=True)

    # --- the loops ---

    def _accept_forever(self) -> None:
        while not self._is_closed:
            try:
                connection, _ = self._server.accept()
            except OSError:
                return
            threading.Thread(
                target=self._serve, args=(connection,), daemon=True
            ).start()

    def _serve(self, connection) -> None:
        first = self._read_line(connection)
        if first is None or first.get("secret") != self.secret:
            self.refused_connections += 1
            connection.close()
            return
        op = first.get("op")
        if op == "open":
            self.opens.put(FakeStreamPeer(connection, first))
            return
        if op != "control":
            connection.close()
            return
        with self._lock:
            self._control = connection
        self._control_ready.set()
        held = b""
        while True:
            try:
                data = connection.recv(65536)
            except OSError:
                return
            if not data:
                return
            held += data
            while b"\n" in held:
                raw, held = held.split(b"\n", 1)
                self._take(connection, json.loads(raw))

    def _take(self, connection, line: dict) -> None:
        if "frame" in line:
            self.frames.put(line)
            return
        if "command" not in line:
            return
        self.commands.put(line)
        answer_of = self.answers.get(line["command"])
        answer = {} if answer_of is None else answer_of(line)
        if answer is None:
            return
        connection.sendall(json.dumps(dict(answer, id=line["id"])).encode() + b"\n")

    @staticmethod
    def _read_line(connection) -> "dict | None":
        data = b""
        while not data.endswith(b"\n"):
            more = connection.recv(1)
            if not more:
                return None
            data += more
        return json.loads(data)
