"""The one store for what this person typed once and keeps.

The file is the person's own, mode 0600, under the client's configuration
directory. It holds this installation's id, the language this person
reads, the palette the window draws in, the terminal's font size, the AI
tool choices, the local port each forwardable entry takes, the address
each machine that provides a share takes on the Windows files adapter, and
the mount records: the hub and entry a share came from, its host, its login
name and where it goes. Nothing about a service standing on is here; that is the
running client's own and starts clean.

Secrets never enter it: a mount's password lives in that record's own
credentials file, and the gateway key arrives fresh in every poll reply.

Every read and every write takes one lock, and a write re-reads the file
and lands atomically: a temporary file in the same directory, then
``os.replace``. On Windows a replace fails while the file is open
anywhere, so no read of this process overlaps a write, and a replace
another program's brief open refuses is tried again. A key an older
build wrote reads as if it were absent and is gone from the next write.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import json
import os
import threading
import time
import uuid

from neutrino_client.constants import (
    CLIENT_DEFAULT_LANGUAGE,
    CLIENT_DEFAULT_THEME,
    CLIENT_LANGUAGES,
    CLIENT_TERMINAL_FONT_SIZE_MAX,
    CLIENT_TERMINAL_FONT_SIZE_MIN,
    CLIENT_THEMES,
)

# What one mount record keeps, whether its share was on this machine at its
# last mount among them; a record's other fields are dropped.
STORE_MOUNT_KEYS = (
    "hub_id",
    "entry_id",
    "host",
    "share",
    "username",
    "path",
    "is_own_machine",
)
# How often, and how far apart, a replace the system refuses with the
# file held open is tried.
STORE_REPLACE_TRIES = 20
STORE_REPLACE_PAUSE_S = 0.05
# The setting of a local port the client picks itself.
STORE_LOCAL_PORT_AUTO = "auto"
# The protocols a local port is held on; a record with none is TCP.
STORE_LOCAL_PORT_PROTOCOLS = ("tcp", "udp")
STORE_LOCAL_PORT_TCP = "tcp"


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


def _local_port(raw) -> "dict | None":
    """One local port record, None for one of an unusable shape.

    Args:
        raw: What the file held for one entry under ``local_ports``.

    Returns:
        ``{"setting": "auto" or a number, "port": number, "protocol"}``, the
        port 0 while auto has picked none, the protocol ``tcp`` for a record
        that names none.
    """
    if not isinstance(raw, dict):
        return None
    setting = raw.get("setting")
    port = raw.get("port")
    protocol = raw.get("protocol", STORE_LOCAL_PORT_TCP)
    if protocol not in STORE_LOCAL_PORT_PROTOCOLS:
        return None
    if not isinstance(port, int) or isinstance(port, bool) or not 0 <= port <= 65535:
        return None
    if setting == STORE_LOCAL_PORT_AUTO:
        return {"setting": setting, "port": port, "protocol": protocol}
    if isinstance(setting, int) and not isinstance(setting, bool) and setting == port:
        return {"setting": setting, "port": port, "protocol": protocol}
    return None


def _files_address(raw) -> "dict | None":
    """One files adapter address record, None for one of an unusable shape.

    Args:
        raw: What the file held for one address under ``files_addresses``.

    Returns:
        ``{"hub_id", "machine"}``.
    """
    if not isinstance(raw, dict):
        return None
    hub_id = raw.get("hub_id")
    machine = raw.get("machine")
    if not isinstance(hub_id, str) or not isinstance(machine, str):
        return None
    if not hub_id or not machine:
        return None
    return {"hub_id": hub_id, "machine": machine}


def _record(raw: dict) -> dict:
    """One mount record with only the fields the store keeps.

    Args:
        raw: The record as it was given or read.

    Returns:
        The record, its other fields dropped.
    """
    return {key: raw[key] for key in STORE_MOUNT_KEYS if key in raw}


def _language(raw) -> str:
    """The kept language, empty where the file names none the client offers.

    Args:
        raw: What the file held under ``language``.

    Returns:
        One of ``CLIENT_LANGUAGES``, or empty.
    """
    return raw if raw in CLIENT_LANGUAGES else ""


def _theme(raw) -> str:
    """The kept theme, empty where the file names none the client offers.

    Args:
        raw: What the file held under ``theme``.

    Returns:
        One of ``CLIENT_THEMES``, or empty.
    """
    return raw if raw in CLIENT_THEMES else ""


def _font_size(raw) -> int:
    """The kept terminal font size, 0 where the file names none in range.

    Args:
        raw: What the file held under ``terminal_font_size``.

    Returns:
        A size within the range, or 0.
    """
    if not isinstance(raw, int) or isinstance(raw, bool):
        return 0
    if not CLIENT_TERMINAL_FONT_SIZE_MIN <= raw <= CLIENT_TERMINAL_FONT_SIZE_MAX:
        return 0
    return raw


def _kept(data: dict) -> dict:
    """The store's own keys, whatever else the file carries.

    Args:
        data: What the file held.

    Returns:
        ``{"machine_id": str, "language": str, "theme": str,
        "terminal_font_size": int, "ai": {"tool_configs": {...}},
        "local_ports": {service key: record}, "files_addresses": {address:
        record}, "mounts": {id: record}}``.
    """
    ai = data.get("ai")
    mounts = data.get("mounts")
    local_ports = data.get("local_ports")
    ai = ai if isinstance(ai, dict) else {}
    mounts = mounts if isinstance(mounts, dict) else {}
    local_ports = local_ports if isinstance(local_ports, dict) else {}
    kept_ports = {}
    for key, raw in local_ports.items():
        record = _local_port(raw)
        if record is not None:
            kept_ports[str(key)] = record
    files_addresses = data.get("files_addresses")
    files_addresses = files_addresses if isinstance(files_addresses, dict) else {}
    kept_addresses = {}
    for address, raw in files_addresses.items():
        record = _files_address(raw)
        if record is not None:
            kept_addresses[str(address)] = record
    machine_id = data.get("machine_id")
    return {
        "machine_id": machine_id if isinstance(machine_id, str) else "",
        "language": _language(data.get("language")),
        "theme": _theme(data.get("theme")),
        "terminal_font_size": _font_size(data.get("terminal_font_size")),
        "ai": {"tool_configs": _tool_configs(ai.get("tool_configs"))},
        "local_ports": kept_ports,
        "files_addresses": kept_addresses,
        "mounts": {
            str(record_id): _record(record)
            for record_id, record in mounts.items()
            if isinstance(record, dict)
        },
    }


def _replace(source: str, target: str) -> None:
    """``os.replace``, tried again while the target is briefly held open.

    Raises:
        PermissionError: When the target stays held past the last try.
        OSError: When the replace fails for any other reason.
    """
    for attempt in range(STORE_REPLACE_TRIES):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == STORE_REPLACE_TRIES - 1:
                raise
            time.sleep(STORE_REPLACE_PAUSE_S)


class ClientServiceStore:
    """Reads and writes what this person keeps between runs."""

    def __init__(self, *, path: str):
        """
        Args:
            path: Where the store lives on disk.
        """
        self._path = path
        self._lock = threading.RLock()

    def machine_id(self) -> str:
        """This installation's id, what a join names as ``machine_id``.

        Returns:
            A uuid4 hex string, generated on the first read and kept.
        """
        with self._lock:
            kept = self._read()["machine_id"]
            if kept:
                return kept
            made = uuid.uuid4().hex

            def change(data: dict) -> None:
                data["machine_id"] = made

            self._mutate(change)
            return made

    def language(self) -> str:
        """The language this person reads the window in.

        Returns:
            One of ``CLIENT_LANGUAGES``, or empty until one is set.
        """
        return self._read()["language"]

    def set_language(self, language: str) -> None:
        """Record the language this person reads the window in.

        Args:
            language: One of ``CLIENT_LANGUAGES``; anything else is kept as
                the default.
        """

        def change(data: dict) -> None:
            data["language"] = _language(language) or CLIENT_DEFAULT_LANGUAGE

        self._mutate(change)

    def theme(self) -> str:
        """The palette this person draws the window in.

        Returns:
            One of ``CLIENT_THEMES``, or empty until one is set.
        """
        return self._read()["theme"]

    def set_theme(self, theme: str) -> None:
        """Record the palette this person draws the window in.

        Args:
            theme: One of ``CLIENT_THEMES``; anything else is kept as the
                default.
        """

        def change(data: dict) -> None:
            data["theme"] = _theme(theme) or CLIENT_DEFAULT_THEME

        self._mutate(change)

    def terminal_font_size(self) -> int:
        """The terminal's font size this person chose.

        Returns:
            The size in pixels, or 0 until one is set.
        """
        return self._read()["terminal_font_size"]

    def set_terminal_font_size(self, size: int) -> None:
        """Record the terminal's font size.

        Args:
            size: The size in pixels; one out of range is held to the range.
        """
        held = min(
            max(int(size), CLIENT_TERMINAL_FONT_SIZE_MIN), CLIENT_TERMINAL_FONT_SIZE_MAX
        )

        def change(data: dict) -> None:
            data["terminal_font_size"] = held

        self._mutate(change)

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

    def local_ports(self) -> dict:
        """The local port each forwardable entry takes.

        Returns:
            Service key to ``{"setting", "port", "protocol"}``: the setting
            is ``"auto"`` or a fixed number, the port the one the entry
            takes, 0 while auto has picked none, and the protocol it is
            held on.
        """
        return self._read()["local_ports"]

    def set_local_port(
        self, key: str, setting, port: int, protocol: str = STORE_LOCAL_PORT_TCP
    ) -> None:
        """Keep one entry's local port.

        Args:
            key: The entry's service key.
            setting: ``"auto"`` or a fixed number.
            port: The port the entry takes; for a fixed setting, that
                number.
            protocol: ``tcp`` or ``udp``, the protocol the number is held on.

        Raises:
            ValueError: When the setting, the port and the protocol do not
                make a record.
        """
        record = _local_port({"setting": setting, "port": port, "protocol": protocol})
        if record is None:
            raise ValueError(f"no local port record of {setting!r} and {port!r}")

        def change(data: dict) -> None:
            data["local_ports"][key] = record

        self._mutate(change)

    def files_addresses(self) -> dict:
        """The address each machine that provides a share takes on the files adapter.

        Returns:
            Address to ``{"hub_id", "machine"}``.
        """
        return self._read()["files_addresses"]

    def set_files_address(self, address: str, hub_id: str, machine: str) -> None:
        """Keep one machine's address, replacing whatever held it.

        Args:
            address: The address on the adapter's network.
            hub_id: The hub the machine is reached through.
            machine: The machine: an entry's device id, or a declared
                record's host.

        Raises:
            ValueError: When the hub or the machine is empty.
        """
        record = _files_address({"hub_id": hub_id, "machine": machine})
        if record is None:
            raise ValueError("a files address names a hub and a machine")

        def change(data: dict) -> None:
            data["files_addresses"][address] = record

        self._mutate(change)

    def remove_files_addresses(self, addresses: list) -> None:
        """Drop the records of some addresses.

        Args:
            addresses: The addresses.
        """

        def change(data: dict) -> None:
            for address in addresses:
                data["files_addresses"].pop(address, None)

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

    def drop_hubless_mounts(self) -> list:
        """Drop every mount record that names no hub.

        Returns:
            The ids of the records dropped, in the file's order.
        """
        with self._lock:
            dropped = [
                record_id
                for record_id, record in self._read()["mounts"].items()
                if not record.get("hub_id")
            ]

            def change(data: dict) -> None:
                for record_id in dropped:
                    data["mounts"].pop(record_id, None)

            self._mutate(change)
            return dropped

    def _read(self) -> dict:
        with self._lock:
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
            _replace(temporary, self._path)
