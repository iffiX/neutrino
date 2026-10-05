"""What the files daemon keeps up on Windows, and what it answers.

The daemon runs tun2socks on the wintun adapter ``neutrino_files``, pointed
at the SOCKS endpoint of the resident that asked last, and gives the adapter
its address each time tun2socks has opened it, then answers ``up`` only
once a connection through the adapter is answered: for some seconds after
the address is given the adapter accepts a connection and loses its bytes,
and the system's SMB client then reports a refused login or a lost
network name for a share that is fine. Nothing is kept on disk: a
daemon that starts serves nobody until a resident asks.

One request is one JSON object with a ``verb``:

    {"verb": "up", "port", "user", "password"}
    {"verb": "down"}
    {"verb": "status"}

Every accepted request is answered with the status, ``{"is_up", "port"}``; a
refusal is ``{"code": "files_adapter_unavailable", "params": {"detail"}}``.
Neither ever carries the user name or the password.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import os
import re
import socket
import threading
import time

from neutrino_client.constants import (
    CLIENT_FILES_ADAPTER_MTU,
    CLIENT_FILES_ADAPTER_NAME,
    CLIENT_FILES_ADAPTER_READY_S,
    CLIENT_FILES_DAEMON_TICK_S,
    CLIENT_FILES_PROBE_ADDRESS,
    CLIENT_FILES_PROBE_PAUSE_S,
    CLIENT_FILES_PROBE_PORT,
    CLIENT_FILES_PROBE_TIMEOUT_S,
    CLIENT_FILES_TUN2SOCKS_LOG_LEVEL,
)
from neutrino_client.core.easytier_supervisor import EasytierCoreSupervisor

VERB_UP = "up"
VERB_DOWN = "down"
VERB_STATUS = "status"
FILES_REFUSAL_CODE = "files_adapter_unavailable"
# What the endpoint's user name and password may hold: the characters a
# proxy address carries without escaping.
FILES_CREDENTIAL_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,128}")
# The endpoint listens on this machine's loopback alone.
FILES_ENDPOINT_HOST = "127.0.0.1"
# The most a refusal's detail carries.
FILES_DETAIL_LIMIT_CHARS = 200


def tun2socks_command(binary: str, *, port: int, user: str, password: str) -> list:
    """How tun2socks starts on the adapter, pointed at the resident's endpoint.

    Args:
        binary: The carried tun2socks.
        port: The endpoint's port on the loopback.
        user: The endpoint's user name.
        password: The endpoint's password.

    Returns:
        The argument vector.
    """
    return [
        binary,
        "--device",
        f"tun://{CLIENT_FILES_ADAPTER_NAME}",
        "--proxy",
        f"socks5://{user}:{password}@{FILES_ENDPOINT_HOST}:{port}",  # scan: allow
        "--mtu",
        str(CLIENT_FILES_ADAPTER_MTU),
        "--loglevel",
        CLIENT_FILES_TUN2SOCKS_LOG_LEVEL,
    ]


def adapter_carries(dial=None) -> bool:
    """Whether one connection through the adapter is answered.

    The probe goes to an address and port the resident's endpoint refuses,
    so tun2socks ends it at once while the adapter carries connections, and
    nothing answers while it does not.

    Args:
        dial: ``dial(address, timeout)`` returns a connected socket; None
            is :func:`socket.create_connection`.

    Returns:
        True when the far side ended the connection or sent anything within
        the probe's timeout.
    """
    dial = dial if dial is not None else socket.create_connection
    try:
        connection = dial(
            (CLIENT_FILES_PROBE_ADDRESS, CLIENT_FILES_PROBE_PORT),
            CLIENT_FILES_PROBE_TIMEOUT_S,
        )
    except OSError:
        return False
    try:
        connection.settimeout(CLIENT_FILES_PROBE_TIMEOUT_S)
        connection.recv(1)
        return True
    except ConnectionError:
        return True
    except OSError:
        return False
    finally:
        connection.close()


def files_refusal(detail: str) -> dict:
    """The one refusal the daemon answers.

    Args:
        detail: What failed, in a few words.

    Returns:
        ``{"code": "files_adapter_unavailable", "params": {"detail"}}``.
    """
    return {"code": FILES_REFUSAL_CODE, "params": {"detail": detail}}


def _endpoint_of(request: dict) -> "dict | None":
    """The endpoint an ``up`` names, or None when it names none usable."""
    port = request.get("port")
    user = request.get("user")
    password = request.get("password")
    if not isinstance(port, int) or isinstance(port, bool) or not 0 < port < 65536:
        return None
    for value in (user, password):
        if not isinstance(value, str) or not FILES_CREDENTIAL_PATTERN.fullmatch(value):
            return None
    return {"port": port, "user": user, "password": password}


def _nobody(*_args) -> None:
    """Nobody listening."""


def _detail(error: OSError) -> str:
    """An error's words, cut to what a refusal carries."""
    return str(error.strerror or error)[:FILES_DETAIL_LIMIT_CHARS]


class FilesAdapterDaemon:
    """tun2socks on the adapter for the resident that asked last, and the requests."""

    def __init__(
        self,
        *,
        tun2socks_path: str,
        configure_adapter,
        bind_child=None,
        log=print,
        tun2socks_log=None,
        start_process=None,
        probe=None,
        clock=None,
        sleep=None,
    ):
        """
        Args:
            tun2socks_path: The carried tun2socks, empty when this install
                carries none.
            configure_adapter: Gives the adapter tun2socks opened its
                address, metric and DNS settings; raises ``OSError`` with
                what failed.
            bind_child: Called with each tun2socks once started, to tie it
                to the daemon's life; None ties nothing.
            log: Callable used for progress messages; it never sees the
                user name or the password.
            tun2socks_log: Called with each line tun2socks prints; None
                drops them.
            start_process: ``start_process(argv, env)`` starts tun2socks;
                None starts a real process.
            probe: Returns whether a connection through the adapter is
                answered; None is :func:`adapter_carries`.
            clock: Returns the time in seconds; None is ``time.monotonic``.
            sleep: Waits a number of seconds; None is ``time.sleep``.
        """
        self._tun2socks_path = tun2socks_path
        self._configure_adapter = configure_adapter
        self._bind_child = bind_child if bind_child is not None else _nobody
        self._probe = probe if probe is not None else adapter_carries
        self._clock = clock if clock is not None else time.monotonic
        self._sleep = sleep if sleep is not None else time.sleep
        self._log = log
        self._lock = threading.Lock()
        self._endpoint: "dict | None" = None
        self._is_configured = False
        self._is_address_due = threading.Event()
        self._stop = threading.Event()
        self._supervisor = EasytierCoreSupervisor(
            command_of=self.command,
            log=log,
            core_log=tun2socks_log,
            start_process=start_process,
            on_started=self.started,
            name="tun2socks",
        )

    @property
    def supervisor(self) -> EasytierCoreSupervisor:
        """What runs tun2socks."""
        return self._supervisor

    def start(self) -> None:
        """Watch tun2socks and the adapter on threads of their own until :meth:`stop`."""
        self._supervisor.start()
        threading.Thread(
            target=self._watch_forever, name="files_adapter", daemon=True
        ).start()

    def stop(self) -> None:
        """Stop watching and end tun2socks, which takes the adapter with it. Idempotent."""
        self._stop.set()
        with self._lock:
            self._endpoint = None
            self._is_configured = False
        self._supervisor.stop()

    def command(self) -> "tuple[list, dict] | None":
        """tun2socks's argument vector and environment for the endpoint served.

        Returns:
            ``(argv, env)``; None when no resident is served or this install
            carries no tun2socks.
        """
        endpoint = self._endpoint
        if endpoint is None or not self._tun2socks_path:
            return None
        argv = tun2socks_command(
            self._tun2socks_path,
            port=endpoint["port"],
            user=endpoint["user"],
            password=endpoint["password"],
        )
        return argv, dict(os.environ)

    def started(self, process) -> None:
        """Tie a started tun2socks to the daemon and mark the address as due.

        Args:
            process: The started process.

        Raises:
            OSError: When it cannot be tied.
        """
        self._is_address_due.set()
        self._bind_child(process)

    def status(self) -> dict:
        """Whether the adapter is up and which endpoint it serves.

        Returns:
            ``{"is_up", "port"}``, the port 0 while nobody is served.
        """
        endpoint = self._endpoint
        return {
            "is_up": bool(
                endpoint is not None
                and self._is_configured
                and self._supervisor.is_running
            ),
            "port": endpoint["port"] if endpoint is not None else 0,
        }

    def handle(self, request) -> dict:
        """Answer one request.

        Args:
            request: The decoded request.

        Returns:
            The status after it, or the refusal.
        """
        if not isinstance(request, dict):
            return files_refusal("request_invalid")
        verb = request.get("verb")
        if verb == VERB_STATUS:
            return self.status()
        if verb == VERB_DOWN:
            with self._lock:
                self._take_down()
            return self.status()
        if verb != VERB_UP:
            return files_refusal("request_invalid")
        endpoint = _endpoint_of(request)
        if endpoint is None:
            return files_refusal("request_invalid")
        if not self._tun2socks_path:
            self._log("no tun2socks in this install")
            return files_refusal("bundle_missing")
        with self._lock:
            return self._bring_up(endpoint)

    def tick(self) -> None:
        """Give a restarted tun2socks's adapter its address again."""
        with self._lock:
            if self._endpoint is None or not self._is_address_due.is_set():
                return
            if not self._supervisor.is_running:
                return
            try:
                self._configure()
            except OSError as error:
                self._log(
                    f"the adapter could not be given its address: {_detail(error)}"
                )
                return
            self._log("the adapter has its address again")

    def _bring_up(self, endpoint: dict) -> dict:
        """Serve one endpoint, under the lock."""
        if (
            endpoint == self._endpoint
            and self._is_configured
            and self._supervisor.is_running
            and not self._is_address_due.is_set()
        ):
            return self.status()
        self._endpoint = endpoint
        self._is_configured = False
        self._is_address_due.clear()
        self._supervisor.apply()
        if not self._supervisor.is_running:
            self._take_down()
            return files_refusal("tun2socks_not_started")
        try:
            self._configure()
        except OSError as error:
            detail = _detail(error)
            self._log(f"the adapter could not be given its address: {detail}")
            self._take_down()
            return files_refusal(detail)
        self._log(f"up for the endpoint on {FILES_ENDPOINT_HOST}:{endpoint['port']}")
        return self.status()

    def _configure(self) -> None:
        """Give the adapter its address and wait until it carries a connection, under the lock.

        Raises:
            OSError: When the address cannot be given, or no probe is
                answered within ``CLIENT_FILES_ADAPTER_READY_S``.
        """
        self._is_address_due.clear()
        self._is_configured = False
        self._configure_adapter()
        deadline = self._clock() + CLIENT_FILES_ADAPTER_READY_S
        started = self._clock()
        while not self._probe():
            if self._clock() >= deadline:
                raise OSError(
                    f"the adapter {CLIENT_FILES_ADAPTER_NAME} carries no connection"
                )
            self._sleep(CLIENT_FILES_PROBE_PAUSE_S)
        self._log(
            f"the adapter carries connections after {self._clock() - started:.1f} s"
        )
        self._is_configured = True

    def _take_down(self) -> None:
        """Serve nobody and end tun2socks, under the lock."""
        was_serving = self._endpoint is not None
        self._endpoint = None
        self._is_configured = False
        self._is_address_due.clear()
        self._supervisor.apply()
        if was_serving:
            self._log("down")

    def _watch_forever(self) -> None:
        while not self._stop.wait(CLIENT_FILES_DAEMON_TICK_S):
            try:
                self.tick()
            except Exception as error:  # noqa: BLE001 - the watch must survive
                self._log(f"the adapter could not be watched: {error}")
