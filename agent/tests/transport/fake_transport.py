"""The agent's transport, played by a test on a Unix socket of its own.

It speaks the agent's local channel: every connection's first line must
hold the secret; the control connection carries commands, which the fake
answers from a table a test fills, and the frames the agent writes, which
it records; a test sends events, frames and questions down it. ``attach``
and ``open`` connections carry records, kept for the test to drive.
"""

import json
import os
import queue
import shutil
import socket
import tempfile
import threading
import time

from neutrino_agent.transport.records import RecordReader, encode_record

ACCEPT = 2


class FakeConnection:
    """One local connection the agent opened, past its first line."""

    def __init__(self, sock, first: dict, buffer: bytes):
        self.socket = sock
        self.first = first
        self.reader = RecordReader(self)
        self.reader.take_buffer(buffer)

    def recv(self, size: int) -> bytes:
        return self.socket.recv(size)

    def read_record(self, timeout: float = 5.0):
        """The next record the agent wrote: ``(type, payload)``, None at the end."""
        self.socket.settimeout(timeout)
        try:
            return self.reader.read()
        finally:
            self.socket.settimeout(None)

    def write(self, data: bytes) -> None:
        self.socket.sendall(data)

    def close(self) -> None:
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.socket.close()


class FakeTransport:
    """A transport a test plays; built with :func:`start`, stopped with :meth:`stop`.

    Attributes:
        listen: The socket's path.
        secret: The secret every connection must open with.
        answers: Command name to its answer's fields, or to a function of
            the command's line returning them; a command not named is
            answered ``{}``.
        commands: Every command line the agent sent, in order.
        frames: Every frame the agent wrote, in order.
        attached: Stream id to its :class:`FakeConnection`.
        opened: Every ``open`` connection, in order.
        on_open: Called with an ``open`` connection to answer it; None
            accepts it.
        starts: How many times the agent started it.
    """

    def __init__(self):
        self._directory = tempfile.mkdtemp(prefix="nt", dir="/tmp")
        self.listen = os.path.join(self._directory, "t.sock")
        self.secret = "5e" * 32
        self.answers: dict = {}
        self.commands: list = []
        self.frames: list = []
        self.attached: dict = {}
        self.opened: list = []
        self.on_open = None
        self.starts = 0
        self.refused_connections = 0
        self._answers_seen: dict = {}
        self._control = None
        self._control_lock = threading.Lock()
        self._news = threading.Condition()
        self._question_ids = 0
        self._server = None
        self._is_running = False

    # --- what the agent sees ---

    def start(self) -> "FakeTransport":
        if self._server is None:
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(self.listen)
            server.listen(16)
            self._server = server
            threading.Thread(target=self._accept, daemon=True).start()
        self._is_running = True
        self.starts += 1
        return self

    def is_running(self) -> bool:
        return self._is_running

    def stop(self) -> None:
        self._is_running = False
        control = self._control
        if control is not None:
            control.close()

    def close(self) -> None:
        """End everything; the test's teardown."""
        self.stop()
        if self._server is not None:
            self._server.close()
        shutil.rmtree(self._directory, ignore_errors=True)

    # --- what the test drives ---

    def send_event(self, event: str, **fields) -> None:
        self._write_control({"event": event, **fields})

    def send_frame(self, frame: dict) -> None:
        self._write_control({"frame": frame})

    def ask(self, question: str, **fields) -> dict:
        """Ask the agent one question and wait for its answer."""
        with self._news:
            self._question_ids += 1
            question_id = f"q{self._question_ids}"
        self._write_control({"id": question_id, "question": question, **fields})
        return self.wait_for(lambda: self._answers_seen.get(question_id))

    def drop_control(self) -> None:
        """End the control connection, as a transport that exits does."""
        control = self._control
        if control is not None:
            control.close()

    def wait_for(self, check, timeout: float = 5.0):
        deadline = time.monotonic() + timeout
        with self._news:
            while True:
                value = check()
                if value:
                    return value
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AssertionError("the fake transport waited in vain")
                self._news.wait(min(remaining, 0.05))

    def wait_frame(self, kind: str, count: int = 1) -> dict:
        """The ``count``-th frame of one type the agent wrote."""
        frames = self.wait_for(
            lambda: [f for f in self.frames if f.get("type") == kind][count - 1 :]
            or None
        )
        return frames[0]

    def wait_command(self, name: str, count: int = 1) -> dict:
        lines = self.wait_for(
            lambda: [c for c in self.commands if c.get("command") == name][count - 1 :]
            or None
        )
        return lines[0]

    def wait_attached(self, stream_id: str) -> FakeConnection:
        return self.wait_for(lambda: self.attached.get(stream_id))

    def wait_opened(self, count: int = 1) -> FakeConnection:
        return self.wait_for(lambda: self.opened[count - 1 :] or None)[0]

    def welcome(
        self, address="tcp://192.0.2.1:8443", local="192.0.2.7:51000", **fields
    ):
        """Open a session and welcome the agent's hello on it."""
        before = len([f for f in self.frames if f.get("type") == "hello"])
        self.send_event("session_open", address=address, local_address=local)
        self.wait_frame("hello", before + 1)
        welcome = {
            "type": "welcome",
            "protocol": 4,
            "role": "hub",
            "id": "hub-1",
            "name": "lab-hub",
            "software": "neutrino_hub/0.0.0+dev",
            "time": time.time(),
        }
        welcome.update(fields)
        self.send_frame(welcome)

    # --- the fake's own ---

    def _write_control(self, line: dict) -> None:
        control = self.wait_for(lambda: self._control)
        with self._control_lock:
            control.write(json.dumps(line).encode() + b"\n")

    def _accept(self) -> None:
        while True:
            try:
                sock, _ = self._server.accept()
            except OSError:
                return
            threading.Thread(target=self._take, args=(sock,), daemon=True).start()

    def _take(self, sock) -> None:
        buffer = b""
        while b"\n" not in buffer:
            try:
                chunk = sock.recv(4096)
            except OSError:
                chunk = b""
            if not chunk:
                sock.close()
                return
            buffer += chunk
        line, _, rest = buffer.partition(b"\n")
        try:
            first = json.loads(line)
        except ValueError:
            first = {}
        if first.get("secret") != self.secret:
            self.refused_connections += 1
            sock.close()
            return
        connection = FakeConnection(sock, first, rest)
        op = first.get("op")
        if op == "control":
            self._serve_control(connection, rest)
        elif op == "attach":
            with self._news:
                self.attached[str(first.get("stream"))] = connection
                self._news.notify_all()
        elif op == "open":
            if self.on_open is not None:
                self.on_open(connection)
            else:
                connection.write(encode_record(ACCEPT))
            with self._news:
                self.opened.append(connection)
                self._news.notify_all()

    def _serve_control(self, connection: FakeConnection, rest: bytes) -> None:
        with self._news:
            self._control = connection
            self._news.notify_all()
        buffer = bytearray(rest)
        while True:
            while b"\n" in buffer:
                end = buffer.index(b"\n")
                line = json.loads(bytes(buffer[:end]))
                del buffer[: end + 1]
                self._take_line(connection, line)
            try:
                chunk = connection.socket.recv(65536)
            except OSError:
                chunk = b""
            if not chunk:
                with self._news:
                    if self._control is connection:
                        self._control = None
                    self._news.notify_all()
                return
            buffer.extend(chunk)

    def _take_line(self, connection: FakeConnection, line: dict) -> None:
        if "command" in line:
            answer = self.answers.get(line["command"], {})
            if callable(answer):
                answer = answer(line)
            with self._news:
                self.commands.append(line)
                self._news.notify_all()
            try:
                with self._control_lock:
                    connection.write(
                        json.dumps({"id": line["id"], **answer}).encode() + b"\n"
                    )
            except OSError:
                return
        elif "frame" in line:
            with self._news:
                self.frames.append(line["frame"])
                self._news.notify_all()
        elif "id" in line:
            with self._news:
                self._answers_seen[line["id"]] = line
                self._news.notify_all()


def starter_for(fake: FakeTransport):
    """An agent's ``transport_starter`` that starts the fake."""

    def start(_platform, _log):
        return fake.start()

    return start


def one_shot_for(fake: FakeTransport):
    """An agent's ``one_shot`` that reaches the fake through a real control client."""
    import contextlib

    from neutrino_agent.transport.connection import open_local
    from neutrino_agent.transport.control import TransportControlClient

    @contextlib.contextmanager
    def opener(on_event=None, on_frame=None):
        fake.start()
        control = TransportControlClient(
            connect=lambda: open_local(fake.listen),
            secret=fake.secret,
            on_event=on_event or (lambda event: None),
            on_frame=on_frame or (lambda frame: None),
            on_question=lambda question: {},
            log=lambda line: None,
        )
        control.start()
        try:
            yield control
        finally:
            control.close()

    return opener
