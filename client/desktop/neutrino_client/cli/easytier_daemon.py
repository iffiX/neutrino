"""``nclient easytier-daemon``: the EasyTier daemon, started by the system.

systemd on Linux and launchd on macOS run it as root in the foreground; the
Windows service control manager runs it as SYSTEM with ``--service``. It
makes its state directory, runs the core to match what that directory
holds, and answers on its socket until it is stopped, when the core is
stopped with it. Its log goes to standard error, and as a Windows service
to ``daemon.log`` in the client's log root, rotated; the core's output goes
to ``core.log`` beside it.
"""

import logging
import logging.handlers
import os
import signal
import sys
import threading

from neutrino_client.bundled import bundled_path
from neutrino_client.constants import (
    CLIENT_EASYTIER_CORE_LOG_NAME,
    CLIENT_EASYTIER_DAEMON_LOG_NAME,
    CLIENT_EASYTIER_LOG_KEEP_BYTES,
    CLIENT_EASYTIER_SERVICE_WINDOWS,
)
from neutrino_client.control.easytier_socket import EasytierSocketServer
from neutrino_client.core.easytier_daemon import EasytierDaemon
from neutrino_client.core.easytier_supervisor import EasytierCoreSupervisor
from neutrino_client.exceptions import PlatformUnsupportedError
from neutrino_client.platforms.detect import detect_platform

# --- config ---
LOG_FORMAT = "%(asctime)s %(message)s"
# The core stamps its own lines.
CORE_LOG_FORMAT = "%(message)s"
LOG_BACKUP_COUNT = 1
NOT_FROM_MANAGER = (
    "nclient easytier-daemon --service is started by the service control "
    "manager; run it without --service in a terminal instead"
)


def main(*, is_service: bool = False) -> int:
    """Run the daemon until it is stopped.

    Args:
        is_service: Run under the Windows service control manager.

    Returns:
        The process exit status: 1 when this platform carries no EasyTier,
        the state or the socket cannot be taken, or the process was not
        started as a service when it was asked to be one.
    """
    platform = detect_platform()
    try:
        state_dir = platform.easytier_state_dir()
    except PlatformUnsupportedError as error:
        print(f"no EasyTier daemon on this platform: {error}", file=sys.stderr)
        return 1
    if is_service:
        return _run_as_service(platform, state_dir)
    log = _stream_log()
    stopped = threading.Event()
    for name in ("SIGTERM", "SIGINT", "SIGHUP"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), lambda *_: stopped.set())
    try:
        parts = start_daemon(platform, state_dir, log)
    except OSError as error:
        log(f"could not start: {error}")
        return 1
    stopped.wait()
    stop_daemon(parts, log)
    return 0


def start_daemon(platform, state_dir: str, log) -> dict:
    """Make the state directory, run the core to match it, and serve the socket.

    Args:
        platform: The machine's platform.
        state_dir: The daemon's state directory.
        log: Callable used for progress messages.

    Returns:
        ``{"daemon", "supervisor", "server"}``, for :func:`stop_daemon`.

    Raises:
        OSError: When a directory or the socket cannot be taken.
    """
    platform.secure_easytier_state_dir(state_dir)
    core_log = file_log(
        os.path.join(_log_dir(platform), CLIENT_EASYTIER_CORE_LOG_NAME),
        "easytier_core",
        log_format=CORE_LOG_FORMAT,
    )
    holder: dict = {}
    supervisor = EasytierCoreSupervisor(
        command_of=lambda: holder["daemon"].core_command(),
        log=log,
        core_log=core_log,
        on_started=platform.bind_child_process,
    )
    daemon = EasytierDaemon(
        state_dir=state_dir,
        core_path=bundled_path("easytier-core"),
        supervisor=supervisor,
        log=log,
    )
    holder["daemon"] = daemon
    server = EasytierSocketServer(
        daemon=daemon, address=platform.easytier_daemon_address(), log=log
    )
    server.bind()
    daemon.restore()
    supervisor.start()
    server.start()
    return {"daemon": daemon, "supervisor": supervisor, "server": server}


def stop_daemon(parts: dict, log) -> None:
    """Stop serving and stop the core.

    Args:
        parts: What :func:`start_daemon` returned.
        log: Callable used for progress messages.
    """
    log("stopping")
    parts["server"].stop()
    parts["supervisor"].stop()


def file_log(path: str, name: str, *, log_format: str = LOG_FORMAT):
    """A log callable that writes to one file, kept to a size.

    Args:
        path: The file.
        name: The logger's name.
        log_format: How each line is written.

    Returns:
        A callable taking one message.
    """
    logger = logging.Logger(name, logging.INFO)
    handler = logging.handlers.RotatingFileHandler(
        path,
        maxBytes=CLIENT_EASYTIER_LOG_KEEP_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(log_format))
    logger.addHandler(handler)
    return logger.info


def _run_as_service(platform, state_dir: str) -> int:
    """Run under the Windows service control manager."""
    from neutrino_client.platforms.windows_service import ServiceControlDispatcher

    try:
        platform.secure_easytier_state_dir(state_dir)
        log = file_log(
            os.path.join(_log_dir(platform), CLIENT_EASYTIER_DAEMON_LOG_NAME),
            "easytier_daemon",
        )
    except OSError as error:
        print(f"could not make {state_dir}: {error}", file=sys.stderr)
        return 1
    held: dict = {}
    stopped = threading.Event()

    def on_start() -> None:
        held["parts"] = start_daemon(platform, state_dir, log)
        stopped.wait()

    def on_stop() -> None:
        parts = held.get("parts")
        if parts is not None:
            stop_daemon(parts, log)
        stopped.set()

    dispatcher = ServiceControlDispatcher(
        CLIENT_EASYTIER_SERVICE_WINDOWS, on_start, on_stop
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


def _stream_log():
    """A log callable that writes one line to standard error."""

    def log(message: str) -> None:
        print(f"easytier-daemon: {message}", file=sys.stderr, flush=True)

    return log
