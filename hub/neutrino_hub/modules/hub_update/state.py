"""The record of the last update, shared by the panel and the install unit.

One JSON file under the state root. The panel writes it while it stages the
package and once it hands the install over; the unit's script writes it at
every turn after that, in the same shape, so the panel that comes back reads
where things ended.
"""

import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from neutrino_hub.modules.hub_update.constants import (
    HUB_UPDATE_DIR_NAME,
    HUB_UPDATE_REASON_INTERRUPTED,
    HUB_UPDATE_SETTLE_GRACE_S,
    HUB_UPDATE_STAGE_FAILED,
    HUB_UPDATE_STAGE_PREPARING,
    HUB_UPDATE_STAGES,
    HUB_UPDATE_STAGES_IN_UNIT,
    HUB_UPDATE_STATE_MODE,
    HUB_UPDATE_STATE_NAME,
)
from neutrino_hub.utils import constants
from neutrino_hub.utils.json_file import write_generated

PERCENT_STEP = re.compile(r"^[0-9]+%$")
PERCENT_ROW = re.compile(r"^[0-9]+%(  [0-9]+%)*$")
STAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


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
        steps: The lines a person reads, one per step, the download's
            percentages joined on one line; versions and file names only,
            nothing a package manager printed.
    """

    stage: str
    from_version: str
    to_version: str
    started_at: str
    finished_at: str = ""
    reason: str = ""
    output: str = ""
    steps: list[str] = field(default_factory=list)


def append_step(steps: list[str], line: str) -> None:
    """Add one line to a record's steps, a percentage to the row before it.

    Args:
        steps: The steps so far, changed in place.
        line: The line said.
    """
    if PERCENT_STEP.match(line) and steps and PERCENT_ROW.match(steps[-1]):
        steps[-1] = f"{steps[-1]}  {line}"
        return
    steps.append(line)


def stamp_now() -> str:
    """The time now, as the record stamps it.

    Returns:
        An ISO stamp in UTC, to the second.
    """
    return datetime.now(timezone.utc).strftime(STAMP_FORMAT)


def stamp_age_s(stamp: str, *, now: float | None = None) -> float | None:
    """How long ago a record's stamp was.

    Args:
        stamp: An ISO stamp as the record writes it.
        now: The epoch second to measure from; None is now.

    Returns:
        Seconds, or None when the stamp does not parse.
    """
    try:
        moment = datetime.strptime(stamp, STAMP_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (time.time() if now is None else now) - moment.timestamp()


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
        steps = raw.get("steps")
        return HubUpdateRecord(
            stage=str(raw.get("stage")),
            from_version=str(raw.get("from_version") or ""),
            to_version=str(raw.get("to_version") or ""),
            started_at=str(raw.get("started_at") or ""),
            finished_at=str(raw.get("finished_at") or ""),
            reason=str(raw.get("reason") or ""),
            output=str(raw.get("output") or ""),
            steps=[str(step) for step in steps] if isinstance(steps, list) else [],
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
        self,
        *,
        is_unit_active: bool,
        is_task_running: bool,
        grace_s: float = HUB_UPDATE_SETTLE_GRACE_S,
    ) -> HubUpdateRecord | None:
        """The record, with a run that died without writing marked as such.

        A record still ``preparing`` with no task staging it, or still in
        the unit with no unit running, was interrupted: the process that
        would have written the next stage is gone. A record written less
        than ``grace_s`` ago is left as it is, since the unit, job or
        process just started may not be running yet.

        Args:
            is_unit_active: Whether the install unit is running now.
            is_task_running: Whether a staging task is running now.
            grace_s: How recent a write leaves the record alone.

        Returns:
            The record as it stands, or None when there is none.
        """
        record = self.load()
        if record is None:
            return None
        is_orphaned = (
            record.stage == HUB_UPDATE_STAGE_PREPARING and not is_task_running
        ) or (record.stage in HUB_UPDATE_STAGES_IN_UNIT and not is_unit_active)
        if not is_orphaned or self._written_within(grace_s):
            return record
        record.stage = HUB_UPDATE_STAGE_FAILED
        record.reason = record.reason or HUB_UPDATE_REASON_INTERRUPTED
        record.finished_at = record.finished_at or stamp_now()
        self.save(record)
        return record

    def _written_within(self, seconds: float) -> bool:
        """Whether the file was written less than this many seconds ago."""
        try:
            return time.time() - self.path.stat().st_mtime < seconds
        except OSError:
            return False
