"""Whether each share's folder is a real folder, read by whoever owns its place.

A share's folder is real when it is there, it is a folder, and its last
level is no link. On Linux and macOS the read runs as the account that owns
the first level of the path an account owns, through the step-down, and as
root where every level is root's; a link or a folder others may write in
root's place reads as a link. On Windows the applier opens the folder by
handle. :class:`SambaFolderReader` takes the shares that cannot be served out
of a configuration at an apply, and at the report asks for a configure task
when a folder reads otherwise than the last apply read it, and once at the
first report of a run, before any apply read the folders.

Not pure: reads folders, as an account where the folder is in its place.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import dataclasses
import errno
import os
import threading
import time

try:
    import pwd
except ImportError:  # Windows has no account database of this kind.
    pwd = None

from neutrino_agent.modules.samba.config import SambaConfig
from neutrino_agent.modules.samba.constants import (
    SAMBA_FOLDER_CODES,
    SAMBA_FOLDER_LINK,
    SAMBA_FOLDER_MISSING,
    SAMBA_FOLDER_READ_TTL_S,
    SAMBA_FOLDER_REAL,
    SAMBA_FOLDER_SHELL,
    SAMBA_FOLDER_SHELL_EXITS,
    SAMBA_FOLDER_UNREACHABLE,
)
from neutrino_agent.modules.shared.account_files import AccountFiles
from neutrino_agent.modules.shared.handle_walk import open_dir, place_owner


def read_posix_folder(path: str, *, platform) -> str:
    """What a share's folder is on Linux or macOS, read by whoever owns its place.

    Args:
        path: The absolute folder.
        platform: The machine's platform, which steps down to the account.

    Returns:
        ``folder``, ``missing``, ``link`` or ``unreachable``.
    """
    path = os.path.normpath(path)
    try:
        owner = place_owner(path)
    except ValueError:
        return SAMBA_FOLDER_MISSING
    except OSError:
        return SAMBA_FOLDER_UNREACHABLE
    if owner is None:
        return SAMBA_FOLDER_LINK
    if owner == 0:
        return _read_in_roots_place(path)
    if pwd is None:
        return SAMBA_FOLDER_UNREACHABLE
    try:
        account = pwd.getpwuid(owner).pw_name
    except KeyError:
        return SAMBA_FOLDER_UNREACHABLE
    try:
        done = AccountFiles(platform=platform, account=account).run(
            ["/bin/sh", "-c", SAMBA_FOLDER_SHELL, path]
        )
    except OSError:
        return SAMBA_FOLDER_UNREACHABLE
    return SAMBA_FOLDER_SHELL_EXITS.get(done.returncode, SAMBA_FOLDER_UNREACHABLE)


def _read_in_roots_place(path: str) -> str:
    """A folder whose every level is root's, opened level by level with no link followed.

    A link at the last level is refused with ``ENOTDIR`` on Linux and with
    ``ELOOP`` on macOS, and the last level's own entry names it.
    """
    try:
        descriptor = open_dir(path)
    except FileNotFoundError:
        return SAMBA_FOLDER_MISSING
    except OSError as error:
        if error.errno in (errno.ELOOP, errno.ENOTDIR):
            if os.path.islink(path):
                return SAMBA_FOLDER_LINK
            return SAMBA_FOLDER_MISSING
        return SAMBA_FOLDER_UNREACHABLE
    os.close(descriptor)
    return SAMBA_FOLDER_REAL


def folder_refusal(found: str, path: str) -> dict:
    """The ``folder`` verb's answer for one read. Pure.

    Args:
        found: What the read found.
        path: The folder read.

    Returns:
        ``{"code", "params"}``, empty for a real folder.
    """
    if found == SAMBA_FOLDER_REAL:
        return {}
    return {"code": SAMBA_FOLDER_CODES[found], "params": {"path": path}}


class SambaFolderReader:
    """Each share's folder, read at an apply and again at the report."""

    def __init__(self, *, read, clock=time.monotonic):
        """
        Args:
            read: Called with a path; returns what the folder is.
            clock: The monotonic clock a read at the report ages on.
        """
        self._read = read
        self._clock = clock
        self._lock = threading.Lock()
        self._held: dict = {}
        self._named: list = []
        # None until an apply of this run reads the folders.
        self._applied: "dict | None" = None
        self._asked: set = set()

    def read(self, path: str) -> str:
        """Read one folder now, and keep the read for the report.

        Args:
            path: The folder.

        Returns:
            ``folder``, ``missing``, ``link`` or ``unreachable``.
        """
        found = self._read(path)
        with self._lock:
            self._held[path] = (found, self._clock())
        return found

    def take_config(self, config: dict) -> None:
        """Take the shares the state names, the ones the report reads.

        Args:
            config: The module's section in the state.
        """
        try:
            named = SambaConfig.from_dict(config).served_shares()
        except (TypeError, ValueError, AttributeError):
            named = []
        with self._lock:
            self._named = list(named)

    def served(self, config: SambaConfig) -> tuple:
        """The configuration less each served share whose folder is no real folder, read now.

        Args:
            config: The parsed configuration.

        Returns:
            ``(config, left_off)``: the configuration with those shares
            taken out, and ``{"code", "params"}`` for each, in its order.
        """
        found = {share.path: self.read(share.path) for share in config.served_shares()}
        with self._lock:
            self._applied = dict(found)
            self._asked = set()
        off = [
            share
            for share in config.served_shares()
            if found[share.path] != SAMBA_FOLDER_REAL
        ]
        if not off:
            return config, []
        names = {share.name for share in off}
        kept = [share for share in config.shares if share.name not in names]
        left_off = [
            {
                "code": SAMBA_FOLDER_CODES[found[share.path]],
                "params": {"name": share.name, "path": share.path},
            }
            for share in off
        ]
        return dataclasses.replace(config, shares=kept), left_off

    def forget(self) -> None:
        """Drop what the last apply read, as a removal of the configuration does."""
        with self._lock:
            self._applied = {}
            self._asked = set()

    def check(self, ask) -> None:
        """Read each share the state names again, at most every 30 seconds, and ask for a task on a change.

        A folder that reads otherwise than the last apply read it, gone,
        back, a link put in its place or one taken away, calls ``ask`` once
        for each change. A folder the reading account cannot reach calls
        nothing. Before any apply of this run, the first check calls ``ask``
        once, whatever the folders read.

        Args:
            ask: Asks for a configure task of the module.
        """
        with self._lock:
            named = list(self._named)
            is_first = self._applied is None and bool(named)
            if is_first:
                self._applied = {}
        if is_first:
            ask()
            return
        for share in named:
            found = self._kept(share.path)
            with self._lock:
                applied = (self._applied or {}).get(share.path)
                is_changed = (
                    applied is not None
                    and applied != found
                    and found != SAMBA_FOLDER_UNREACHABLE
                    and (share.path, found) not in self._asked
                )
                if is_changed:
                    self._asked.add((share.path, found))
            if is_changed:
                ask()

    def _kept(self, path: str) -> str:
        """One folder's read, read again once 30 seconds old."""
        with self._lock:
            held = self._held.get(path)
        if held is not None and self._clock() - held[1] < SAMBA_FOLDER_READ_TTL_S:
            return held[0]
        return self.read(path)


def refused_notes(left_off: list) -> list:
    """One note for each share left off the server. Pure."""
    return [
        f"left share {item['params'].get('name', '')} off the server: {item['code']}"
        for item in left_off
    ]
