"""The one store for the service choices this machine keeps.

Service choices are machine state: they live here, survive a hub restore
untouched, and appear in no hub backup. The file is root-owned mode 0600 and
holds the AI switching targets with each account's last-granted endpoint,
and the mount records. Secrets never enter it: a mount's password lives in
that record's own credentials file, and an account's gateway key arrives
fresh in every heartbeat reply.

Every write re-reads the file under one lock and lands atomically — a
temporary file in the same directory, then ``os.replace``.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import json
import os
import threading

from neutrino_agent.constants import AGENT_SERVICE_STORE_PATH


class MachineServiceStore:
    """Reads and writes the machine's service choices."""

    def __init__(self, *, path: str = ""):
        """
        Args:
            path: Where the store lives on disk; empty uses the agent's own.
        """
        self._path = path or AGENT_SERVICE_STORE_PATH
        self._lock = threading.RLock()

    def ai_targets(self) -> dict:
        """Which accounts are switched at the hub's gateway.

        Returns:
            Account name to bool; empty until an account is switched.
        """
        targets = self._read().get("ai", {}).get("targets", {})
        return {
            str(account): bool(is_switched) for account, is_switched in targets.items()
        }

    def set_ai_target(self, account: str, *, is_activated: bool) -> None:
        """Record one account's switching target.

        Args:
            account: The account.
            is_activated: Whether its tools should point at the hub.
        """

        def change(data: dict) -> None:
            data.setdefault("ai", {}).setdefault("targets", {})[account] = is_activated

        self._mutate(change)

    def ai_tool_configs(self) -> dict:
        """The per-tool model choices the machine keeps.

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
        """Each account's last-granted endpoint, as activation recorded it.

        Returns:
            Account name to ``{"base_url", "model"}``. The key is never here;
            deactivation needs only the endpoint the account was pointed at.
        """
        granted = self._read().get("ai", {}).get("granted", {})
        return {
            str(account): dict(config)
            for account, config in granted.items()
            if isinstance(config, dict)
        }

    def set_ai_granted(self, account: str, config: dict) -> None:
        """Record what one account's activation granted.

        Args:
            account: The account.
            config: ``{"base_url", "model"}``.
        """

        def change(data: dict) -> None:
            data.setdefault("ai", {}).setdefault("granted", {})[account] = {
                "base_url": str(config.get("base_url", "")),
                "model": str(config.get("model", "")),
            }

        self._mutate(change)

    def clear_ai_granted(self, account: str) -> None:
        """Forget one account's granted endpoint, after deactivation.

        Args:
            account: The account.
        """

        def change(data: dict) -> None:
            data.get("ai", {}).get("granted", {}).pop(account, None)

        self._mutate(change)

    def mounts(self) -> dict:
        """The mount records this machine keeps.

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

    def rdp_share(self) -> dict:
        """What this machine last decided about sharing its desktop.

        Returns:
            ``{"share_id", "is_shared", "port"}``, empty until somebody
            shares. The access password is not here: it lives in its own
            root-only file, the way a mount's does.
        """
        record = self._read().get("rdp", {})
        return dict(record) if isinstance(record, dict) else {}

    def set_rdp_share(self, record: dict) -> None:
        """Record that this machine shares its desktop.

        Args:
            record: ``{"share_id", "is_shared", "port"}``; any ``password``
                field is dropped, because secrets never enter this file.
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
