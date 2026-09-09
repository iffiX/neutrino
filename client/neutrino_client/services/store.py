"""The one store for the service choices this person keeps.

The file is the person's own, mode 0600, under the client's configuration
directory. It holds the AI choice with the last-granted endpoint, and the
mount records. Secrets never enter it: a mount's password lives in that
record's own credentials file, and the gateway key arrives fresh in every
poll reply.

Every write re-reads the file under one lock and lands atomically: a
temporary file in the same directory, then ``os.replace``.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import json
import os
import threading


class ClientServiceStore:
    """Reads and writes this person's service choices."""

    def __init__(self, *, path: str):
        """
        Args:
            path: Where the store lives on disk.
        """
        self._path = path
        self._lock = threading.RLock()

    def is_ai_enabled(self) -> bool:
        """Whether this person's tools should point at the hub."""
        return bool(self._read().get("ai", {}).get("is_enabled"))

    def set_ai_enabled(self, is_enabled: bool) -> None:
        """Record whether the tools should point at the hub.

        Args:
            is_enabled: The choice.
        """

        def change(data: dict) -> None:
            data.setdefault("ai", {})["is_enabled"] = bool(is_enabled)

        self._mutate(change)

    def ai_tool_configs(self) -> dict:
        """The per-tool model choices this person keeps.

        Returns:
            ``{"claude": {...}, "codex": {...}, "gemini": {...}}``; empty
            tools until somebody configures them.
        """
        configs = self._read().get("ai", {}).get("tool_configs", {})
        return {
            str(tool): dict(values)
            for tool, values in configs.items()
            if isinstance(values, dict)
        }

    def set_ai_tool_configs(self, configs: dict) -> None:
        """Record the per-tool model choices.

        Args:
            configs: Tool name to its choices.
        """

        def change(data: dict) -> None:
            data.setdefault("ai", {})["tool_configs"] = {
                str(tool): dict(values)
                for tool, values in configs.items()
                if isinstance(values, dict)
            }

        self._mutate(change)

    def ai_granted(self) -> dict:
        """The endpoint the last activation pointed the tools at.

        Returns:
            ``{"base_url", "model"}``, empty until an activation. The key is
            never here.
        """
        granted = self._read().get("ai", {}).get("granted", {})
        return dict(granted) if isinstance(granted, dict) else {}

    def set_ai_granted(self, config: dict) -> None:
        """Record what an activation granted.

        Args:
            config: ``{"base_url", "model"}``.
        """

        def change(data: dict) -> None:
            data.setdefault("ai", {})["granted"] = {
                "base_url": str(config.get("base_url", "")),
                "model": str(config.get("model", "")),
            }

        self._mutate(change)

    def clear_ai_granted(self) -> None:
        """Forget the granted endpoint, after deactivation."""

        def change(data: dict) -> None:
            data.get("ai", {}).pop("granted", None)

        self._mutate(change)

    def mounts(self) -> dict:
        """The mount records this person keeps.

        Returns:
            Record id to the record.
        """
        mounts = self._read().get("mounts", {})
        return {
            str(record_id): dict(record)
            for record_id, record in mounts.items()
            if isinstance(record, dict)
        }

    def set_mount(self, record_id: str, record: dict) -> None:
        """Keep one mount record. Passwords are never stored here.

        Args:
            record_id: The record id.
            record: The record; any ``password`` field is dropped.
        """
        kept = {key: value for key, value in record.items() if key != "password"}

        def change(data: dict) -> None:
            data.setdefault("mounts", {})[record_id] = kept

        self._mutate(change)

    def remove_mount(self, record_id: str) -> None:
        """Drop one mount record.

        Args:
            record_id: The record id.
        """

        def change(data: dict) -> None:
            data.get("mounts", {}).pop(record_id, None)

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
