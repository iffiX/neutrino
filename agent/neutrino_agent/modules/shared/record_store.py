"""What each instance of a module is, kept root-only on the machine.

The hub stops naming a module in its state once the machine has settled
it, so the forwarder of a running instance starts again after the agent
restarts from what is kept here: one file per account holding the fields
the module names, mode 0600 in a directory only the agent's own account
reads; on Windows, where the module's directory is open to every account,
each file is left to SYSTEM and the administrators alone before anything is
written into it. An instance whose account is no longer enabled keeps a retired
record of its port alone, so the account takes the same port when it is
enabled again.

Not pure: writes files.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import json
import os
import tempfile

# The end of every record's file name.
RECORD_SUFFIX = ".json"
# What a retired record holds beside the account: its port, and the mark.
RECORD_PORT_FIELD = "port"
RECORD_RETIRED_FIELD = "is_retired"


class InstanceRecordStore:
    """One root-only file per instance, by account."""

    def __init__(self, *, directory: str, fields: tuple, seal=None):
        """
        Args:
            directory: Where the records live.
            fields: The fields one record holds; ``account`` names its file.
            seal: Called with a new file's path before anything is written
                into it, to leave it to the agent's own account; None leaves
                it to its mode.
        """
        self.directory = directory
        self._fields = tuple(fields)
        self._seal = seal

    def read_all(self) -> list:
        """Every record held, by account; a retired one left out.

        Returns:
            The records, an unreadable one left out.
        """
        return [
            {name: held.get(name) for name in self._fields}
            for held in self._read_files()
            if not held.get(RECORD_RETIRED_FIELD)
        ]

    def kept_ports(self) -> dict:
        """The port every record keeps, a retired one's included.

        Returns:
            Account to port, a record with no port left out.
        """
        ports = {}
        for held in self._read_files():
            try:
                port = int(held.get(RECORD_PORT_FIELD) or 0)
            except (TypeError, ValueError):
                port = 0
            if port:
                ports[str(held.get("account", "") or "")] = port
        return ports

    def read(self, account: str) -> dict:
        """One account's record.

        Args:
            account: The account.

        Returns:
            The record, empty when none is held.
        """
        for record in self.read_all():
            if record.get("account") == account:
                return record
        return {}

    def write(self, record: dict) -> None:
        """Keep one record whole, mode 0600.

        Args:
            record: The record; the fields the store holds are kept.

        Raises:
            OSError: When the file cannot be written.
        """
        self._write_file(
            str(record["account"]), {name: record.get(name) for name in self._fields}
        )

    def retire(self, account: str) -> None:
        """Keep one account's port alone, and forget the rest of its record.

        Args:
            account: The account.

        Raises:
            OSError: When the file cannot be written.
        """
        port = self.kept_ports().get(account, 0)
        if not port:
            self.remove(account)
            return
        self._write_file(
            account,
            {"account": account, RECORD_PORT_FIELD: port, RECORD_RETIRED_FIELD: True},
        )

    def remove(self, account: str) -> None:
        """Forget one account's record, a retired one's port included.

        Args:
            account: The account.
        """
        with contextlib.suppress(OSError):
            os.unlink(self._path(account))

    def accounts(self) -> list:
        """The accounts a record is held for, sorted."""
        try:
            names = os.listdir(self.directory)
        except OSError:
            return []
        return sorted(
            name[: -len(RECORD_SUFFIX)]
            for name in names
            if name.endswith(RECORD_SUFFIX) and not name.startswith(".")
        )

    def _path(self, account: str) -> str:
        return os.path.join(self.directory, account + RECORD_SUFFIX)

    def _read_files(self) -> list:
        """Every file's object, retired ones among them; an unreadable one left out."""
        found = []
        for account in self.accounts():
            try:
                with open(self._path(account), "r", encoding="utf-8") as stream:
                    held = json.load(stream)
            except (OSError, ValueError):
                continue
            if isinstance(held, dict):
                found.append(held)
        return found

    def _write_file(self, account: str, content: dict) -> None:
        """Write one account's file whole, mode 0600, through a file beside it."""
        os.makedirs(self.directory, mode=0o700, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=self.directory, prefix=".record_")
        try:
            if self._seal is not None:
                self._seal(temporary)
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(content, stream)
            os.chmod(temporary, 0o600)
            os.replace(temporary, self._path(account))
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(temporary)
            raise
