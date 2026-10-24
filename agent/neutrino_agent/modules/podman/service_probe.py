"""Detecting what answers on a container's published TCP port.

Three steps, each on a connection of its own: a read for a service that
speaks first, a plain HTTP request, and the same request over TLS with no
certificate check. A result is kept per container start and port, and the
probes a report starts run side by side under one bounded wait.

Not pure: opens connections to the machine's own ports.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import socket
import ssl
import threading
import time

from neutrino_agent.modules.podman.constants import (
    PODMAN_DETECTED_HTTP,
    PODMAN_DETECTED_HTTPS,
    PODMAN_DETECTED_TCP,
    PODMAN_PROBE_PLAIN_TO_TLS_STATUS,
    PODMAN_PROBE_READ_S,
    PODMAN_PROBE_REPLY_BYTES,
    PODMAN_PROBE_REPLY_PREFIX,
    PODMAN_PROBE_REQUEST,
    PODMAN_PROBE_STEP_S,
    PODMAN_PROBE_WAIT_S,
)


def detect_service(
    address: str,
    port: int,
    *,
    read_s: float = PODMAN_PROBE_READ_S,
    step_s: float = PODMAN_PROBE_STEP_S,
) -> str:
    """What one TCP port answers as.

    Args:
        address: Where the port is dialled.
        port: The port.
        read_s: How long the first step waits for the service to speak.
        step_s: How long each step waits to connect, and each later step
            for its reply.

    Returns:
        ``tcp`` for a service that speaks first, ``http`` for a reply that
        starts ``HTTP/``, ``https`` for the same over TLS, ``tcp`` for any
        other; empty while the port does not accept a connection.
    """
    try:
        greeting = _first_bytes(address, port, read_s=read_s, step_s=step_s)
    except OSError:
        return ""
    if greeting:
        return PODMAN_DETECTED_TCP
    plain = _http_reply(address, port, step_s=step_s, is_tls=False)
    if plain.startswith(PODMAN_PROBE_REPLY_PREFIX) and not _is_plain_to_tls(plain):
        return PODMAN_DETECTED_HTTP
    secure = _http_reply(address, port, step_s=step_s, is_tls=True)
    if secure.startswith(PODMAN_PROBE_REPLY_PREFIX):
        return PODMAN_DETECTED_HTTPS
    if plain.startswith(PODMAN_PROBE_REPLY_PREFIX):
        return PODMAN_DETECTED_HTTP
    return PODMAN_DETECTED_TCP


def _first_bytes(address: str, port: int, *, read_s: float, step_s: float) -> bytes:
    """What the service sends before it is sent anything, empty for nothing."""
    with socket.create_connection((address, port), timeout=step_s) as connection:
        connection.settimeout(read_s)
        try:
            return connection.recv(1)
        except OSError:
            return b""


def _http_reply(address: str, port: int, *, step_s: float, is_tls: bool) -> bytes:
    """The first bytes of the reply to the probe's request, empty for none."""
    deadline = time.monotonic() + step_s
    try:
        with socket.create_connection((address, port), timeout=step_s) as raw:
            if not is_tls:
                return _reply(raw, deadline)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            raw.settimeout(max(deadline - time.monotonic(), 0.01))
            with context.wrap_socket(raw) as secure:
                return _reply(secure, deadline)
    except (OSError, ValueError):
        return b""


def _reply(connection, deadline: float) -> bytes:
    """Send the request and read up to the status code of the reply."""
    connection.sendall(PODMAN_PROBE_REQUEST)
    reply = b""
    while len(reply) < PODMAN_PROBE_REPLY_BYTES:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        connection.settimeout(remaining)
        try:
            chunk = connection.recv(PODMAN_PROBE_REPLY_BYTES - len(reply))
        except OSError:
            break
        if not chunk:
            break
        reply += chunk
    return reply


def _is_plain_to_tls(reply: bytes) -> bool:
    """Whether a plain reply is the 400 a web server with TLS on the port gives."""
    words = reply.split(b" ")
    return len(words) > 1 and words[1] == PODMAN_PROBE_PLAIN_TO_TLS_STATUS


class PodmanServiceProbe:
    """Detects the published TCP ports of running containers, once per start."""

    def __init__(
        self,
        *,
        read_s: float = PODMAN_PROBE_READ_S,
        step_s: float = PODMAN_PROBE_STEP_S,
        wait_s: float = PODMAN_PROBE_WAIT_S,
    ):
        """
        Args:
            read_s: How long the first step waits for the service to speak.
            step_s: How long each step waits to connect and for a reply.
            wait_s: The longest :meth:`detected` waits for the probes it
                started.
        """
        self._read_s = read_s
        self._step_s = step_s
        self._wait_s = wait_s
        self._lock = threading.Lock()
        self._results: dict = {}
        self._running: dict = {}

    def detected(self, targets: list) -> dict:
        """What each port answers as, probing the ports not detected yet.

        A result is forgotten once its key is no longer a target, so a
        container that stops or starts again is detected again.

        Args:
            targets: ``(key, address, port)`` each, ``key`` naming the
                container's start and the port.

        Returns:
            Key to ``http``, ``https`` or ``tcp``; a key whose port has not
            accepted a connection yet, or whose probe outlasted the wait, is
            absent.
        """
        keys = {key for key, _, _ in targets}
        threads = []
        with self._lock:
            for key in list(self._results):
                if key not in keys:
                    del self._results[key]
            for key, address, port in targets:
                if key in self._results or key in self._running:
                    continue
                thread = threading.Thread(
                    target=self._probe, args=(key, address, port), daemon=True
                )
                self._running[key] = thread
                threads.append(thread)
        for thread in threads:
            thread.start()
        deadline = time.monotonic() + self._wait_s
        for thread in threads:
            thread.join(max(deadline - time.monotonic(), 0))
        with self._lock:
            return {key: self._results[key] for key in keys if key in self._results}

    def _probe(self, key: tuple, address: str, port: int) -> None:
        """Detect one port and keep what it answers as."""
        result = ""
        try:
            result = detect_service(
                address, port, read_s=self._read_s, step_s=self._step_s
            )
        finally:
            with self._lock:
                self._running.pop(key, None)
                if result:
                    self._results[key] = result
