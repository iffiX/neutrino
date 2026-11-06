"""Following xray's log for failed dials, and handing each one to the exit controller.

On Linux the log is the xray unit's journal, followed with ``journalctl -f``.
Outside Linux it is the child's log file under the hub's one service, read
from its end and opened again when the service rotates it.

Not pure: runs ``journalctl`` and reads a file, on a thread of its own.
"""

import logging
import subprocess
import threading
from pathlib import Path

from neutrino_hub.modules.xray.constants import (
    XRAY_LOG_FOLLOW_COMMAND,
    XRAY_LOG_FOLLOW_RETRY_S,
    XRAY_LOG_POLL_S,
)
from neutrino_hub.modules.xray.log_filter import failed_dial

LOGGER = logging.getLogger(__name__)


class XrayDialWatcher:
    """Hands every failed dial in xray's log to one callable.

    Attributes:
        on_failed_dial: Called with ``(host, port)`` for each failed dial.
        log_path: The child's log file it follows; None follows ``command``.
    """

    def __init__(
        self,
        *,
        on_failed_dial,
        log_path: "Path | None" = None,
        command: "list | None" = None,
    ):
        """
        Args:
            on_failed_dial: Called with ``(host, port)`` for each failed dial.
            log_path: The child's log file to follow; None follows the
                output of ``command``.
            command: The program whose output is the log;
                None is :data:`XRAY_LOG_FOLLOW_COMMAND`.
        """
        self.on_failed_dial = on_failed_dial
        self.log_path = log_path
        self._command = list(command or XRAY_LOG_FOLLOW_COMMAND)
        self._is_stopped = threading.Event()
        self._process: "subprocess.Popen | None" = None
        self._thread: "threading.Thread | None" = None

    def start(self) -> None:
        """Follow the log from now on; a second start is a no-op."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._loop, name="xray_dial_watcher", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop following; a running ``journalctl`` is ended."""
        self._is_stopped.set()
        process = self._process
        if process is not None and process.poll() is None:
            process.terminate()

    def _loop(self) -> None:
        """Follow the log, and follow it again after it ended."""
        while not self._is_stopped.is_set():
            try:
                if self.log_path is None:
                    self._follow_command()
                else:
                    self._follow_file(self.log_path)
            except OSError as error:
                LOGGER.warning("xray's log could not be followed: %s", error)
            self._is_stopped.wait(XRAY_LOG_FOLLOW_RETRY_S)

    def _follow_command(self) -> None:
        """Read each line the follow command prints, until it ends."""
        self._process = subprocess.Popen(
            self._command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        try:
            for line in self._process.stdout:
                if self._is_stopped.is_set():
                    break
                self._handle(line)
        finally:
            if self._process.poll() is None:
                self._process.terminate()
            self._process.wait()

    def _follow_file(self, path: Path) -> None:
        """Read the lines added to one file from its end, across its rotations.

        The file is opened only while it is read. The service on Windows
        cannot rename a file another process holds open.
        """
        position = path.stat().st_size if path.exists() else 0
        identity = self._identity(path)
        pending = ""
        while not self._is_stopped.wait(XRAY_LOG_POLL_S):
            now_identity = self._identity(path)
            if now_identity is None:
                continue
            if now_identity != identity or path.stat().st_size < position:
                identity, position, pending = now_identity, 0, ""
            try:
                with open(path, "rb") as stream:
                    stream.seek(position)
                    read = stream.read()
            except OSError:
                continue
            position += len(read)
            pending += read.decode("utf-8", "replace")
            *lines, pending = pending.split("\n")
            for line in lines:
                self._handle(line)

    @staticmethod
    def _identity(path: Path) -> "int | None":
        """The file the path names now, by its inode; None while there is none."""
        try:
            return path.stat().st_ino
        except OSError:
            return None

    def _handle(self, line: str) -> None:
        """Hand on a failed dial one line names."""
        address = failed_dial(line)
        if address is None:
            return
        try:
            self.on_failed_dial(*address)
        except Exception:  # noqa: BLE001 - one bad check never stops the watch
            LOGGER.exception("a failed dial could not be checked")
