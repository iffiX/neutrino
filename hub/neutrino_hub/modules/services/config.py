"""The services somebody declares on machines the hub does not run.

A NAS's Samba, an HTTP server, a plain TCP port: each is a record in
``config/services/declared.json`` naming where it answers, so the hub can
watch it and publish it to devices. The file holds no secrets — a share's
login is typed on the machine that mounts it, never here.

Pure: this module parses, validates and stores configuration. Measuring
whether a declared service answers is :mod:`neutrino_hub.modules.services.probe`.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from neutrino_hub.modules.services.constants import (
    SERVICES_DECLARED_KINDS,
    SERVICES_DECLARED_PATH,
    SERVICES_ERROR_INVALID,
    SERVICES_HTTP_SCHEMES,
    SERVICES_KIND_HTTP,
    SERVICES_KIND_SAMBA,
    SERVICES_PORT_MAX,
    SERVICES_PORT_MIN,
    SERVICES_SAMBA_DEFAULT_PORT,
)
from neutrino_hub.utils.json_file import (
    CONFIG_WRITE_LOCK,
    read_config,
    write_config,
)


class DeclaredServiceError(ValueError):
    """A declared service that cannot be stored.

    Attributes:
        code: Machine name of the refusal; the pages do the wording.
        params: The values the refusal's sentence needs.
    """

    def __init__(self, code: str, params: dict | None = None):
        super().__init__(code)
        self.code = code
        self.params = params or {}


@dataclass
class DeclaredShare:
    """One share a declared Samba service exports.

    Attributes:
        name: The share's name on that server.
    """

    name: str

    @classmethod
    def from_dict(cls, data: dict) -> "DeclaredShare":
        return cls(name=data.get("name", ""))

    def to_dict(self) -> dict:
        return {"name": self.name}


@dataclass
class DeclaredService:
    """One user-declared service.

    Attributes:
        id: Stable identifier other records reference.
        name: Human-chosen label.
        kind: One of :data:`SERVICES_DECLARED_KINDS`.
        host: Where it answers.
        port: The TCP port it answers on.
        scheme: ``http`` or ``https``; only an ``http`` kind carries one.
        path: The path an ``http`` kind is probed on.
        shares: The exports of a ``samba`` kind.
        description: The declarer's one line of provenance.
        created_at: ISO timestamp of when it was declared.
    """

    id: str
    name: str
    kind: str
    host: str
    port: int
    scheme: str | None = None
    path: str | None = None
    shares: list[DeclaredShare] = field(default_factory=list)
    description: str = ""
    created_at: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "DeclaredService":
        """Build from a stored entry.

        Args:
            data: The stored object.

        Returns:
            The parsed record.
        """
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            kind=data.get("kind", ""),
            host=data.get("host", ""),
            port=int(data.get("port", 0)),
            scheme=data.get("scheme"),
            path=data.get("path"),
            shares=[DeclaredShare.from_dict(entry) for entry in data.get("shares", [])],
            description=data.get("description", ""),
            created_at=data.get("created_at", ""),
        )

    def to_dict(self) -> dict:
        """Serialize for storage, carrying only the fields the kind has.

        Returns:
            A JSON-ready object.
        """
        entry = {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "host": self.host,
            "port": self.port,
            "description": self.description,
            "created_at": self.created_at,
        }
        if self.kind == SERVICES_KIND_HTTP:
            entry["scheme"] = self.scheme
            entry["path"] = self.path
        if self.kind == SERVICES_KIND_SAMBA:
            entry["shares"] = [share.to_dict() for share in self.shares]
        return entry


# The config-wide lock: a mutation re-reads the file under it, and an
# operation that also touches another store nests under the same lock.
_WRITE_LOCK = CONFIG_WRITE_LOCK


class DeclaredServiceRegistry:
    """Reads and edits the declared services."""

    def __init__(self):
        self._records = self._read()

    def list_records(self) -> list[DeclaredService]:
        """Read every declared service, newest first.

        Returns:
            The stored records.
        """
        return sorted(self._records, key=lambda r: r.created_at, reverse=True)

    def get(self, service_id: str) -> DeclaredService | None:
        """Look one declared service up.

        Args:
            service_id: The record's id.

        Returns:
            The record, or None when unknown.
        """
        return next((r for r in self._records if r.id == service_id), None)

    def add(
        self,
        *,
        name: str,
        kind: str,
        host: str,
        port: int | None = None,
        scheme: str | None = None,
        path: str | None = None,
        shares: list[DeclaredShare] | None = None,
        description: str = "",
    ) -> DeclaredService:
        """Store a new declared service.

        Args:
            name: Human-chosen label.
            kind: One of :data:`SERVICES_DECLARED_KINDS`.
            host: Where it answers.
            port: The TCP port; a ``samba`` kind left blank gets 445.
            scheme: ``http`` or ``https``, for the ``http`` kind.
            path: The probe path, for the ``http`` kind; blank means ``/``.
            shares: The exports, for the ``samba`` kind.
            description: The declarer's one line of provenance.

        Returns:
            The stored record.

        Raises:
            DeclaredServiceError: If a field does not validate.
        """
        record = _build_record(
            record_id=uuid.uuid4().hex,
            name=name,
            kind=kind,
            host=host,
            port=port,
            scheme=scheme,
            path=path,
            shares=shares,
            description=description,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        with _WRITE_LOCK:
            self._records = self._read()
            self._records.append(record)
            self._write()
        return record

    def delete(self, service_id: str) -> None:
        """Remove a declared service.

        Args:
            service_id: The record's id.

        Raises:
            KeyError: If the id is unknown.
        """
        with _WRITE_LOCK:
            self._records = self._read()
            if self.get(service_id) is None:
                raise KeyError(service_id)
            self._records = [r for r in self._records if r.id != service_id]
            self._write()

    def _read(self) -> list[DeclaredService]:
        try:
            data = read_config(SERVICES_DECLARED_PATH)
        except FileNotFoundError:
            return []
        # A stored kind the hub no longer knows — the retired docker_engine —
        # is dropped on read, so the file heals on the next write.
        return [
            DeclaredService.from_dict(entry)
            for entry in data.get("services", [])
            if entry.get("kind") in SERVICES_DECLARED_KINDS
        ]

    def _write(self) -> None:
        write_config(
            SERVICES_DECLARED_PATH,
            {"services": [record.to_dict() for record in self._records]},
        )


def _build_record(
    *,
    record_id: str,
    name: str,
    kind: str,
    host: str,
    port: int | None,
    scheme: str | None,
    path: str | None,
    shares: list[DeclaredShare] | None,
    description: str,
    created_at: str,
) -> DeclaredService:
    """Validate the fields and shape them into a record.

    Args:
        record_id: The record's id.
        name: Human-chosen label.
        kind: One of :data:`SERVICES_DECLARED_KINDS`.
        host: Where it answers.
        port: The TCP port; a ``samba`` kind left blank gets 445.
        scheme: ``http`` or ``https``, for the ``http`` kind.
        path: The probe path, for the ``http`` kind; blank means ``/``.
        shares: The exports, for the ``samba`` kind.
        description: The declarer's one line of provenance.
        created_at: ISO timestamp the record keeps.

    Returns:
        The validated record, carrying only the fields its kind has.

    Raises:
        DeclaredServiceError: Naming the first field that does not validate.
    """
    if kind not in SERVICES_DECLARED_KINDS:
        raise DeclaredServiceError(SERVICES_ERROR_INVALID, {"field": "kind"})
    if not name.strip():
        raise DeclaredServiceError(SERVICES_ERROR_INVALID, {"field": "name"})
    if not host.strip():
        raise DeclaredServiceError(SERVICES_ERROR_INVALID, {"field": "host"})
    if port is None:
        if kind != SERVICES_KIND_SAMBA:
            raise DeclaredServiceError(SERVICES_ERROR_INVALID, {"field": "port"})
        port = SERVICES_SAMBA_DEFAULT_PORT
    if not SERVICES_PORT_MIN <= port <= SERVICES_PORT_MAX:
        raise DeclaredServiceError(SERVICES_ERROR_INVALID, {"field": "port"})

    record = DeclaredService(
        id=record_id,
        name=name.strip(),
        kind=kind,
        host=host.strip(),
        port=port,
        description=description.strip(),
        created_at=created_at,
    )
    if kind == SERVICES_KIND_HTTP:
        record.scheme = scheme or SERVICES_HTTP_SCHEMES[0]
        if record.scheme not in SERVICES_HTTP_SCHEMES:
            raise DeclaredServiceError(SERVICES_ERROR_INVALID, {"field": "scheme"})
        record.path = path.strip() if path else "/"
        if not record.path.startswith("/"):
            raise DeclaredServiceError(SERVICES_ERROR_INVALID, {"field": "path"})
    if kind == SERVICES_KIND_SAMBA:
        record.shares = list(shares or [])
        seen: set[str] = set()
        for share in record.shares:
            share.name = share.name.strip()
            if not share.name or share.name in seen:
                raise DeclaredServiceError(SERVICES_ERROR_INVALID, {"field": "shares"})
            seen.add(share.name)
        if not record.shares:
            raise DeclaredServiceError(SERVICES_ERROR_INVALID, {"field": "shares"})
    return record
