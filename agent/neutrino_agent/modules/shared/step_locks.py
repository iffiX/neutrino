"""The step locks a module's steps take.

Three locks guard what two modules' tasks share: ``containers``,
Containers' engine; ``package_manager``, the system's installer; and
``system_accounts``, the machine's account database. A step names its locks
before it runs, takes all of them in :data:`AGENT_LOCK_ORDER`, and lets
them go when it ends. ``containers`` is taken shared or alone, and a taker
waiting to take it alone keeps new shared takers out. While a taker waits,
it is told which module holds the lock, the wait its row names.

Not pure: blocks the calling thread.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import threading

from neutrino_agent.constants import (
    AGENT_LOCK_ALONE,
    AGENT_LOCK_CONTAINERS,
    AGENT_LOCK_ORDER,
    AGENT_LOCK_SHARED,
    AGENT_LOCK_SYSTEM_ACCOUNTS,
    AGENT_WAIT_LOCK,
)

# The locks a taker may share; every other lock is taken alone.
SHARABLE_LOCKS = (AGENT_LOCK_CONTAINERS,)
# The step locks of a step that makes or removes the machine's accounts.
SYSTEM_ACCOUNTS_LOCKS = ((AGENT_LOCK_SYSTEM_ACCOUNTS, AGENT_LOCK_ALONE),)


def ordered(locks) -> tuple:
    """A step's locks, each once, in the order they are taken.

    Args:
        locks: ``(lock, mode)`` pairs, a lock named more than once among
            them; ``alone`` wins over ``shared`` for one lock.

    Returns:
        The pairs in :data:`AGENT_LOCK_ORDER`.

    Raises:
        KeyError: For a lock the order does not name.
    """
    modes: dict = {}
    for lock, mode in locks:
        if lock not in AGENT_LOCK_ORDER:
            raise KeyError(f"no step lock named {lock!r}")
        if mode == AGENT_LOCK_ALONE or lock not in SHARABLE_LOCKS:
            modes[lock] = AGENT_LOCK_ALONE
        else:
            modes.setdefault(lock, AGENT_LOCK_SHARED)
    return tuple((lock, modes[lock]) for lock in AGENT_LOCK_ORDER if lock in modes)


def is_in_order(locks) -> bool:
    """Whether a step's locks are named once each, in the order they are taken.

    Args:
        locks: ``(lock, mode)`` pairs.

    Returns:
        True when each lock is one the order names and none comes before
        one it follows.
    """
    names = [lock for lock, _mode in locks]
    if any(name not in AGENT_LOCK_ORDER for name in names):
        return False
    positions = [AGENT_LOCK_ORDER.index(name) for name in names]
    return positions == sorted(set(positions))


def lock_wait(lock: str, module: str) -> dict:
    """The wait a row names while a step waits for a step lock.

    Args:
        lock: The lock.
        module: The module whose task holds it, ``agent`` for the
            self-update.

    Returns:
        ``waiting_for_lock {lock, module}``.
    """
    return {"code": AGENT_WAIT_LOCK, "params": {"lock": lock, "module": module}}


class StepLock:
    """One step lock: taken alone, or shared where the lock allows it."""

    def __init__(self, name: str):
        """
        Args:
            name: The lock's name, one :data:`AGENT_LOCK_ORDER` names.
        """
        self.name = name
        self._condition = threading.Condition()
        # The holders sharing the lock, in the order they took it.
        self._shared: list = []
        # The holder that has it alone; empty for none.
        self._alone = ""
        # The takers waiting to have it alone, in the order they came.
        self._alone_waiting: list = []

    def holders(self) -> list:
        """The holders of the lock now.

        Returns:
            The one holder alone, or every shared holder in the order they
            took it; empty while nobody holds it.
        """
        with self._condition:
            return [self._alone] if self._alone else list(self._shared)

    def acquire(self, holder: str, mode: str, on_wait=None) -> None:
        """Take the lock, waiting while another holder keeps it.

        Args:
            holder: The module taking it.
            mode: ``shared`` or ``alone``; a lock nobody shares is taken
                alone either way.
            on_wait: Called with the module that keeps it each time that
                module changes while this taker waits; None tells nothing.
        """
        is_alone = mode == AGENT_LOCK_ALONE or self.name not in SHARABLE_LOCKS
        announced = ""
        with self._condition:
            if is_alone:
                self._alone_waiting.append(holder)
            try:
                while True:
                    blocker = self._blocker(holder, is_alone=is_alone)
                    if not blocker:
                        break
                    if on_wait is not None and blocker != announced:
                        announced = blocker
                        self._condition.release()
                        try:
                            on_wait(blocker)
                        finally:
                            self._condition.acquire()
                        continue
                    self._condition.wait()
                if is_alone:
                    self._alone = holder
                else:
                    self._shared.append(holder)
            finally:
                if is_alone:
                    self._alone_waiting.remove(holder)

    def try_acquire(self, holder: str, mode: str) -> bool:
        """Take the lock when nobody keeps it, and never wait.

        Args:
            holder: The module taking it.
            mode: ``shared`` or ``alone``.

        Returns:
            Whether it was taken.
        """
        is_alone = mode == AGENT_LOCK_ALONE or self.name not in SHARABLE_LOCKS
        with self._condition:
            if self._blocker(holder, is_alone=is_alone):
                return False
            if is_alone:
                self._alone = holder
            else:
                self._shared.append(holder)
            return True

    def release(self, holder: str) -> None:
        """Let the lock go.

        Args:
            holder: The module that took it.

        Raises:
            RuntimeError: When the holder does not hold it.
        """
        with self._condition:
            if self._alone == holder:
                self._alone = ""
            elif holder in self._shared:
                self._shared.remove(holder)
            else:
                raise RuntimeError(f"{holder} does not hold {self.name}")
            self._condition.notify_all()

    def _blocker(self, holder: str, *, is_alone: bool) -> str:
        """The module that keeps a taker out now, empty when none does. Call under the condition."""
        if self._alone:
            return self._alone
        if is_alone:
            return self._shared[0] if self._shared else ""
        others = [name for name in self._alone_waiting if name != holder]
        return others[0] if others else ""


class StepLocks:
    """The three step locks of one agent."""

    def __init__(self):
        # One lock per name, in the order they are taken.
        self._locks = {name: StepLock(name) for name in AGENT_LOCK_ORDER}

    def holders(self, lock: str) -> list:
        """The modules holding one lock now.

        Args:
            lock: The lock's name.

        Returns:
            Their names, as :meth:`StepLock.holders` gives them.

        Raises:
            KeyError: For a lock the order does not name.
        """
        return self._locks[lock].holders()

    def acquire(self, locks, holder: str, on_wait=None) -> None:
        """Take a step's locks in the order, waiting for each.

        Args:
            locks: ``(lock, mode)`` pairs.
            holder: The module taking them.
            on_wait: Called with the wait's ``{code, params}`` while one
                lock is kept by another module.

        Raises:
            KeyError: For a lock the order does not name.
        """
        taken = []
        try:
            for lock, mode in ordered(locks):
                self._locks[lock].acquire(
                    holder, mode, on_wait=_announcer(lock, on_wait)
                )
                taken.append(lock)
        except BaseException:
            for lock in reversed(taken):
                self._locks[lock].release(holder)
            raise

    def try_acquire(self, locks, holder: str) -> bool:
        """Take a step's locks when none is kept, and never wait.

        Args:
            locks: ``(lock, mode)`` pairs.
            holder: The module taking them.

        Returns:
            Whether all of them were taken; none is kept when one was not.
        """
        taken = []
        for lock, mode in ordered(locks):
            if not self._locks[lock].try_acquire(holder, mode):
                for held in reversed(taken):
                    self._locks[held].release(holder)
                return False
            taken.append(lock)
        return True

    def release(self, locks, holder: str) -> None:
        """Let a step's locks go, the last taken first.

        Args:
            locks: ``(lock, mode)`` pairs, as they were taken.
            holder: The module that took them.
        """
        for lock, _mode in reversed(ordered(locks)):
            self._locks[lock].release(holder)

    @contextlib.contextmanager
    def held(self, locks, holder: str, on_wait=None):
        """Hold a step's locks for the length of the block.

        Args:
            locks: ``(lock, mode)`` pairs.
            holder: The module taking them.
            on_wait: As :meth:`acquire` takes it.

        Yields:
            Nothing; the locks are held inside the block.
        """
        self.acquire(locks, holder, on_wait=on_wait)
        try:
            yield
        finally:
            self.release(locks, holder)


def _announcer(lock: str, on_wait):
    """What one lock calls while its taker waits, or None."""
    if on_wait is None:
        return None

    def announce(module: str) -> None:
        on_wait(lock_wait(lock, module))

    return announce
