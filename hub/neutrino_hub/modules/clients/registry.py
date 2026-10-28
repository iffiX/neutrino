"""The clients enrolled with this hub: one record per person's program.

A client is a program a person runs, enrolled once by name. The record is
created with its link and waits to join until the link expires; what it
authenticates with is the SHA-256 of a token the enroll reply handed it
once. Presence and when it was last seen are the session registry's, in
memory; what is written here is what the program said it is when it last
connected.
"""

import functools
import hashlib
import secrets
import uuid
from dataclasses import dataclass, field

from neutrino_hub.modules.clients.constants import (
    CLIENT_DEFAULT_PERMISSION_KINDS,
    CLIENT_PERMISSION_FILTERED_KINDS,
    CLIENT_PERMISSION_KINDS,
    CLIENT_PERMISSION_SSH,
    CLIENT_PERMISSION_TERMINAL,
    CLIENT_SSH_GRANTED_KEY,
    CLIENT_TOKEN_BYTES,
    CLIENTS_CONFIG_PATH,
)
from neutrino_hub.modules.clients.permissions import (
    ClientPermission,
    is_row_of_device,
    permission_devices,
    permission_entries,
    permission_kinds,
)
from neutrino_hub.utils.json_file import CONFIG_WRITE_LOCK, read_config, write_config


def _token_digest(token: str) -> str:
    """The stored form of a client token: its SHA-256 hex."""
    return hashlib.sha256(token.encode()).hexdigest()


def _stored_kinds(entry) -> "list | None":
    """The kinds a stored permission names, unknown ones dropped; None for none."""
    if not isinstance(entry, dict) or not isinstance(entry.get("kinds"), list):
        return None
    return permission_kinds(
        kind for kind in entry["kinds"] if kind in CLIENT_PERMISSION_KINDS
    )


def _stored_devices(entry) -> dict:
    """The device filter a stored permission names, anything unreadable dropped."""
    if not isinstance(entry, dict) or not isinstance(entry.get("devices"), dict):
        return {}
    return permission_devices(
        {
            kind: ids
            for kind, ids in entry["devices"].items()
            if kind in CLIENT_PERMISSION_FILTERED_KINDS and isinstance(ids, list)
        }
    )


def _stored_entries(entry) -> dict:
    """The rows a stored permission names, anything unreadable dropped."""
    if not isinstance(entry, dict) or not isinstance(entry.get("entries"), dict):
        return {}
    return permission_entries(
        {
            row_id: value
            for row_id, value in entry["entries"].items()
            if isinstance(value, bool)
        }
    )


def _permission_document(kinds: list, devices: dict, entries: dict) -> dict:
    """A permission as stored: its kinds, its filter and its rows when it has
    them."""
    document = {"kinds": list(kinds)}
    if devices:
        document["devices"] = {kind: list(ids) for kind, ids in devices.items()}
    if entries:
        document["entries"] = dict(entries)
    return document


def _without_device_rows(
    device_id: str, kinds: list, devices: dict, entries: dict
) -> tuple:
    """A permission with one device taken out of its lists and its rows.

    Returns:
        ``(kinds, devices, entries)``.
    """
    kinds, devices = _without_device(kinds, devices, device_id)
    rows = {
        row_id: value
        for row_id, value in entries.items()
        if not is_row_of_device(row_id, device_id)
    }
    return kinds, devices, rows


def _without_rows(dropped: set, kinds: list, devices: dict, entries: dict) -> tuple:
    """A permission with some rows taken out of ``entries``.

    Returns:
        ``(kinds, devices, entries)``.
    """
    rows = {row_id: value for row_id, value in entries.items() if row_id not in dropped}
    return kinds, devices, rows


def _stored_time(value) -> "float | None":
    """A stored Unix time, None for anything that is not a number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _with_ssh(kinds: list, devices: dict) -> "tuple | None":
    """A permission with ``ssh`` added beside its ``terminal``.

    Args:
        kinds: The permission's kinds.
        devices: Its device filter.

    Returns:
        ``(kinds, devices)`` with ``ssh`` added, ``terminal``'s device list
        copied to it when there is one; None when the permission names no
        ``terminal`` or already names ``ssh``.
    """
    if CLIENT_PERMISSION_TERMINAL not in kinds or CLIENT_PERMISSION_SSH in kinds:
        return None
    granted = permission_kinds(list(kinds) + [CLIENT_PERMISSION_SSH])
    filters = dict(devices)
    if devices.get(CLIENT_PERMISSION_TERMINAL):
        filters[CLIENT_PERMISSION_SSH] = list(devices[CLIENT_PERMISSION_TERMINAL])
    return granted, permission_devices(filters)


def _without_device(kinds: list, devices: dict, device_id: str) -> tuple:
    """A permission with one device taken out of every list.

    A kind whose list named only that device is turned off, since an empty
    list allows every device.

    Returns:
        ``(kinds, devices)``.
    """
    emptied = {kind for kind, ids in devices.items() if ids and set(ids) <= {device_id}}
    kept = permission_devices(
        {
            kind: [entry for entry in ids if entry != device_id]
            for kind, ids in devices.items()
        }
    )
    return [kind for kind in kinds if kind not in emptied], kept


@dataclass
class Client:
    """One enrolled client.

    Attributes:
        id: The key it is stored under, a uuid4 hex.
        name: What the person called it when the link was minted.
        token_sha256: The digest of its token; None until it joins, or once
            it has left.
        public_key: Its static public key, 64 hex characters, which its
            knock names the binding by; None until it joined or moved its
            binding to the transport.
        hostname: What the program's machine called itself.
        machine_id: The id the machine reports for itself, empty until it
            has joined.
        os_machine_id: The operating system's id for the machine the
            program runs on, from its reports; empty until one names it.
        platform: ``{os, arch, family}`` as the program reported it.
        version: The client release it last reported.
        is_disabled: Whether the admin has switched it off.
        ai_key_id: The gateway client key minted for it, or None.
        permission: The kinds it is allowed, or None to follow the default.
        permission_devices: With a permission of its own, the device ids
            each kind is narrowed to; a kind not named allows every device.
        permission_entries: With a permission of its own, row id to
            ``True`` or ``False``; a row not named follows its kind.
        link_expires_at: When its link stops working, in Unix seconds,
            while it waits to join; None once it joined.
    """

    id: str
    name: str = ""
    token_sha256: "str | None" = None
    public_key: "str | None" = None
    hostname: str = ""
    machine_id: str = ""
    os_machine_id: str = ""
    platform: dict = field(default_factory=dict)
    version: str = ""
    is_disabled: bool = False
    ai_key_id: "str | None" = None
    permission: "list | None" = None
    permission_devices: dict = field(default_factory=dict)
    permission_entries: dict = field(default_factory=dict)
    link_expires_at: "float | None" = None

    @property
    def is_enrolled(self) -> bool:
        """Whether the client holds a token that still stands."""
        return bool(self.token_sha256)

    @property
    def is_waiting(self) -> bool:
        """Whether the client has not joined yet."""
        return not self.token_sha256 and not self.public_key

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
            public_key=str(data.get("public_key") or "") or None,
            hostname=str(data.get("hostname", "") or ""),
            machine_id=str(data.get("machine_id", "") or ""),
            os_machine_id=str(data.get("os_machine_id", "") or ""),
            platform=dict(platform) if isinstance(platform, dict) else {},
            version=str(data.get("version", "") or ""),
            is_disabled=bool(data.get("is_disabled", False)),
            ai_key_id=data.get("ai_key_id") or None,
            permission=_stored_kinds(data.get("permission")),
            permission_devices=_stored_devices(data.get("permission")),
            permission_entries=_stored_entries(data.get("permission")),
            link_expires_at=_stored_time(data.get("link_expires_at")),
        )

    def to_dict(self) -> dict:
        """Serialize to the stored shape, without the id."""
        return {
            "name": self.name,
            "token_sha256": self.token_sha256,
            "public_key": self.public_key,
            "hostname": self.hostname,
            "machine_id": self.machine_id,
            "os_machine_id": self.os_machine_id,
            "platform": dict(self.platform),
            "version": self.version,
            "is_disabled": self.is_disabled,
            "ai_key_id": self.ai_key_id,
            "permission": (
                None
                if self.permission is None
                else _permission_document(
                    self.permission, self.permission_devices, self.permission_entries
                )
            ),
            "link_expires_at": self.link_expires_at,
        }


class ClientRegistry:
    """Reads and writes ``config/clients/clients.json``.

    Every write re-reads the file under the config lock first, so a caller
    holding an older snapshot cannot put another client back as it was.
    """

    def __init__(self):
        self._default = None
        self._default_devices = {}
        self._default_entries = {}
        self._is_ssh_granted = False
        self._is_file_present = False
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

    def create(
        self,
        name: str,
        *,
        permission: "ClientPermission | None" = None,
        link_expires_at: "float | None" = None,
    ) -> str:
        """Add a client that has not joined yet.

        Args:
            name: What the person calls it.
            permission: Its own permission; None follows the default.
            link_expires_at: When its link stops working, in Unix seconds.

        Returns:
            The new client's id.

        Raises:
            ValueError: If the permission names a kind that is not one, a
                filter on a kind that takes none, or a row that is neither
                on nor off.
        """
        client_id = uuid.uuid4().hex
        client = Client(
            id=client_id, name=name.strip(), link_expires_at=link_expires_at
        )
        if permission is not None:
            client.permission = permission_kinds(permission.kinds)
            client.permission_devices = permission_devices(permission.devices)
            client.permission_entries = permission_entries(permission.entries)
        with CONFIG_WRITE_LOCK:
            self._stored = self._read_stored()
            self._stored[client_id] = client.to_dict()
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
        self._update(
            client_id, {"token_sha256": _token_digest(token), "link_expires_at": None}
        )
        return token

    def find_by_token(self, token: str) -> "Client | None":
        """The client a presented token belongs to, or None."""
        presented = _token_digest(token)
        for client_id, entry in self._stored.items():
            stored = entry.get("token_sha256")
            if stored and secrets.compare_digest(str(stored), presented):
                return Client.from_dict(client_id, entry)
        return None

    def find_by_public_key(self, public_key: str) -> "Client | None":
        """The client whose static public key a knock named, or None.

        Args:
            public_key: The key, 64 hex characters.

        Returns:
            The client holding it, or None when no row does.
        """
        wanted = str(public_key or "").lower()
        if not wanted:
            return None
        for client_id, entry in self._stored.items():
            stored = str(entry.get("public_key") or "").lower()
            if stored and secrets.compare_digest(stored, wanted):
                return Client.from_dict(client_id, entry)
        return None

    def set_public_key(self, client_id: str, public_key: "str | None") -> None:
        """Record the static public key a client knocks with.

        Args:
            client_id: The client.
            public_key: The key, or None to drop it.

        Raises:
            KeyError: When there is no such client.
        """
        self._update(
            client_id, {"public_key": str(public_key).lower() if public_key else None}
        )

    def find_by_machine_id(self, machine_id: str) -> "Client | None":
        """The client stored for a machine, or None.

        Args:
            machine_id: The id a machine reports for itself; an empty one
                matches no row.

        Returns:
            The client that reported this machine id, or None.
        """
        if not machine_id:
            return None
        for client_id, entry in self._stored.items():
            if entry.get("machine_id") == machine_id:
                return Client.from_dict(client_id, entry)
        return None

    def record_seen(
        self,
        client_id: str,
        *,
        hostname: str,
        platform: dict,
        version: str,
        machine_id: str = "",
        os_machine_id: str = "",
    ) -> None:
        """Keep what the program said it is, written only when it changed.

        Args:
            client_id: The client.
            hostname: The machine's name; empty keeps what is stored.
            platform: ``{os, arch, family}``; empty keeps what is stored.
            version: The client release; empty keeps what is stored.
            machine_id: The machine's own id; empty keeps what is stored.
            os_machine_id: The operating system's id for the machine;
                empty keeps what is stored.
        """
        changes = {}
        if hostname:
            changes["hostname"] = str(hostname)
        if machine_id:
            changes["machine_id"] = str(machine_id)
        if os_machine_id:
            changes["os_machine_id"] = str(os_machine_id)
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

    def rename(self, client_id: str, name: str) -> None:
        """Give a client a new name.

        Args:
            client_id: The client.
            name: What the person calls it now.

        Raises:
            KeyError: When there is no such client.
        """
        self._update(client_id, {"name": name.strip()})

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
        """Take a client's token and static key back; the row stays.

        Args:
            client_id: The client.

        Raises:
            KeyError: When there is no such client.
        """
        self._update(client_id, {"token_sha256": None, "public_key": None})

    def default_permission(self) -> list:
        """The kinds a client with no set of its own is allowed.

        Returns:
            The kinds; every kind but ``panel`` when the file names no
            default.
        """
        if self._default is None:
            return list(CLIENT_DEFAULT_PERMISSION_KINDS)
        return list(self._default)

    def default_permission_devices(self) -> dict:
        """The device filter a client with no permission of its own is held to.

        Returns:
            Device ids by kind; empty when the default narrows nothing.
        """
        return {kind: list(ids) for kind, ids in self._default_devices.items()}

    def default_permission_entries(self) -> dict:
        """The rows a client with no permission of its own is held to.

        Returns:
            Row id to ``True`` or ``False``; empty when the default sets no
            row.
        """
        return dict(self._default_entries)

    def set_default_permission(self, kinds, devices=None, entries=None) -> None:
        """Store what a client with no permission of its own is allowed.

        Args:
            kinds: The kinds.
            devices: Device ids by kind; None or a missing kind allows every
                device.
            entries: Row id to ``True`` or ``False``; None sets no row.

        Raises:
            ValueError: If one of the kinds is not a permission kind, one
                takes no device filter, or a row is neither on nor off.
        """
        chosen = permission_kinds(kinds)
        filters = permission_devices(devices)
        rows = permission_entries(entries)
        with CONFIG_WRITE_LOCK:
            self._stored = self._read_stored()
            self._default = chosen
            self._default_devices = filters
            self._default_entries = rows
            self._write_stored()

    def set_permission(self, client_id: str, kinds, devices=None, entries=None) -> None:
        """Give one client a permission of its own, or put it back on the
        default.

        Args:
            client_id: The client.
            kinds: The kinds, or None to follow the default.
            devices: Device ids by kind; None or a missing kind allows every
                device. Ignored when ``kinds`` is None.
            entries: Row id to ``True`` or ``False``; None sets no row.
                Ignored when ``kinds`` is None.

        Raises:
            KeyError: When there is no such client.
            ValueError: If one of the kinds is not a permission kind, one
                takes no device filter, or a row is neither on nor off.
        """
        chosen = None
        if kinds is not None:
            chosen = _permission_document(
                permission_kinds(kinds),
                permission_devices(devices),
                permission_entries(entries),
            )
        self._update(client_id, {"permission": chosen})

    def grant_ssh_once(self) -> bool:
        """Add ``ssh`` to every stored permission that names ``terminal``, once.

        The first 0.6.0 start of a hub whose file predates the ``ssh`` kind
        gives it to the default permission and to each client's own, with
        ``terminal``'s device list when it has one, and marks the file so a
        person who takes ``ssh`` away later keeps it away.

        Returns:
            Whether the file was written.
        """
        with CONFIG_WRITE_LOCK:
            self._stored = self._read_stored()
            if self._is_ssh_granted or not self._is_file_present:
                return False
            if self._default is not None:
                granted = _with_ssh(self._default, self._default_devices)
                if granted is not None:
                    self._default, self._default_devices = granted
            for client_id, entry in self._stored.items():
                client = Client.from_dict(client_id, entry)
                if client.permission is None:
                    continue
                granted = _with_ssh(client.permission, client.permission_devices)
                if granted is not None:
                    entry["permission"] = _permission_document(
                        *granted, client.permission_entries
                    )
            self._is_ssh_granted = True
            self._write_stored()
        return True

    def forget_device(self, device_id: str) -> bool:
        """Take one device out of every permission, the default's and each
        client's.

        A kind whose list named only that device is turned off, and every
        row whose id names the device leaves ``entries``.

        Args:
            device_id: The device that is gone.

        Returns:
            Whether any permission named it.
        """
        return self._rewrite_permissions(
            functools.partial(_without_device_rows, device_id)
        )

    def forget_permission_rows(self, row_ids) -> bool:
        """Take rows out of every permission, the default's and each client's.

        Args:
            row_ids: The row ids of things that are gone for good.

        Returns:
            Whether any permission named one of them.
        """
        dropped = {str(row_id) for row_id in row_ids}
        return self._rewrite_permissions(functools.partial(_without_rows, dropped))

    def sweep_waiting(self, now: float) -> list:
        """Remove every client that waits to join on a link that expired.

        Args:
            now: The time, in Unix seconds.

        Returns:
            The removed clients' ids.
        """
        with CONFIG_WRITE_LOCK:
            self._stored = self._read_stored()
            expired = [
                client.id
                for client in self.all()
                if client.is_waiting
                and (client.link_expires_at is None or client.link_expires_at < now)
            ]
            for client_id in expired:
                del self._stored[client_id]
            if expired:
                self._write_stored()
        return expired

    def forget_permission_rows(self, row_ids) -> bool:
        """Take rows out of the ``entries`` of every permission, the default's and each client's.

        Args:
            row_ids: The row ids of things gone for good, such as a removed
                folder share's.

        Returns:
            Whether any permission named one. The file is written once, and
            only when something changed.
        """
        gone = set(row_ids)
        with CONFIG_WRITE_LOCK:
            try:
                document = read_config(CLIENTS_CONFIG_PATH)
            except FileNotFoundError:
                return False
            permissions = [document.get("default_permission")]
            clients = document.get("clients")
            if isinstance(clients, dict):
                permissions += [
                    entry.get("permission")
                    for entry in clients.values()
                    if isinstance(entry, dict)
                ]
            is_changed = False
            for permission in permissions:
                entries = (
                    permission.get("entries") if isinstance(permission, dict) else None
                )
                if not isinstance(entries, dict) or not gone & set(entries):
                    continue
                kept = {key: value for key, value in entries.items() if key not in gone}
                if kept:
                    permission["entries"] = kept
                else:
                    del permission["entries"]
                is_changed = True
            if is_changed:
                write_config(CLIENTS_CONFIG_PATH, document)
                self._stored = self._read_stored()
        return is_changed

    def forget(self, client_id: str) -> None:
        """Remove a client's record. An unknown id is ignored."""
        with CONFIG_WRITE_LOCK:
            self._stored = self._read_stored()
            self._stored.pop(client_id, None)
            self._write_stored()

    def _rewrite_permissions(self, rewrite) -> bool:
        """Rewrite the default and every client's own permission.

        Args:
            rewrite: Takes ``(kinds, devices, entries)`` and returns them
                rewritten.

        Returns:
            Whether any permission changed; the file is written then.
        """
        with CONFIG_WRITE_LOCK:
            self._stored = self._read_stored()
            is_changed = False
            before = (
                self.default_permission(),
                self._default_devices,
                self._default_entries,
            )
            after = rewrite(*before)
            if after != before:
                self._default, self._default_devices, self._default_entries = after
                is_changed = True
            for client_id, entry in self._stored.items():
                client = Client.from_dict(client_id, entry)
                if client.permission is None:
                    continue
                before = (
                    client.permission,
                    client.permission_devices,
                    client.permission_entries,
                )
                after = rewrite(*before)
                if after != before:
                    entry["permission"] = _permission_document(*after)
                    is_changed = True
            if is_changed:
                self._write_stored()
        return is_changed

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
            self._default = None
            self._default_devices = {}
            self._default_entries = {}
            self._is_ssh_granted = False
            self._is_file_present = False
            return {}
        self._is_file_present = True
        self._is_ssh_granted = data.get(CLIENT_SSH_GRANTED_KEY) is True
        self._default = _stored_kinds(data.get("default_permission"))
        self._default_devices = _stored_devices(data.get("default_permission"))
        self._default_entries = _stored_entries(data.get("default_permission"))
        clients = data.get("clients", {})
        return dict(clients) if isinstance(clients, dict) else {}

    def _write_stored(self) -> None:
        document = {"clients": self._stored}
        if self._default is not None:
            document = {
                "default_permission": _permission_document(
                    self._default, self._default_devices, self._default_entries
                ),
                **document,
            }
        # A file this hub writes is one the ``ssh`` grant has run on, or one
        # made after the kind existed; either way the grant is not owed.
        document = {CLIENT_SSH_GRANTED_KEY: True, **document}
        self._is_ssh_granted = True
        self._is_file_present = True
        write_config(CLIENTS_CONFIG_PATH, document)
