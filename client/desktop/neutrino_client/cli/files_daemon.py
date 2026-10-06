"""``nclient files-daemon``: the files adapter's daemon, started by the system.

The Windows service control manager runs it as SYSTEM with ``--service``;
run without it, it serves in the foreground until interrupted. It answers on
its pipe, runs tun2socks on the adapter for the resident that asked last,
and stops tun2socks when it is stopped. As a service its log goes to
``files.log`` in the client's log root, rotated, and tun2socks's output to
``tun2socks.log`` beside it; in the foreground both go to standard error.
"""

import os
import signal
import sys
import threading

from neutrino_client.bundled import bundled_path
from neutrino_client.cli.easytier_daemon import file_log
from neutrino_client.constants import (
    CLIENT_FILES_DAEMON_LOG_NAME,
    CLIENT_FILES_SERVICE_WINDOWS,
    CLIENT_FILES_TUN2SOCKS_LOG_NAME,
)
from neutrino_client.control.easytier_socket import EasytierSocketServer
from neutrino_client.core.files_daemon import FILES_REFUSAL_CODE, FilesAdapterDaemon
from neutrino_client.exceptions import PlatformUnsupportedError
from neutrino_client.platforms.detect import detect_platform

# --- config ---
# tun2socks stamps its own lines.
TUN2SOCKS_LOG_FORMAT = "%(message)s"
NOT_FROM_MANAGER = (
    "nclient files-daemon --service is started by the service control "
    "manager; run it without --service in a terminal instead"
)


def main(*, is_service: bool = False) -> int:
    """Run the daemon until it is stopped.

    Args:
        is_service: Run under the Windows service control manager.

    Returns:
        The process exit status: 1 when this platform has no files adapter,
        the pipe cannot be taken, or the process was not started as a
        service when it was asked to be one.
    """
    platform = detect_platform()
    try:
        platform.files_daemon_address()
    except PlatformUnsupportedError as error:
        print(f"no files adapter on this platform: {error}", file=sys.stderr)
        return 1
    if is_service:
        return _run_as_service(platform)
    log = _stream_log()
    stopped = threading.Event()
    for name in ("SIGTERM", "SIGINT", "SIGHUP"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), _setter(stopped))
    try:
        parts = start_daemon(platform, log, tun2socks_log=log)
    except OSError as error:
        log(f"could not start: {error}")
        return 1
    stopped.wait()
    stop_daemon(parts, log)
    return 0


def start_daemon(platform, log, *, tun2socks_log=None) -> dict:
    """Serve the pipe, with tun2socks run only once a resident asks.

    Args:
        platform: The machine's platform.
        log: Callable used for progress messages.
        tun2socks_log: Called with each line tun2socks prints; None writes
            them to ``tun2socks.log`` in the client's log root.

    Returns:
        ``{"daemon", "server"}``, for :func:`stop_daemon`.

    Raises:
        OSError: When the log directory or the pipe cannot be taken.
    """
    if tun2socks_log is None:
        tun2socks_log = file_log(
            os.path.join(_log_dir(platform), CLIENT_FILES_TUN2SOCKS_LOG_NAME),
            "tun2socks",
            log_format=TUN2SOCKS_LOG_FORMAT,
        )
    daemon = FilesAdapterDaemon(
        tun2socks_path=bundled_path("tun2socks"),
        configure_adapter=platform.configure_files_adapter,
        bind_child=platform.bind_child_process,
        log=log,
        tun2socks_log=tun2socks_log,
        watch_process=platform.watch_process,
    )
    server = EasytierSocketServer(
        daemon=daemon,
        address=platform.files_daemon_address(),
        log=log,
        invalid_code=FILES_REFUSAL_CODE,
        identify=platform.daemon_peer,
    )
    server.bind()
    daemon.start()
    server.start()
    return {"daemon": daemon, "server": server}


def stop_daemon(parts: dict, log) -> None:
    """Stop serving and stop tun2socks, which takes the adapter with it.

    Args:
        parts: What :func:`start_daemon` returned.
        log: Callable used for progress messages.
    """
    log("stopping")
    parts["server"].stop()
    parts["daemon"].stop()


def _run_as_service(platform) -> int:
    """Run under the Windows service control manager."""
    from neutrino_client.platforms.windows_service import ServiceControlDispatcher

    try:
        log = file_log(
            os.path.join(_log_dir(platform), CLIENT_FILES_DAEMON_LOG_NAME),
            "files_daemon",
        )
    except OSError as error:
        print(f"could not open the log: {error}", file=sys.stderr)
        return 1
    held: dict = {}
    stopped = threading.Event()

    def on_start() -> None:
        held["parts"] = start_daemon(platform, log)
        stopped.wait()

    def on_stop() -> None:
        parts = held.get("parts")
        if parts is not None:
            stop_daemon(parts, log)
        stopped.set()

    dispatcher = ServiceControlDispatcher(
        CLIENT_FILES_SERVICE_WINDOWS, on_start, on_stop
    )
    try:
        dispatcher.run()
    except OSError as error:
        print(f"{NOT_FROM_MANAGER} ({error})", file=sys.stderr)
        return 1
    return 0


def _log_dir(platform) -> str:
    """The client's log root, made when it is missing."""
    directory = platform.easytier_log_dir()
    os.makedirs(directory, exist_ok=True)
    return directory


def _setter(event: threading.Event):
    """A signal handler that sets one event."""

    def handle(*_args) -> None:
        event.set()

    return handle


def _stream_log():
    """A log callable that writes one line to standard error."""

    def log(message: str) -> None:
        print(f"files-daemon: {message}", file=sys.stderr, flush=True)

    return log
