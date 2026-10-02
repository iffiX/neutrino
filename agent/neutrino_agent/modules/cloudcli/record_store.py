"""What each instance's forwarder serves, kept root-only on the machine.

The hub stops naming a module in its state once the machine has settled
it, so the forwarder of a running instance starts again after the agent
restarts from what is kept here: one file per account, ``{account, port,
upstream_port, web_password, token_secret}``, mode 0600 in a directory only
the agent's own account reads.

Not pure: writes files.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import json
import os
import tempfile

from neutrino_agent.modules.cloudcli.constants import CLOUDCLI_RECORD_SUFFIX

# The fields one record holds.
RECORD_FIELDS = ("account", "port", "upstream_port", "web_password", "token_secret")


class CloudcliRecordStore:
    """One root-only file per instance, by account."""

    def __init__(self, *, directory: str):
        """
        Args:
            directory: Where the records live.
        """
        self.directory = directory

    def read_all(self) -> list:
        """Every record held, by account.

        Returns:
            The records, an unreadable one left out.
        """
        records = []
        for account in self.accounts():
            try:
                with open(self._path(account), "r", encoding="utf-8") as stream:
                    held = json.load(stream)
            except (OSError, ValueError):
                continue
            if isinstance(held, dict):
                records.append({name: held.get(name) for name in RECORD_FIELDS})
        return records

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
            record: ``{account, port, upstream_port, web_password,
                token_secret}``.

        Raises:
            OSError: When the file cannot be written.
        """
        os.makedirs(self.directory, mode=0o700, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=self.directory, prefix=".record_")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump({name: record.get(name) for name in RECORD_FIELDS}, stream)
            os.chmod(temporary, 0o600)
            os.replace(temporary, self._path(str(record["account"])))
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(temporary)
            raise

    def remove(self, account: str) -> None:
        """Forget one account's record.

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
            name[: -len(CLOUDCLI_RECORD_SUFFIX)]
            for name in names
            if name.endswith(CLOUDCLI_RECORD_SUFFIX) and not name.startswith(".")
        )

    def _path(self, account: str) -> str:
        return os.path.join(self.directory, account + CLOUDCLI_RECORD_SUFFIX)
