"""The one store for what this person typed once and keeps.

The file is the person's own, mode 0600, under the client's configuration
directory. It holds the AI tool choices and the mount records: a share's
host, its login name and where it goes. Nothing about a service standing
on is here; that is the running client's own and starts clean.

Secrets never enter it: a mount's password lives in that record's own
credentials file, and the gateway key arrives fresh in every poll reply.

Every write re-reads the file under one lock and lands atomically: a
temporary file in the same directory, then ``os.replace``. A key an older
build wrote reads as if it were absent and is gone from the next write.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import json
import os
import threading

# What one mount record keeps; a record's other fields are dropped.
STORE_MOUNT_KEYS = ("entry_id", "host", "share", "username", "path")


def _tool_configs(raw) -> dict:
    """The per-tool choices, tools of an unusable shape dropped.

    Args:
        raw: What the file held under ``ai.tool_configs``.

    Returns:
        ``{tool: {knob: value}}``.
    """
    if not isinstance(raw, dict):
        return {}
    return {
        str(tool): dict(values)
        for tool, values in raw.items()
        if isinstance(values, dict)
    }


def _record(raw: dict) -> dict:
    """One mount record with only the fields the store keeps.

    Args:
        raw: The record as it was given or read.

    Returns:
        The record, its other fields dropped.
    """
    return {key: raw[key] for key in STORE_MOUNT_KEYS if key in raw}


def _kept(data: dict) -> dict:
    """The store's own keys, whatever else the file carries.

    Args:
        data: What the file held.

    Returns:
        ``{"ai": {"tool_configs": {...}}, "mounts": {id: record}}``.
    """
    ai = data.get("ai")
    mounts = data.get("mounts")
    ai = ai if isinstance(ai, dict) else {}
    mounts = mounts if isinstance(mounts, dict) else {}
    return {
        "ai": {"tool_configs": _tool_configs(ai.get("tool_configs"))},
        "mounts": {
            str(record_id): _record(record)
            for record_id, record in mounts.items()
            if isinstance(record, dict)
        },
    }


class ClientServiceStore:
    """Reads and writes what this person keeps between runs."""

    def __init__(self, *, path: str):
        """
        Args:
            path: Where the store lives on disk.
        """
        self._path = path
        self._lock = threading.RLock()

    def ai_tool_configs(self) -> dict:
        """The per-tool model choices this person keeps.

        Returns:
            ``{"claude": {...}, "codex": {...}, "gemini": {...}}``; empty
            tools until somebody configures them.
        """
        return self._read()["ai"]["tool_configs"]

    def set_ai_tool_configs(self, configs: dict) -> None:
        """Record the per-tool model choices.

        Args:
            configs: Tool name to its choices.
        """

        def change(data: dict) -> None:
            data["ai"]["tool_configs"] = _tool_configs(configs)

        self._mutate(change)

    def mounts(self) -> dict:
        """The mount records this person keeps.

        Returns:
            Record id to the record.
        """
        return self._read()["mounts"]

    def set_mount(self, record_id: str, record: dict) -> None:
        """Keep one mount record; only the fields the store keeps land in it.

        Args:
            record_id: The record id.
            record: The record; a ``password`` field is one of those dropped.
        """

        def change(data: dict) -> None:
            data["mounts"][record_id] = _record(record)

        self._mutate(change)

    def remove_mount(self, record_id: str) -> None:
        """Drop one mount record.

        Args:
            record_id: The record id.
        """

        def change(data: dict) -> None:
            data["mounts"].pop(record_id, None)

        self._mutate(change)

    def _read(self) -> dict:
        try:
            with open(self._path, "r", encoding="utf-8") as stream:
                data = json.load(stream)
        except (OSError, ValueError):
            data = {}
        return _kept(data if isinstance(data, dict) else {})

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
