"""The clients enrolled with this hub: one record per person's program.

A client is a desktop program a person runs, enrolled once by name. The
record is created when its link is minted, so a client that has never
joined is a row already; what it authenticates with is the SHA-256 of a
token the enroll reply handed it once. Presence and when it was last seen
are the session registry's, in memory; what is written here is what the
program said it is when it last connected.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass, field

from neutrino_hub.modules.clients.constants import (
    CLIENT_TOKEN_BYTES,
    CLIENTS_CONFIG_PATH,
)
from neutrino_hub.utils.json_file import CONFIG_WRITE_LOCK, read_config, write_config


def _token_digest(token: str) -> str:
    """The stored form of a client token: its SHA-256 hex."""
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class Client:
    """One enrolled client.

    Attributes:
        id: The key it is stored under, a uuid4 hex.
        name: What the person called it when the link was minted.
        token_sha256: The digest of its token; None until it joins, or once
            it has left.
        hostname: What the program's machine called itself.
        platform: ``{os, arch, family}`` as the program reported it.
        version: The client release it last reported.
        is_disabled: Whether the admin has switched it off.
        ai_key_id: The gateway client key minted for it, or None.
    """

    id: str
    name: str = ""
    token_sha256: "str | None" = None
    hostname: str = ""
    platform: dict = field(default_factory=dict)
    version: str = ""
    is_disabled: bool = False
    ai_key_id: "str | None" = None

    @property
    def is_enrolled(self) -> bool:
        """Whether the client holds a token that still stands."""
        return bool(self.token_sha256)

    @classmethod
    def from_dict(cls, client_id: str, data: dict) -> "Client":
        """Build from the stored entry.

        Args:
            client_id: The key the entry is stored under.
            data: The stored entry.

        Returns:
            The parsed record.
        """
        platform = data.get("platform")
        return cls(
            id=client_id,
            name=str(data.get("name", "") or ""),
            token_sha256=data.get("token_sha256") or None,
            hostname=str(data.get("hostname", "") or ""),
            platform=dict(platform) if isinstance(platform, dict) else {},
            version=str(data.get("version", "") or ""),
            is_disabled=bool(data.get("is_disabled", False)),
            ai_key_id=data.get("ai_key_id") or None,
        )

    def to_dict(self) -> dict:
        """Serialize to the stored shape, without the id."""
        return {
            "name": self.name,
            "token_sha256": self.token_sha256,
            "hostname": self.hostname,
            "platform": dict(self.platform),
            "version": self.version,
            "is_disabled": self.is_disabled,
            "ai_key_id": self.ai_key_id,
        }


class ClientRegistry:
    """Reads and writes ``config/clients/clients.json``.

    Every write re-reads the file under the config lock first, so a caller
    holding an older snapshot cannot put another client back as it was.
    """

    def __init__(self):
        self._stored = self._read_stored()

    def all(self) -> list:
        """Every client, in stored order."""
        return [
            Client.from_dict(client_id, entry)
            for client_id, entry in self._stored.items()
        ]

    def get(self, client_id: str) -> "Client | None":
        """One client by id, or None when there is no such record."""
        entry = self._stored.get(client_id)
        if entry is None:
            return None
        return Client.from_dict(client_id, entry)

    def create(self, name: str) -> str:
        """Add a client that has not joined yet.

        Args:
            name: What the person calls it.

        Returns:
            The new client's id.
        """
        client_id = uuid.uuid4().hex
        with CONFIG_WRITE_LOCK:
            self._stored = self._read_stored()
            self._stored[client_id] = Client(id=client_id, name=name.strip()).to_dict()
            self._write_stored()
        return client_id

    def issue_token(self, client_id: str) -> str:
        """Give a client a fresh token, storing only its digest.

        Args:
            client_id: The client.

        Returns:
            The raw token, for the enroll reply alone.

        Raises:
            KeyError: When there is no such client.
        """
        token = secrets.token_urlsafe(CLIENT_TOKEN_BYTES)
        self._update(client_id, {"token_sha256": _token_digest(token)})
        return token

    def find_by_token(self, token: str) -> "Client | None":
        """The client a presented token belongs to, or None."""
        presented = _token_digest(token)
        for client_id, entry in self._stored.items():
            stored = entry.get("token_sha256")
            if stored and secrets.compare_digest(str(stored), presented):
                return Client.from_dict(client_id, entry)
        return None

    def record_seen(
        self, client_id: str, *, hostname: str, platform: dict, version: str
    ) -> None:
        """Keep what the program said it is, written only when it changed.

        Args:
            client_id: The client.
            hostname: The machine's name; empty keeps what is stored.
            platform: ``{os, arch, family}``; empty keeps what is stored.
            version: The client release; empty keeps what is stored.
        """
        changes = {}
        if hostname:
            changes["hostname"] = str(hostname)
        if platform:
            changes["platform"] = dict(platform)
        if version:
            changes["version"] = str(version)
        with CONFIG_WRITE_LOCK:
            self._stored = self._read_stored()
            entry = self._stored.get(client_id)
            if entry is None:
                return
            if all(entry.get(name) == value for name, value in changes.items()):
                return
            entry.update(changes)
            self._write_stored()

    def set_disabled(self, client_id: str, is_disabled: bool) -> None:
        """Switch a client off or on.

        Args:
            client_id: The client.
            is_disabled: True to refuse it everything while its socket stays.

        Raises:
            KeyError: When there is no such client.
        """
        self._update(client_id, {"is_disabled": bool(is_disabled)})

    def set_ai_key_id(self, client_id: str, key_id: "str | None") -> None:
        """Remember which gateway key a client holds.

        Args:
            client_id: The client.
            key_id: The key's id, or None once it is revoked.

        Raises:
            KeyError: When there is no such client.
        """
        self._update(client_id, {"ai_key_id": key_id})

    def drop_token(self, client_id: str) -> None:
        """Take a client's token back; the row stays.

        Args:
            client_id: The client.

        Raises:
            KeyError: When there is no such client.
        """
        self._update(client_id, {"token_sha256": None})

    def forget(self, client_id: str) -> None:
        """Remove a client's record. An unknown id is ignored."""
        with CONFIG_WRITE_LOCK:
            self._stored = self._read_stored()
            self._stored.pop(client_id, None)
            self._write_stored()

    def _update(self, client_id: str, changes: dict) -> None:
        with CONFIG_WRITE_LOCK:
            self._stored = self._read_stored()
            entry = self._stored.get(client_id)
            if entry is None:
                raise KeyError(client_id)
            entry.update(changes)
            self._write_stored()

    def _read_stored(self) -> dict:
        try:
            data = read_config(CLIENTS_CONFIG_PATH)
        except FileNotFoundError:
            return {}
        clients = data.get("clients", {})
        return dict(clients) if isinstance(clients, dict) else {}

    def _write_stored(self) -> None:
        write_config(CLIENTS_CONFIG_PATH, {"clients": self._stored})
