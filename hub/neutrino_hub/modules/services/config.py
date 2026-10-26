"""The apps somebody declares on machines the hub does not run.

A NAS's share, an HTTP server, a plain TCP or UDP port: each is an entry of
an app in ``config/services/declared.json``, ``apps`` each ``{id, name,
host, description, created_at, entries}`` with one entry at least, each
``{type, port, scheme, path, protocol, share}`` as ``declaration/add`` takes
it. The file holds no secrets: a share's login is typed on the machine that
mounts it, never here. A 0.5 record of the kind ``http``, ``generic_tcp`` or
``generic_udp`` reads as an app of one entry with the record's id, a
``samba`` record as an app with one ``file`` entry per share it names, and
each is written into ``apps`` at the next write of the file.

Pure: this module parses, validates and stores configuration. Measuring
whether an entry answers is :mod:`neutrino_hub.modules.services.probe`.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from neutrino_hub.exceptions import ServiceFieldInvalidError
from neutrino_hub.modules.services.apps import slug
from neutrino_hub.modules.services.constants import (
    SERVICES_DECLARED_ENTRY_TYPES,
    SERVICES_DECLARED_PATH,
    SERVICES_ENTRY_DECLARED_FILE,
    SERVICES_ENTRY_DECLARED_PORT,
    SERVICES_ENTRY_DECLARED_WEB,
    SERVICES_ERROR_INVALID,
    SERVICES_HTTP_SCHEMES,
    SERVICES_KIND_GENERIC_TCP,
    SERVICES_KIND_GENERIC_UDP,
    SERVICES_KIND_HTTP,
    SERVICES_KIND_SAMBA,
    SERVICES_PORT_MAX,
    SERVICES_PORT_MIN,
    SERVICES_PORT_PROTOCOLS,
    SERVICES_PROTOCOL_TCP,
    SERVICES_PROTOCOL_UDP,
    SERVICES_SAMBA_DEFAULT_PORT,
    SERVICES_TYPE_FILE,
    SERVICES_TYPE_PORT,
    SERVICES_TYPE_WEB,
    SERVICES_UDP_ID_SUFFIX,
)
from neutrino_hub.utils.json_file import (
    CONFIG_WRITE_LOCK,
    read_config,
    write_config,
)


@dataclass
class DeclaredEntry:
    """One entry of a declared app.

    Attributes:
        type: ``web``, ``port`` or ``file``.
        port: The port it answers on; 445 for a share left blank.
        scheme: ``http`` or ``https``, on a ``web`` entry.
        path: The path a ``web`` entry is probed on, ``/`` when blank.
        protocol: ``tcp`` or ``udp``, on a ``port`` entry.
        share: The share's name on the server, on a ``file`` entry.
    """

    type: str
    port: int
    scheme: str = ""
    path: str = ""
    protocol: str = ""
    share: str = ""

    @property
    def name(self) -> str:
        """The entry's name inside its app.

        Returns:
            ``web_<port>`` for a ``web`` entry, ``port_<port>`` for a TCP
            ``port`` entry and ``port_<port>_udp`` for a UDP one,
            ``file_<slug of the share>`` for a ``file`` entry.
        """
        if self.type == SERVICES_TYPE_WEB:
            return SERVICES_ENTRY_DECLARED_WEB.format(port=self.port)
        if self.type == SERVICES_TYPE_PORT:
            made = SERVICES_ENTRY_DECLARED_PORT.format(port=self.port)
            if self.protocol == SERVICES_PROTOCOL_UDP:
                made += SERVICES_UDP_ID_SUFFIX
            return made
        return SERVICES_ENTRY_DECLARED_FILE.format(share=slug(self.share))

    @classmethod
    def from_dict(cls, data: dict) -> "DeclaredEntry":
        """Build from a stored entry.

        Args:
            data: The stored object.

        Returns:
            The parsed entry.
        """
        return cls(
            type=str(data.get("type", "") or ""),
            port=int(data.get("port", 0) or 0),
            scheme=str(data.get("scheme", "") or ""),
            path=str(data.get("path", "") or ""),
            protocol=str(data.get("protocol", "") or ""),
            share=str(data.get("share", "") or ""),
        )

    def to_dict(self) -> dict:
        """Serialize for storage, carrying only the fields its type has."""
        stored = {"type": self.type, "port": self.port}
        if self.type == SERVICES_TYPE_WEB:
            stored["scheme"] = self.scheme
            stored["path"] = self.path
        elif self.type == SERVICES_TYPE_PORT:
            stored["protocol"] = self.protocol
        else:
            stored["share"] = self.share
        return stored


@dataclass
class DeclaredApp:
    """One app somebody declared.

    Attributes:
        id: Stable identifier other records reference.
        name: Human-chosen title.
        host: Where it answers.
        description: The declarer's one line of provenance.
        created_at: ISO timestamp of when it was declared.
        entries: Its entries, one at least.
    """

    id: str
    name: str
    host: str
    description: str = ""
    created_at: str = ""
    entries: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "DeclaredApp":
        """Build from a stored app.

        Args:
            data: The stored object.

        Returns:
            The parsed app.
        """
        return cls(
            id=str(data.get("id", "") or ""),
            name=str(data.get("name", "") or ""),
            host=str(data.get("host", "") or ""),
            description=str(data.get("description", "") or ""),
            created_at=str(data.get("created_at", "") or ""),
            entries=[
                DeclaredEntry.from_dict(entry)
                for entry in data.get("entries") or []
                if isinstance(entry, dict)
            ],
        )

    @classmethod
    def from_record(cls, data: dict) -> "DeclaredApp | None":
        """Build from a 0.5 record of the ``services`` list.

        Args:
            data: The stored record, ``{id, name, kind, host, port, ...}``.

        Returns:
            The app of one entry a web or a port record is, or one with a
            ``file`` entry per share for a ``samba`` record; None for a kind
            the hub does not know.
        """
        kind = str(data.get("kind", "") or "")
        port = int(data.get("port", 0) or 0)
        if kind == SERVICES_KIND_HTTP:
            entries = [
                DeclaredEntry(
                    type=SERVICES_TYPE_WEB,
                    port=port,
                    scheme=str(data.get("scheme", "") or SERVICES_HTTP_SCHEMES[0]),
                    path=str(data.get("path", "") or "/"),
                )
            ]
        elif kind in (SERVICES_KIND_GENERIC_TCP, SERVICES_KIND_GENERIC_UDP):
            protocol = (
                SERVICES_PROTOCOL_UDP
                if kind == SERVICES_KIND_GENERIC_UDP
                else SERVICES_PROTOCOL_TCP
            )
            entries = [
                DeclaredEntry(type=SERVICES_TYPE_PORT, port=port, protocol=protocol)
            ]
        elif kind == SERVICES_KIND_SAMBA:
            entries = [
                DeclaredEntry(
                    type=SERVICES_TYPE_FILE,
                    port=port or SERVICES_SAMBA_DEFAULT_PORT,
                    share=str(share.get("name", "") or ""),
                )
                for share in data.get("shares") or []
                if isinstance(share, dict) and share.get("name")
            ]
        else:
            return None
        return cls(
            id=str(data.get("id", "") or ""),
            name=str(data.get("name", "") or ""),
            host=str(data.get("host", "") or ""),
            description=str(data.get("description", "") or ""),
            created_at=str(data.get("created_at", "") or ""),
            entries=entries,
        )

    def to_dict(self) -> dict:
        """Serialize for storage."""
        return {
            "id": self.id,
            "name": self.name,
            "host": self.host,
            "description": self.description,
            "created_at": self.created_at,
            "entries": [entry.to_dict() for entry in self.entries],
        }


# The config-wide lock: a mutation re-reads the file under it, and an
# operation that also touches another store nests under the same lock.
_WRITE_LOCK = CONFIG_WRITE_LOCK


class DeclaredAppRegistry:
    """Reads and edits the declared apps."""

    def __init__(self):
        self._apps = self._read()

    def list_apps(self) -> list:
        """Read every declared app, newest first.

        Returns:
            The stored apps.
        """
        return sorted(self._apps, key=lambda app: app.created_at, reverse=True)

    def get(self, app_id: str) -> "DeclaredApp | None":
        """Look one declared app up.

        Args:
            app_id: The app's id.

        Returns:
            The app, or None when unknown.
        """
        return next((app for app in self._apps if app.id == app_id), None)

    def add(
        self, *, name: str, host: str, entries: list, description: str = ""
    ) -> DeclaredApp:
        """Store a new declared app.

        Args:
            name: Human-chosen title.
            host: Where it answers.
            entries: Its entries, each as :func:`build_entry` takes it.
            description: The declarer's one line of provenance.

        Returns:
            The stored app.

        Raises:
            ServiceFieldInvalidError: If a field does not validate, naming
                it as ``name``, ``host``, ``entries`` or
                ``entries.<n>.<field>``.
        """
        app = build_app(
            app_id=uuid.uuid4().hex,
            name=name,
            host=host,
            entries=entries,
            description=description,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        with _WRITE_LOCK:
            self._apps = self._read()
            self._apps.append(app)
            self._write()
        return app

    def delete(self, app_id: str) -> None:
        """Remove a declared app.

        Args:
            app_id: The app's id.

        Raises:
            KeyError: If the id is unknown.
        """
        with _WRITE_LOCK:
            self._apps = self._read()
            if self.get(app_id) is None:
                raise KeyError(app_id)
            self._apps = [app for app in self._apps if app.id != app_id]
            self._write()

    def _read(self) -> list:
        try:
            data = read_config(SERVICES_DECLARED_PATH)
        except FileNotFoundError:
            return []
        apps = [
            DeclaredApp.from_dict(entry)
            for entry in data.get("apps") or []
            if isinstance(entry, dict) and entry.get("id")
        ]
        for record in data.get("services") or []:
            if not isinstance(record, dict) or not record.get("id"):
                continue
            app = DeclaredApp.from_record(record)
            if app is not None and app.entries:
                apps.append(app)
        return apps

    def _write(self) -> None:
        write_config(
            SERVICES_DECLARED_PATH, {"apps": [app.to_dict() for app in self._apps]}
        )


def build_entry(data: dict, *, where: str = "") -> DeclaredEntry:
    """Validate one entry's fields and shape them into an entry.

    Args:
        data: ``{type, port, scheme, path, protocol, share}`` as the form
            sends it; ``scheme`` and ``path`` for ``web``, ``protocol`` for
            ``port`` (``tcp`` when absent), ``share`` for ``file`` (its port
            445 when absent).
        where: What a refusal names in front of the field, such as
            ``entries.0``.

    Returns:
        The validated entry.

    Raises:
        ServiceFieldInvalidError: Naming the first field that does not
            validate.
    """
    prefix = f"{where}." if where else ""
    kind = str(data.get("type", "") or "")
    if kind not in SERVICES_DECLARED_ENTRY_TYPES:
        _refuse(f"{prefix}type")
    port = data.get("port")
    if port is None or port == "":
        if kind != SERVICES_TYPE_FILE:
            _refuse(f"{prefix}port")
        port = SERVICES_SAMBA_DEFAULT_PORT
    if isinstance(port, bool) or not isinstance(port, int):
        _refuse(f"{prefix}port")
    if not SERVICES_PORT_MIN <= port <= SERVICES_PORT_MAX:
        _refuse(f"{prefix}port")
    entry = DeclaredEntry(type=kind, port=port)
    if kind == SERVICES_TYPE_WEB:
        entry.scheme = str(data.get("scheme", "") or SERVICES_HTTP_SCHEMES[0])
        if entry.scheme not in SERVICES_HTTP_SCHEMES:
            _refuse(f"{prefix}scheme")
        path = str(data.get("path", "") or "").strip()
        entry.path = path or "/"
        if not entry.path.startswith("/"):
            _refuse(f"{prefix}path")
    elif kind == SERVICES_TYPE_PORT:
        entry.protocol = str(data.get("protocol", "") or SERVICES_PROTOCOL_TCP)
        if entry.protocol not in SERVICES_PORT_PROTOCOLS:
            _refuse(f"{prefix}protocol")
    else:
        entry.share = str(data.get("share", "") or "").strip()
        if not entry.share:
            _refuse(f"{prefix}share")
    return entry


def build_app(
    *,
    app_id: str,
    name: str,
    host: str,
    entries: list,
    description: str,
    created_at: str,
) -> DeclaredApp:
    """Validate the fields and shape them into an app.

    Args:
        app_id: The app's id.
        name: Human-chosen title.
        host: Where it answers.
        entries: Its entries, each a dict as :func:`build_entry` takes it.
        description: The declarer's one line of provenance.
        created_at: ISO timestamp the app keeps.

    Returns:
        The validated app.

    Raises:
        ServiceFieldInvalidError: Naming the first field that does not
            validate: ``name``, ``host``, ``entries`` for no entry, two of
            one type, port and protocol or two shares of one slug, or
            ``entries.<n>.<field>``.
    """
    if not name.strip():
        _refuse("name")
    if not host.strip():
        _refuse("host")
    if not isinstance(entries, list) or not entries:
        _refuse("entries")
    built = []
    for index, data in enumerate(entries):
        if not isinstance(data, dict):
            _refuse(f"entries.{index}")
        built.append(build_entry(data, where=f"entries.{index}"))
    if len({entry.name for entry in built}) != len(built):
        _refuse("entries")
    return DeclaredApp(
        id=app_id,
        name=name.strip(),
        host=host.strip(),
        description=description.strip(),
        created_at=created_at,
        entries=built,
    )


def _refuse(field_name: str) -> None:
    raise ServiceFieldInvalidError(SERVICES_ERROR_INVALID, {"field": field_name})
