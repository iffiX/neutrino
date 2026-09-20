"""The record of the last update, shared by the panel and the install unit.

One JSON file under the state root. The panel writes it while it stages the
package and once it hands the install over; the unit's script writes it at
every turn after that, in the same shape, so the panel that comes back reads
where things ended.
"""

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from neutrino_hub.modules.hub_update.constants import (
    HUB_UPDATE_DIR_NAME,
    HUB_UPDATE_REASON_INTERRUPTED,
    HUB_UPDATE_STAGE_FAILED,
    HUB_UPDATE_STAGE_PREPARING,
    HUB_UPDATE_STAGES,
    HUB_UPDATE_STAGES_IN_UNIT,
    HUB_UPDATE_STATE_MODE,
    HUB_UPDATE_STATE_NAME,
)
from neutrino_hub.utils import constants
from neutrino_hub.utils.json_file import write_generated


@dataclass
class HubUpdateRecord:
    """Where one update stands.

    Attributes:
        stage: One of the ``HUB_UPDATE_STAGE_*`` words.
        from_version: The version the update started from.
        to_version: The version it installs.
        started_at: When it started, as an ISO stamp.
        finished_at: When it settled, empty while it runs.
        reason: Why the target was given up on, empty when it was not; the
            first failure, whatever the rollback did after it.
        output: The tail of the install's log, once the unit has run.
    """

    stage: str
    from_version: str
    to_version: str
    started_at: str
    finished_at: str = ""
    reason: str = ""
    output: str = ""


class HubUpdateStateFile:
    """The one file both the panel and the unit's script write."""

    def __init__(self, *, path: Path | None = None):
        """Set up the file.

        Args:
            path: Where it lives; None puts it under the state root, resolved
                at each call so a test's root is honoured.
        """
        self._path = path

    @property
    def path(self) -> Path:
        """Where the file lives now."""
        return (
            self._path
            or constants.UTILS_STATE_ROOT / HUB_UPDATE_DIR_NAME / HUB_UPDATE_STATE_NAME
        )

    def load(self) -> HubUpdateRecord | None:
        """Read the record, tolerant of anything on disk.

        Returns:
            The record, or None when the file is missing, unreadable, or not
            shaped like one; a box with no readable record has no update to
            speak of.
        """
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(raw, dict) or raw.get("stage") not in HUB_UPDATE_STAGES:
            return None
        return HubUpdateRecord(
            stage=str(raw.get("stage")),
            from_version=str(raw.get("from_version") or ""),
            to_version=str(raw.get("to_version") or ""),
            started_at=str(raw.get("started_at") or ""),
            finished_at=str(raw.get("finished_at") or ""),
            reason=str(raw.get("reason") or ""),
            output=str(raw.get("output") or ""),
        )

    def save(self, record: HubUpdateRecord) -> None:
        """Write the record out, atomically.

        Args:
            record: What to write.
        """
        write_generated(
            self.path,
            json.dumps(asdict(record), indent=2) + "\n",
            mode=HUB_UPDATE_STATE_MODE,
        )

    def settle(
        self, *, is_unit_active: bool, is_task_running: bool
    ) -> HubUpdateRecord | None:
        """The record, with a run that died without writing marked as such.

        A record still ``preparing`` with no task staging it, or still in
        the unit with no unit running, was interrupted: the process that
        would have written the next stage is gone.

        Args:
            is_unit_active: Whether the install unit is running now.
            is_task_running: Whether a staging task is running now.

        Returns:
            The record as it stands, or None when there is none.
        """
        record = self.load()
        if record is None:
            return None
        is_orphaned = (
            record.stage == HUB_UPDATE_STAGE_PREPARING and not is_task_running
        ) or (record.stage in HUB_UPDATE_STAGES_IN_UNIT and not is_unit_active)
        if not is_orphaned:
            return record
        record.stage = HUB_UPDATE_STAGE_FAILED
        record.reason = record.reason or HUB_UPDATE_REASON_INTERRUPTED
        self.save(record)
        return record
