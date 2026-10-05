"""One account's lock, held across processes for a whole switch or switch back.

The lock is a file under the agent's state root, one per account, locked
with ``fcntl.flock`` on Linux and macOS and ``msvcrt.locking`` on Windows.
The system releases it when the process holding it ends, so a file a killed
process left behind blocks no one.

Not pure: opens and locks a file.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
import time

from neutrino_agent.ai_tools.constants import (
    AI_TOOLS_CODE_SWITCH_FAILED,
    AI_TOOLS_LOCK_HELD_DETAIL,
    AI_TOOLS_LOCK_POLL_S,
    AI_TOOLS_LOCK_WAIT_S,
)
from neutrino_agent.exceptions import ToolSwitchError

try:
    import fcntl
except ImportError:  # Windows carries no fcntl.
    fcntl = None
try:
    import msvcrt
except ImportError:  # Only Windows carries msvcrt.
    msvcrt = None


class AiToolsAccountLock:
    """The lock one account's switch or switch back holds, in any process."""

    def __init__(
        self,
        *,
        path: str,
        account: str,
        wait_s: float = AI_TOOLS_LOCK_WAIT_S,
        poll_s: float = AI_TOOLS_LOCK_POLL_S,
    ):
        """
        Args:
            path: The lock's file; its directory is made, root's own.
            account: The account the lock is for, named in a refusal.
            wait_s: How long to wait for a held lock before giving up.
            poll_s: How long to wait between two tries.
        """
        self._path = path
        self._account = account
        self._wait_s = wait_s
        self._poll_s = poll_s
        self._fd: "int | None" = None

    def __enter__(self) -> "AiToolsAccountLock":
        self.acquire()
        return self

    def __exit__(self, *_exc) -> None:
        self.release()

    def acquire(self) -> None:
        """Take the lock, waiting while another run holds it.

        Raises:
            ToolSwitchError: ``switch_failed {account, detail}`` when another
                run still holds it after the wait.
            OSError: When the lock's file cannot be opened.
        """
        os.makedirs(os.path.dirname(self._path), mode=0o700, exist_ok=True)
        fd = os.open(self._path, os.O_RDWR | os.O_CREAT, 0o600)
        deadline = time.monotonic() + self._wait_s
        while True:
            try:
                _lock(fd)
            except OSError:
                if time.monotonic() >= deadline:
                    os.close(fd)
                    raise ToolSwitchError(
                        AI_TOOLS_CODE_SWITCH_FAILED,
                        {"account": self._account, "detail": AI_TOOLS_LOCK_HELD_DETAIL},
                    )
                time.sleep(self._poll_s)
                continue
            self._fd = fd
            return

    def release(self) -> None:
        """Give the lock back; quiet when it is not held."""
        fd, self._fd = self._fd, None
        if fd is None:
            return
        try:
            _unlock(fd)
        except OSError:
            pass
        os.close(fd)


def _lock(fd: int) -> None:
    """Lock a file without waiting; a system with neither call locks nothing.

    Raises:
        OSError: When another open of the file holds it.
    """
    if fcntl is not None:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    elif msvcrt is not None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)


def _unlock(fd: int) -> None:
    """Unlock a file this open holds."""
    if fcntl is not None:
        fcntl.flock(fd, fcntl.LOCK_UN)
    elif msvcrt is not None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
