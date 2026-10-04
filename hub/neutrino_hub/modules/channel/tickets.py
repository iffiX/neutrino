"""The open enrolment tickets, in memory and in one file under the state root.

A ticket is kept as its SHA-256 beside its kind, the row it binds and its
expiry; the ticket itself is written nowhere. Every change writes the file
at once, so a hub that restarts keeps each open ticket until its expiry.
"""

import hashlib
import json
import logging
import secrets
import threading
import time
from pathlib import Path

from neutrino_hub.modules.channel.constants import (
    CHANNEL_ROLE_AGENT,
    CHANNEL_TICKET_FILE_MODE,
    CHANNEL_TICKET_PATH,
    ENROLLMENT_TOKEN_BYTES,
    ENROLLMENT_TTL_S,
)
from neutrino_hub.utils.json_file import write_generated

_LOGGER = logging.getLogger(__name__)


class ChannelTicketRegistry:
    """The open enrolment tickets, one of each kind at a time.

    Each entry is ``{token_sha256, kind, name, device_id, client_id,
    expires_at}``, ``expires_at`` in Unix seconds.
    """

    def __init__(self, *, path: "Path | None" = None):
        """Read back every ticket that has not expired.

        Args:
            path: The file the tickets live in; None for the state root's.
        """
        self._path = path or CHANNEL_TICKET_PATH
        self._lock = threading.Lock()
        with self._lock:
            loaded = self._read()
            self._entries: dict[str, dict] = {
                entry["token_sha256"]: entry
                for entry in loaded
                if entry["expires_at"] >= time.time()
            }
            if len(self._entries) != len(loaded):
                self._write_quietly()

    def make(
        self,
        *,
        kind: str,
        name: str = "",
        device_id: "str | None" = None,
        client_id: "str | None" = None,
    ) -> tuple[str, float]:
        """Make a ticket, replacing the open ticket of its kind.

        Args:
            kind: ``agent`` or ``client``.
            name: What the joining row should be called, blank for none.
            device_id: The device row the ticket binds, None for any machine.
            client_id: The client row the ticket binds.

        Returns:
            The ticket and when it expires, in Unix seconds.

        Raises:
            OSError: When the file cannot be written; no ticket is open then.
        """
        ticket = secrets.token_urlsafe(ENROLLMENT_TOKEN_BYTES)
        expires_at = time.time() + ENROLLMENT_TTL_S
        self.put(
            ticket,
            kind=kind,
            name=name,
            device_id=device_id,
            client_id=client_id,
            expires_at=expires_at,
        )
        return ticket, expires_at

    def put(
        self,
        ticket: str,
        *,
        kind: str,
        expires_at: float,
        name: str = "",
        device_id: "str | None" = None,
        client_id: "str | None" = None,
    ) -> None:
        """Keep a given ticket, replacing the open ticket of its kind.

        Args:
            ticket: The ticket.
            kind: ``agent`` or ``client``.
            expires_at: When it expires, in Unix seconds.
            name: What the joining row should be called, blank for none.
            device_id: The device row the ticket binds.
            client_id: The client row the ticket binds.

        Raises:
            OSError: When the file cannot be written; the ticket is not kept.
        """
        entry = {
            "token_sha256": _digest(ticket),
            "kind": kind,
            "name": name,
            "device_id": device_id or None,
            "client_id": client_id or None,
            "expires_at": float(expires_at),
        }
        with self._lock:
            before = dict(self._entries)
            self._drop_expired()
            for digest in [
                digest
                for digest, open_entry in self._entries.items()
                if open_entry["kind"] == kind
            ]:
                del self._entries[digest]
            self._entries[entry["token_sha256"]] = entry
            try:
                self._write()
            except OSError:
                self._entries = before
                raise

    def spend(self, ticket: str) -> "dict | None":
        """Take a ticket out of the memory and the file in one step.

        Args:
            ticket: The ticket a join carries.

        Returns:
            Its entry, expired or not, or None when no entry has its hash.
        """
        with self._lock:
            entry = self._entries.pop(_digest(ticket), None)
            if self._drop_expired() or entry is not None:
                self._write_quietly()
            return entry

    def get(self, ticket: str) -> "dict | None":
        """The live entry of a ticket, left open.

        Args:
            ticket: The ticket.

        Returns:
            A copy of its entry, or None when it is unknown or expired.
        """
        with self._lock:
            entry = self._entries.get(_digest(ticket))
        if entry is None or entry["expires_at"] < time.time():
            return None
        return dict(entry)

    def entries(self) -> list[dict]:
        """Every open entry that has not expired.

        Returns:
            Copies of the entries.
        """
        now = time.time()
        with self._lock:
            return [dict(e) for e in self._entries.values() if e["expires_at"] >= now]

    def _drop_expired(self) -> int:
        now = time.time()
        expired = [d for d, entry in self._entries.items() if entry["expires_at"] < now]
        for digest in expired:
            del self._entries[digest]
        return len(expired)

    def _read(self) -> list[dict]:
        try:
            loaded = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as error:
            _LOGGER.warning("enrolment tickets unreadable, none kept: %s", error)
            return []
        if not isinstance(loaded, list):
            return []
        return [entry for entry in map(_entry_of, loaded) if entry is not None]

    def _write(self) -> None:
        text = json.dumps(list(self._entries.values()), indent=2) + "\n"
        write_generated(self._path, text, mode=CHANNEL_TICKET_FILE_MODE)

    def _write_quietly(self) -> None:
        try:
            self._write()
        except OSError as error:
            _LOGGER.warning("enrolment tickets not written: %s", error)


def _digest(ticket: str) -> str:
    return hashlib.sha256(ticket.encode("utf-8")).hexdigest()


def _entry_of(item) -> "dict | None":
    if not isinstance(item, dict):
        return None
    digest = item.get("token_sha256")
    expires_at = item.get("expires_at")
    if not isinstance(digest, str) or not isinstance(expires_at, (int, float)):
        return None
    return {
        "token_sha256": digest,
        "kind": str(item.get("kind") or CHANNEL_ROLE_AGENT),
        "name": str(item.get("name") or ""),
        "device_id": item.get("device_id") or None,
        "client_id": item.get("client_id") or None,
        "expires_at": float(expires_at),
    }
