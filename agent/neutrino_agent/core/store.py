"""The one store for what this machine decided for itself.

The record is machine state: it lives here, survives a hub restore untouched,
and appears in no hub backup. The file is root-owned mode 0600. Secrets never
enter it: the share's access password lives in its own credentials file
beside it.

Every write re-reads the file under one lock and lands atomically — a
temporary file in the same directory, then ``os.replace``.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import json
import os
import threading

from neutrino_agent.constants import AGENT_STATE_PATH


class MachineStateStore:
    """Reads and writes this machine's own record."""

    def __init__(self, *, path: str = ""):
        """
        Args:
            path: Where the store lives on disk; empty uses the agent's own.
        """
        self._path = path or AGENT_STATE_PATH
        self._lock = threading.RLock()

    def rdp_share(self) -> dict:
        """What this machine last decided about sharing its desktop.

        Returns:
            ``{"share_id", "is_shared", "port", "account"}``, empty until
            somebody shares. The access password is not here: it lives in
            its own root-only file.
        """
        record = self._read().get("rdp", {})
        return dict(record) if isinstance(record, dict) else {}

    def set_rdp_share(self, record: dict) -> None:
        """Record that this machine shares its desktop.

        Args:
            record: ``{"share_id", "is_shared", "port", "account"}``; any
                ``password`` field is dropped, because secrets never enter
                this file.
        """
        kept = {key: value for key, value in record.items() if key != "password"}

        def change(data: dict) -> None:
            data["rdp"] = kept

        self._mutate(change)

    def clear_rdp_share(self) -> None:
        """Forget the share record, after the machine stopped sharing."""

        def change(data: dict) -> None:
            data.pop("rdp", None)

        self._mutate(change)

    def _read(self) -> dict:
        try:
            with open(self._path, "r", encoding="utf-8") as stream:
                data = json.load(stream)
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _mutate(self, change) -> None:
        """Re-read, apply one change, and write atomically. A change that
        leaves the data as it was writes nothing.

        Args:
            change: Called with the store's data to edit in place.
        """
        with self._lock:
            data = self._read()
            before = json.dumps(data, sort_keys=True)
            change(data)
            if json.dumps(data, sort_keys=True) == before:
                return
            directory = os.path.dirname(self._path) or "."
            os.makedirs(directory, exist_ok=True)
            temporary = f"{self._path}.tmp"
            descriptor = os.open(
                temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600
            )
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(data, stream, indent=2)
            os.replace(temporary, self._path)
