"""The resident's local channel to its transport, and the transport it runs.

The transport is the Go program that holds this person's session to every
hub joined and every forward: the resident runs it as its own child, in its
own account, with ``client --listen <socket>`` and the channel's secret on
the first line of its standard input, made afresh at each start. Standard
input stays open; the transport ends when it closes.

One control connection carries JSON lines both ways: the resident's
commands (``dial``, ``undial``, ``round``, ``join``, ``leave``,
``forward_start``, ``forward_stop``) each answered by the line naming its
``id``, the transport's events, and the frames of each hub's control
stream, ``{frame, binding}``. Every other stream is a connection of its own,
opened with an ``open`` line naming the binding and the stream's ``open``
record. Events and frames are handed to their listeners on one thread of
their own, in order, so a listener may wait for a command's answer.

A transport that ends, or a control connection that drops, is started again
after a wait that doubles; the listeners are told it was lost, and told
again when it is back, with nothing kept: every hub is dialled again and
every forward started again by whoever wants it.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import itertools
import json
import os
import queue
import secrets
import socket
import subprocess
import threading
import time

from neutrino_client.constants import (
    CLIENT_TRANSPORT_COMMAND_TIMEOUT_S,
    CLIENT_TRANSPORT_LISTEN_FLAG,
    CLIENT_TRANSPORT_MODE,
    CLIENT_TRANSPORT_RESTART_MAX_S,
    CLIENT_TRANSPORT_RESTART_MIN_S,
    CLIENT_TRANSPORT_SECRET_BYTES,
    CLIENT_TRANSPORT_START_TIMEOUT_S,
    CLIENT_TRANSPORT_STOP_TIMEOUT_S,
)
from neutrino_client.core.streams import ClientStream
from neutrino_client.exceptions import GatewayUnreachable

# The most one line of the control connection may take, the transport's
# ``ControlFrameBytesMax``.
TRANSPORT_LINE_BYTES_MAX = 2 * 1024 * 1024
# The bytes one read of the control connection takes.
TRANSPORT_READ_BYTES = 64 * 1024
# How often a start looks whether the transport listens yet.
TRANSPORT_CONNECT_PAUSE_S = 0.05
# The ``op`` of each kind of local connection.
TRANSPORT_OP_CONTROL = "control"
TRANSPORT_OP_OPEN = "open"


def make_secret() -> str:
    """A fresh secret for the local channel: 32 random bytes as 64 hex characters."""
    return secrets.token_hex(CLIENT_TRANSPORT_SECRET_BYTES)


def _nobody(*_args) -> None:
    """Nobody listening."""


class ClientTransportProcess:
    """The transport program, run as the resident's child with a fresh secret at each start."""

    def __init__(self, *, program: str, listen: str, log_path: str, bind_child=None):
        """
        Args:
            program: The transport's executable.
            listen: The socket path or pipe name it listens on.
            log_path: Where its output is written, appended to.
            bind_child: ``bind_child(process)`` ties the child's life to
                this process where the system can; None ties nothing.
        """
        self._program = program
        self._listen = listen
        self._log_path = log_path
        self._bind_child = bind_child if bind_child is not None else _nobody
        self._process: "subprocess.Popen | None" = None
        self._log_file = None
        self._lock = threading.Lock()

    @property
    def listen(self) -> str:
        """The socket path or pipe name the transport listens on."""
        return self._listen

    def start(self) -> str:
        """Start the transport and hand it a fresh secret.

        A transport still running from an earlier start is stopped first.

        Returns:
            The secret its listener now asks of every connection.

        Raises:
            OSError: When the program cannot be started.
        """
        self.stop()
        directory = os.path.dirname(self._listen)
        if directory and not self._listen.startswith("\\\\"):
            os.makedirs(directory, mode=0o700, exist_ok=True)
            try:
                os.unlink(self._listen)
            except FileNotFoundError:
                pass
        os.makedirs(os.path.dirname(self._log_path) or ".", exist_ok=True)
        secret = make_secret()
        log_file = open(self._log_path, "ab")
        try:
            process = subprocess.Popen(
                [
                    self._program,
                    CLIENT_TRANSPORT_MODE,
                    CLIENT_TRANSPORT_LISTEN_FLAG,
                    self._listen,
                ],
                stdin=subprocess.PIPE,
                stdout=log_file,
                stderr=log_file,
            )
        except OSError:
            log_file.close()
            raise
        try:
            process.stdin.write((secret + "\n").encode("ascii"))
            process.stdin.flush()
        except OSError:
            process.kill()
            log_file.close()
            raise
        try:
            self._bind_child(process)
        except OSError:
            pass
        with self._lock:
            self._process = process
            self._log_file = log_file
        return secret

    def is_running(self) -> bool:
        """Whether the transport this object started still runs."""
        with self._lock:
            process = self._process
        return process is not None and process.poll() is None

    def stop(self) -> None:
        """End the transport: its standard input closed, then killed when it lingers. Idempotent."""
        with self._lock:
            process, self._process = self._process, None
            log_file, self._log_file = self._log_file, None
        if process is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
            try:
                process.wait(timeout=CLIENT_TRANSPORT_STOP_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if log_file is not None:
            log_file.close()


class ClientTransportChannel:
    """The local channel to the transport: its commands, its events and its streams."""

    def __init__(
        self,
        *,
        connect,
        process=None,
        listen: str = "",
        secret: str = "",
        log=print,
        start_timeout_s: float = CLIENT_TRANSPORT_START_TIMEOUT_S,
        restart_min_s: float = CLIENT_TRANSPORT_RESTART_MIN_S,
        restart_max_s: float = CLIENT_TRANSPORT_RESTART_MAX_S,
    ):
        """
        Args:
            connect: ``connect(listen)`` opens one local connection to the
                transport: ``recv``, ``sendall``, ``shutdown``, ``close``;
                raises ``OSError`` while nothing listens.
            process: The :class:`ClientTransportProcess` the channel starts
                and starts again; None for a transport already listening.
            listen: Where a transport already listening listens; ignored
                with a process.
            secret: The secret a transport already listening asks; ignored
                with a process.
            log: Callable used for progress messages.
            start_timeout_s: How long a started transport may take to listen.
            restart_min_s: The least wait before the transport is started
                again.
            restart_max_s: The most.
        """
        self._connect = connect
        self._process = process
        self._listen = process.listen if process is not None else listen
        self._log = log
        self._start_timeout_s = start_timeout_s
        self._restart_min_s = restart_min_s
        self._restart_max_s = restart_max_s
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._secret = secret
        self._control = None
        self._ids = itertools.count(1)
        # Each command waiting for its answer: id to [event, answer].
        self._waiting: dict = {}
        # Who hears what, by binding, and the forwards' and the channel's own.
        self._binding_listeners: dict = {}
        self._forward_listeners: list = []
        self._ready_listeners: list = []
        self._lost_listeners: list = []
        self._events: queue.Queue = queue.Queue()
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._thread: "threading.Thread | None" = None

    # --- who hears what ---

    def listen_binding(self, binding: str, listener) -> None:
        """Hand one binding's events and frames to a listener.

        Args:
            binding: The binding's label, as the commands name it.
            listener: ``listener(line)`` takes each event line naming the
                binding and each ``{frame, binding}`` line, on the channel's
                own thread.
        """
        with self._lock:
            self._binding_listeners[binding] = listener

    def forget_binding(self, binding: str, listener=None) -> None:
        """Stop handing one binding's lines to its listener.

        Args:
            binding: The binding's label.
            listener: The listener to forget; None forgets whichever holds
                the label.
        """
        with self._lock:
            held = self._binding_listeners.get(binding)
            if listener is None or held == listener:
                self._binding_listeners.pop(binding, None)

    def on_forward_end(self, listener) -> None:
        """Hand every ``forward_end`` to a listener.

        Args:
            listener: ``listener(line)``, on the channel's own thread.
        """
        with self._lock:
            self._forward_listeners.append(listener)

    def on_ready(self, listener) -> None:
        """Be told each time the transport is started and its control connection opens.

        Args:
            listener: Called with no arguments, on the channel's own thread.
        """
        with self._lock:
            self._ready_listeners.append(listener)

    def on_lost(self, listener) -> None:
        """Be told each time the transport ended or its control connection dropped.

        Args:
            listener: Called with no arguments, on the channel's own thread.
        """
        with self._lock:
            self._lost_listeners.append(listener)

    # --- what the resident does ---

    def start(self) -> None:
        """Start the transport and keep it running, on threads of the channel's own."""
        self._thread = threading.Thread(
            target=self._hold_forever, name="client_transport", daemon=True
        )
        self._thread.start()
        threading.Thread(
            target=self._dispatch_forever, name="client_transport_events", daemon=True
        ).start()

    def stop(self) -> None:
        """Close the control connection and end the transport. Idempotent."""
        self._stop.set()
        self._drop_control()
        if self._process is not None:
            self._process.stop()
        self._events.put(None)

    def is_ready(self) -> bool:
        """Whether the control connection is open."""
        return self._ready.is_set()

    def wait_ready(self, timeout_s: float) -> bool:
        """Wait until the control connection is open.

        Args:
            timeout_s: How long to wait.

        Returns:
            Whether it is.
        """
        return self._ready.wait(timeout_s)

    def command(
        self,
        command: str,
        fields: dict,
        timeout_s: float = CLIENT_TRANSPORT_COMMAND_TIMEOUT_S,
    ) -> dict:
        """Send one command and wait for its answer.

        Args:
            command: ``dial``, ``undial``, ``round``, ``join``, ``leave``,
                ``forward_start`` or ``forward_stop``.
            fields: The command's own fields.
            timeout_s: How long to wait for the answer.

        Returns:
            The answer without its ``id``: empty, the command's result, or
            ``{code, params}`` when the transport refused.

        Raises:
            GatewayUnreachable: When the transport is not running, its
                connection drops, or no answer comes in time.
        """
        command_id = str(next(self._ids))
        waiter = [threading.Event(), None]
        with self._lock:
            self._waiting[command_id] = waiter
        try:
            self._write({"id": command_id, "command": command, **dict(fields)})
            if not waiter[0].wait(timeout=timeout_s):
                raise GatewayUnreachable(f"the transport did not answer {command}")
        finally:
            with self._lock:
                self._waiting.pop(command_id, None)
        answer = waiter[1]
        if answer is None:
            raise GatewayUnreachable("the transport's connection closed")
        answer = dict(answer)
        answer.pop("id", None)
        return answer

    def send_frame(self, binding: str, frame: dict, is_last: bool = False) -> None:
        """Send one frame on a hub's control stream.

        Args:
            binding: The binding's label.
            frame: The frame, ``{type, ...body}``.
            is_last: Whether the transport ends the session once it is written.

        Raises:
            GatewayUnreachable: When the transport is not running.
        """
        line = {"frame": dict(frame), "binding": binding}
        if is_last:
            line["is_last"] = True
        self._write(line)

    def open_stream(
        self,
        binding: str,
        open_record: dict,
        *,
        is_raw_after_accept: bool = False,
        is_fd_tagged: bool = False,
    ) -> ClientStream:
        """Open one stream on a hub's session, through a connection of its own.

        Args:
            binding: The binding's label.
            open_record: The ``open`` record, ``{kind, ...args}``.
            is_raw_after_accept: Whether it carries raw bytes after the
                ``accept``, as a TCP ``connect`` does.
            is_fd_tagged: Whether each piece read starts with its output's
                byte, as an ``exec`` without a terminal gives them.

        Returns:
            The stream, its answer still to come.

        Raises:
            GatewayUnreachable: When the transport is not running.
        """
        with self._lock:
            secret = self._secret
        if not self._ready.is_set():
            raise GatewayUnreachable("the client's transport is not running")
        try:
            connection = self._connect(self._listen)
        except OSError as error:
            raise GatewayUnreachable(f"the client's transport is unreachable: {error}")
        try:
            connection.sendall(
                _line(
                    {
                        "secret": secret,
                        "op": TRANSPORT_OP_OPEN,
                        "binding": binding,
                        "open": dict(open_record),
                    }
                )
            )
        except OSError as error:
            connection.close()
            raise GatewayUnreachable(f"the client's transport is unreachable: {error}")
        return ClientStream(
            connection=connection,
            kind=str(open_record.get("kind", "")),
            is_raw_after_accept=is_raw_after_accept,
            is_fd_tagged=is_fd_tagged,
        )

    # --- the loops ---

    def _hold_forever(self) -> None:
        """Start the transport, read its control connection, and start it again when it ends."""
        wait_s = self._restart_min_s
        while not self._stop.is_set():
            control = self._open_control()
            if control is None:
                if self._stop.wait(wait_s):
                    return
                wait_s = min(wait_s * 2, self._restart_max_s)
                continue
            wait_s = self._restart_min_s
            self._read_control(control)
            self._lose(control)
            if self._stop.wait(self._restart_min_s):
                return

    def _open_control(self):
        """Start the transport when this channel runs it, and open the control connection.

        Returns:
            The open connection; None when the transport could not be
            started or did not listen in time.
        """
        if self._process is not None:
            try:
                secret = self._process.start()
            except OSError as error:
                self._log(f"the transport could not start: {error}")
                return None
            with self._lock:
                self._secret = secret
        with self._lock:
            secret = self._secret
        deadline = time.monotonic() + self._start_timeout_s
        while not self._stop.is_set():
            try:
                control = self._connect(self._listen)
                control.sendall(_line({"secret": secret, "op": TRANSPORT_OP_CONTROL}))
            except OSError as error:
                if time.monotonic() >= deadline:
                    self._log(
                        f"the transport does not listen at {self._listen}: {error}"
                    )
                    return None
                self._stop.wait(TRANSPORT_CONNECT_PAUSE_S)
                continue
            with self._lock:
                self._control = control
            self._ready.set()
            self._log(f"the transport listens at {self._listen}")
            self._events.put(("ready", None))
            return control
        return None

    def _read_control(self, control) -> None:
        """Read the control connection's lines until it ends."""
        held = b""
        while not self._stop.is_set():
            try:
                data = control.recv(TRANSPORT_READ_BYTES)
            except OSError:
                return
            if not data:
                return
            held += data
            while b"\n" in held:
                raw, held = held.split(b"\n", 1)
                self._take_line(raw)
            if len(held) > TRANSPORT_LINE_BYTES_MAX:
                self._log("the transport sent a line past the limit; reconnecting")
                return

    def _take_line(self, raw: bytes) -> None:
        """Answer a waiting command, or queue an event or a frame for its listener."""
        try:
            line = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            self._log("the transport sent a line that is not JSON")
            return
        if not isinstance(line, dict):
            return
        if "id" in line and "event" not in line and "frame" not in line:
            with self._lock:
                waiter = self._waiting.get(str(line.get("id")))
            if waiter is not None:
                waiter[1] = line
                waiter[0].set()
            return
        self._events.put(("line", line))

    def _lose(self, control) -> None:
        """The control connection ended: every waiter fails, every listener hears."""
        self._ready.clear()
        with self._lock:
            if self._control is control:
                self._control = None
            waiting = list(self._waiting.values())
        for waiter in waiting:
            waiter[0].set()
        try:
            control.close()
        except OSError:
            pass
        if not self._stop.is_set():
            self._log("the transport's control connection closed; starting it again")
        self._events.put(("lost", None))

    def _dispatch_forever(self) -> None:
        """Hand every queued event, frame and change to its listeners, in order."""
        while True:
            item = self._events.get()
            if item is None:
                return
            kind, line = item
            try:
                self._dispatch(kind, line)
            except Exception as error:  # noqa: BLE001 - a listener's own failure
                self._log(
                    f"a transport listener failed: {type(error).__name__}: {error}"
                )

    def _dispatch(self, kind: str, line) -> None:
        """Hand one item to its listeners."""
        with self._lock:
            ready = list(self._ready_listeners)
            lost = list(self._lost_listeners)
            forwards = list(self._forward_listeners)
            listener = None
            if line is not None:
                listener = self._binding_listeners.get(str(line.get("binding", "")))
        if kind == "ready":
            for each in ready:
                each()
        elif kind == "lost":
            for each in lost:
                each()
        elif line.get("event") == "forward_end":
            for each in forwards:
                each(line)
        elif listener is not None:
            listener(line)

    def _write(self, line: dict) -> None:
        """Write one line on the control connection.

        Raises:
            GatewayUnreachable: When the transport is not running.
        """
        with self._lock:
            control = self._control
        if control is None:
            raise GatewayUnreachable("the client's transport is not running")
        try:
            with self._write_lock:
                control.sendall(_line(line))
        except OSError as error:
            raise GatewayUnreachable(f"the client's transport is unreachable: {error}")

    def _drop_control(self) -> None:
        """Close the control connection from this side."""
        with self._lock:
            control = self._control
        if control is not None:
            try:
                control.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                control.close()
            except OSError:
                pass


def _line(value: dict) -> bytes:
    """One JSON line."""
    return json.dumps(value, separators=(",", ":")).encode("utf-8") + b"\n"
