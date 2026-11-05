"""What a person's Podman units were before the module first changed them, on Linux.

The module's first Install or Start on a person's Podman keeps what
``podman.socket`` and ``podman.service`` were, each enabled and active or
neither, root-only in the module's directory under the state root, and a
Stop with nothing kept keeps it first. An uninstall on a person's Podman
puts both back from it and deletes it.

Not pure: reads and changes systemd units, reads and writes one file.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import json
import os

from neutrino_agent.modules.podman.constants import (
    PODMAN_API_UNIT,
    PODMAN_FOUND_UNITS,
    PODMAN_UNIT,
)

# The units kept and put back, in the order they are put back.
FOUND_UNITS = (PODMAN_UNIT, PODMAN_API_UNIT)


class PodmanFoundUnits:
    """The one file that keeps what a person's Podman units were."""

    def __init__(self, *, module_dir: str, run):
        """
        Args:
            module_dir: The module's directory under the state root.
            run: Runs one command as :func:`subprocess_run.run` does.
        """
        self._module_dir = module_dir
        self._path = os.path.join(module_dir, PODMAN_FOUND_UNITS)
        self._run = run

    def is_kept(self) -> bool:
        """Whether the file stands.

        Returns:
            True while the file is there.
        """
        return os.path.isfile(self._path)

    def keep(self) -> None:
        """Keep what each unit is now, unless a record is kept already.

        Raises:
            OSError: When the file cannot be written.
        """
        if self.is_kept():
            return
        found = {unit: self._read(unit) for unit in FOUND_UNITS}
        os.makedirs(self._module_dir, mode=0o700, exist_ok=True)
        descriptor = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(found, stream)

    def put_back(self) -> bool:
        """Make each unit enabled and active as the record found it, then delete the record.

        Returns:
            Whether a record was there to put back.
        """
        try:
            with open(self._path, encoding="utf-8") as stream:
                found = json.load(stream)
        except (OSError, ValueError):
            return False
        held = found if isinstance(found, dict) else {}
        for unit in FOUND_UNITS:
            state = held.get(unit) if isinstance(held.get(unit), dict) else {}
            verb = "enable" if state.get("is_enabled") else "disable"
            self._run(["systemctl", verb, unit], is_checked=False)
            verb = "start" if state.get("is_active") else "stop"
            self._run(["systemctl", verb, unit], is_checked=False)
        self.forget()
        return True

    def forget(self) -> None:
        """Delete the record, when there is one."""
        with contextlib.suppress(FileNotFoundError):
            os.unlink(self._path)

    def _read(self, unit: str) -> dict:
        """What one unit is now: ``{"is_enabled", "is_active"}``."""
        shown = self._run(
            ["systemctl", "show", "--property=UnitFileState,ActiveState", unit],
            is_checked=False,
        )
        lines = (getattr(shown, "stdout", "") or "").splitlines()
        fields = dict(line.split("=", 1) for line in lines if "=" in line)
        return {
            "is_enabled": fields.get("UnitFileState") == "enabled",
            "is_active": fields.get("ActiveState") == "active",
        }
