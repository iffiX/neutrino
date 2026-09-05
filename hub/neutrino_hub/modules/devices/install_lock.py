"""The one install lock a managed machine has.

``dpkg`` and its equivalents hold a machine-wide lock, so two installs racing
on one device is a failure with no useful diagnosis. The lock belongs to the
**device**, not to whatever wants to install: the module controller takes it
for an order, and the SSH bootstrap that puts the agent there in the first
place takes the same one, so "install the agent" and "install a remote
desktop" cannot overlap by construction.

Both users are served because both can hold it: a worker thread takes it
outright, and an async caller takes it off the event loop rather than
blocking everything else the panel is doing while it waits.

Not pure: a process-wide registry of locks.
"""

import asyncio
import threading
from contextlib import asynccontextmanager, contextmanager


class DeviceInstallLocks:
    """One install lock per device, handed to whoever asks for it."""

    def __init__(self):
        self._guard = threading.Lock()
        self._locks: dict = {}

    def lock_for(self, mac_address: str) -> threading.Lock:
        """The lock this device installs under.

        Args:
            mac_address: The device, lowercased the way everything keys it.

        Returns:
            The one lock for that device, created on first ask.
        """
        key = (mac_address or "").lower()
        with self._guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._locks[key] = lock
            return lock

    @contextmanager
    def hold(self, mac_address: str, *, timeout_s: "float | None" = None):
        """Hold a device's install lock for the length of a block.

        Args:
            mac_address: The device.
            timeout_s: How long to wait for it; None waits forever.

        Yields:
            True when the lock was taken, False when the wait ran out.
        """
        lock = self.lock_for(mac_address)
        is_held = lock.acquire(timeout=-1 if timeout_s is None else timeout_s)
        try:
            yield is_held
        finally:
            if is_held:
                lock.release()

    @asynccontextmanager
    async def hold_async(self, mac_address: str):
        """Hold a device's install lock from async code.

        The wait runs in a worker thread, so a device already installing
        something delays this caller and nothing else the panel serves.

        Args:
            mac_address: The device.

        Yields:
            None, once the lock is held.
        """
        lock = self.lock_for(mac_address)
        await asyncio.to_thread(lock.acquire)
        try:
            yield
        finally:
            lock.release()

    def is_held(self, mac_address: str) -> bool:
        """Whether something is installing on this device right now.

        Args:
            mac_address: The device.

        Returns:
            True while the lock is taken.
        """
        return self.lock_for(mac_address).locked()
