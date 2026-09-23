"""Staging the hub's own package and handing its install to systemd.

The package's maintainer script restarts the panel, which is the process that
would be running the install, so the panel only stages: it makes room, takes
the package down and checks its digest, keeps the running version's package
beside it as the rollback, writes the script below and starts it as a
transient unit. The unit installs, holds a health gate, and installs the
rollback when the gate fails; every turn it takes is written to the state
file the panel reads when it is back.
"""

import hashlib
import os
import shlex
import shutil
import subprocess
import tempfile
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from neutrino_hub import HUB_PACKAGE_ASSET
from neutrino_hub.exceptions import HubUpdateError
from neutrino_hub.modules.hub_update.constants import (
    HUB_UPDATE_DIR_MODE,
    HUB_UPDATE_DIR_NAME,
    HUB_UPDATE_FETCH_LIMIT_BYTES,
    HUB_UPDATE_FETCH_TIMEOUT_S,
    HUB_UPDATE_GATE_POLL_S,
    HUB_UPDATE_GATE_TIMEOUT_S,
    HUB_UPDATE_GATE_UNITS,
    HUB_UPDATE_HEADERS,
    HUB_UPDATE_HEALTH_PATH,
    HUB_UPDATE_LAUNCH_TIMEOUT_S,
    HUB_UPDATE_LOCK_TIMEOUT_S,
    HUB_UPDATE_LOG_NAME,
    HUB_UPDATE_OUTPUT_LIMIT_BYTES,
    HUB_UPDATE_PACKAGE_MODE,
    HUB_UPDATE_PANEL_UNIT,
    HUB_UPDATE_REASON_GATE_FAILED,
    HUB_UPDATE_REASON_INSTALL_FAILED,
    HUB_UPDATE_REASON_LAUNCH_FAILED,
    HUB_UPDATE_REASON_PACKAGE_FETCH_FAILED,
    HUB_UPDATE_REASON_PACKAGE_SHA256_MISMATCH,
    HUB_UPDATE_REASON_ROLLBACK_FETCH_FAILED,
    HUB_UPDATE_REASON_SPACE_SHORT,
    HUB_UPDATE_SCRIPT_MODE,
    HUB_UPDATE_SCRIPT_NAME,
    HUB_UPDATE_STAGE_FAILED,
    HUB_UPDATE_STAGE_INSTALLED,
    HUB_UPDATE_STAGE_INSTALLING,
    HUB_UPDATE_STAGE_ROLLED_BACK,
    HUB_UPDATE_STAGE_ROLLING_BACK,
    HUB_UPDATE_STATE_NAME,
    HUB_UPDATE_UNIT,
    HUB_UPDATE_UNIT_ENVIRONMENT,
    HUB_UPDATE_UNIT_MEMORY_HIGH,
    HUB_UPDATE_UNPACK_MULTIPLE,
)
from neutrino_hub.modules.hub_update.release import (
    HubRelease,
    HubReleaseChecker,
    asset_name,
    version_of_asset,
)
from neutrino_hub.modules.hub_update.state import HubUpdateRecord, HubUpdateStateFile
from neutrino_hub.system.machine import distribution_family
from neutrino_hub.system.systemd_ctl import unit_state
from neutrino_hub.utils import constants
from neutrino_hub.utils.subprocess_run import run

DOWNLOAD_CHUNK_BYTES = 1024 * 1024
PROGRESS_STEPS = 10
UNIT_ACTIVE_STATES = ("active", "activating")
PACKAGE_SUFFIXES = (".deb", ".rpm", ".zst", ".xz")
# The exact digest of a file already on disk decides whether it downloads
# again; a file with no digest to check against is fetched again.
DIGEST_CHUNK_BYTES = 1024 * 1024

# What each family runs to install a package file, and to put the previous
# one back. `--reinstall` makes a same-version file go through its maintainer
# scripts, `--allow-downgrades` lets the rollback take the same line, and the
# lock timeout waits out an unattended upgrade holding dpkg. `$PACE` is the
# script's own: it puts the package manager below every other process for
# the disk and the processor, because a package unpacking on a slow card
# has held PID 1 past its hardware watchdog.
INSTALL_COMMANDS = {
    "debian": (
        "$PACE apt-get install -y --reinstall --allow-downgrades "
        "-o DPkg::Lock::Timeout=@LOCK@ @PATH@",
        "$PACE apt-get install -y --reinstall --allow-downgrades "
        "-o DPkg::Lock::Timeout=@LOCK@ @PATH@",
    ),
    "rhel": (
        "$PACE dnf reinstall -y @PATH@ || $PACE dnf install -y @PATH@",
        "$PACE rpm -Uvh --oldpackage @PATH@",
    ),
    "arch": (
        "$PACE pacman -U --noconfirm @PATH@",
        "$PACE pacman -U --noconfirm @PATH@",
    ),
}

SCRIPT = """#!/bin/sh
# Written by neutrino_hub.modules.hub_update; runs as the transient unit
# @UNIT@. Do not edit.
umask 022
STATE=@STATE@
LOG=@LOG@
FROM=@FROM@
TO=@TO@
PACKAGE=@PACKAGE@
ROLLBACK=@ROLLBACK@
PORT=@PORT@
HEALTH_PATH=@HEALTH_PATH@
UNITS=@UNITS@
STARTED=@STARTED@
GATE_TIMEOUT=@GATE_TIMEOUT@
POLL=@POLL@
PACE='nice -n 10'
command -v ionice >/dev/null 2>&1 && PACE="ionice -c 2 -n 7 $PACE"

write_state() {
    finished=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    {
        printf '{"stage": "%s", "from_version": "%s", "to_version": "%s", "started_at": "%s", "finished_at": "%s", "reason": "%s", "output": "' \\
            "$1" "$FROM" "$TO" "$STARTED" "$finished" "$2"
        tail -c @OUTPUT_LIMIT@ "$LOG" | tr '\\t' ' ' | tr -d '\\000-\\010\\013-\\037' \\
            | sed -e 's/\\\\/\\\\\\\\/g' -e 's/"/\\\\"/g' -e 's/$/\\\\n/' | tr -d '\\n'
        printf '"}\\n'
    } > "$STATE.tmp"
    chmod 600 "$STATE.tmp"
    mv -f "$STATE.tmp" "$STATE"
}

gate() {
    deadline=$(( $(date +%s) + GATE_TIMEOUT ))
    while [ "$(date +%s)" -lt "$deadline" ]; do
        ok=1
        report=''
        for unit in $UNITS; do
            systemctl is-active --quiet "$unit" \\
                || { ok=0; report="$report $unit=$(systemctl is-active "$unit")"; }
        done
        curl -fsS -m 5 -o /dev/null "http://127.0.0.1:$PORT$HEALTH_PATH" \\
            || { ok=0; report="$report http=failed"; }
        seen=$(nhub --version 2>/dev/null)
        [ "$seen" = "$1" ] || { ok=0; report="$report version=$seen"; }
        [ "$ok" = 1 ] && return 0
        sleep "$POLL"
    done
    echo "gate: timed out after ${GATE_TIMEOUT}s:$report" >> "$LOG"
    return 1
}

: > "$LOG"
sync
if ( @INSTALL@ ) >> "$LOG" 2>&1; then
    if gate "$TO"; then
        write_state @STAGE_INSTALLED@ ''
        exit 0
    fi
    reason=@REASON_GATE_FAILED@
else
    reason=@REASON_INSTALL_FAILED@
fi
if [ -z "$ROLLBACK" ]; then
    write_state @STAGE_FAILED@ "$reason"
    exit 1
fi
write_state @STAGE_ROLLING_BACK@ "$reason"
if ( @ROLLBACK_INSTALL@ ) >> "$LOG" 2>&1 && gate "$FROM"; then
    write_state @STAGE_ROLLED_BACK@ "$reason"
    exit 1
fi
write_state @STAGE_FAILED@ "$reason"
exit 1
"""


@dataclass(frozen=True)
class HubUpdatePlan:
    """Everything the install unit is told.

    Attributes:
        from_version: The version running now.
        to_version: The version the package installs.
        package: The package file, digest checked, under the update directory.
        rollback: The running version's own package beside it, or None when
            no release carries one.
        family: The distribution family, which names the package manager.
        port: The panel's port, which the gate probes.
        units: The units the gate holds for: the panel, and those of the
            router's that were running when the plan was made.
        started_at: When the update started, as an ISO stamp.
    """

    from_version: str
    to_version: str
    package: Path
    rollback: Path | None
    family: str
    port: int
    units: tuple[str, ...]
    started_at: str


def space_needed(
    asset_size: int,
    *,
    is_rollback_fetched: bool,
    state_root: Path | None = None,
    static_root: Path | None = None,
) -> dict[Path, int]:
    """How many bytes each root must have free for an update.

    Args:
        asset_size: The package's size.
        is_rollback_fetched: Whether the rollback package has to come down
            too.
        state_root: Where packages land; None is the hub's.
        static_root: Where the package unpacks; None is the hub's.

    Returns:
        Bytes needed by root; the two roots merged into one entry when they
        are on the same filesystem.
    """
    state = state_root or constants.UTILS_STATE_ROOT
    static = static_root or constants.UTILS_STATIC_ROOT
    packages = asset_size * (2 if is_rollback_fetched else 1)
    unpacked = asset_size * HUB_UPDATE_UNPACK_MULTIPLE
    if _device_of(state) == _device_of(static):
        return {state: packages + unpacked}
    return {state: packages, static: unpacked}


def check_space(
    asset_size: int,
    *,
    is_rollback_fetched: bool,
    disk_usage: Callable[[Path], "shutil._ntuple_diskusage"] = shutil.disk_usage,
) -> None:
    """Refuse an update the disk has no room for.

    Args:
        asset_size: The package's size.
        is_rollback_fetched: Whether the rollback package has to come down
            too.
        disk_usage: How a root's usage is read.

    Raises:
        HubUpdateError: ``disk_space_short``, naming the root, what it needs and
            what it has.
    """
    for root, needed in space_needed(
        asset_size, is_rollback_fetched=is_rollback_fetched
    ).items():
        free = disk_usage(_existing_parent(root)).free
        if free < needed:
            raise HubUpdateError(
                HUB_UPDATE_REASON_SPACE_SHORT,
                path=str(root),
                needed_bytes=needed,
                free_bytes=free,
            )


def free_bytes(
    asset_size: int,
    *,
    is_rollback_fetched: bool,
    disk_usage: Callable[[Path], "shutil._ntuple_diskusage"] = shutil.disk_usage,
) -> tuple[int, int]:
    """What an update needs and what the tightest root has, for showing.

    Args:
        asset_size: The package's size.
        is_rollback_fetched: Whether the rollback package has to come down
            too.
        disk_usage: How a root's usage is read.

    Returns:
        ``(needed, free)`` for the root with the least room to spare.
    """
    tightest = None
    for root, needed in space_needed(
        asset_size, is_rollback_fetched=is_rollback_fetched
    ).items():
        free = disk_usage(_existing_parent(root)).free
        if tightest is None or free - needed < tightest[1] - tightest[0]:
            tightest = (needed, free)
    return tightest or (0, 0)


def install_commands(family: str, path: Path) -> tuple[str, str]:
    """What installs a package file on this family, and what puts one back.

    Args:
        family: The distribution family.
        path: The package file.

    Returns:
        The install command line, and the rollback's.

    Raises:
        ValueError: If no package manager is known for the family.
    """
    if family not in INSTALL_COMMANDS:
        raise ValueError(f"no package manager is known for {family}")
    quoted = shlex.quote(str(path))
    lock = str(HUB_UPDATE_LOCK_TIMEOUT_S)
    return tuple(
        line.replace("@PATH@", quoted).replace("@LOCK@", lock)
        for line in INSTALL_COMMANDS[family]
    )


def render_script(
    plan: HubUpdatePlan,
    *,
    directory: Path,
    gate_timeout_s: int = HUB_UPDATE_GATE_TIMEOUT_S,
    poll_s: float = HUB_UPDATE_GATE_POLL_S,
    output_limit_bytes: int = HUB_UPDATE_OUTPUT_LIMIT_BYTES,
) -> str:
    """The shell the transient unit runs. Pure.

    Args:
        plan: What to install and what to hold for.
        directory: Where the state file and the log are written.
        gate_timeout_s: How long the gate holds before it gives up.
        poll_s: How often the gate looks.
        output_limit_bytes: How much of the log's tail the state file keeps.

    Returns:
        The script's text.

    Raises:
        ValueError: If no package manager is known for the plan's family.
    """
    install, _ = install_commands(plan.family, plan.package)
    rollback_install = ""
    if plan.rollback is not None:
        _, rollback_install = install_commands(plan.family, plan.rollback)
    values = {
        "@UNIT@": HUB_UPDATE_UNIT,
        "@STATE@": shlex.quote(str(directory / HUB_UPDATE_STATE_NAME)),
        "@LOG@": shlex.quote(str(directory / HUB_UPDATE_LOG_NAME)),
        "@FROM@": shlex.quote(plan.from_version),
        "@TO@": shlex.quote(plan.to_version),
        "@PACKAGE@": shlex.quote(str(plan.package)),
        "@ROLLBACK@": shlex.quote(str(plan.rollback) if plan.rollback else ""),
        "@PORT@": shlex.quote(str(plan.port)),
        "@UNITS@": shlex.quote(" ".join(plan.units)),
        "@STARTED@": shlex.quote(plan.started_at),
        "@GATE_TIMEOUT@": str(int(gate_timeout_s)),
        "@POLL@": str(poll_s),
        "@OUTPUT_LIMIT@": str(int(output_limit_bytes)),
        "@HEALTH_PATH@": shlex.quote(HUB_UPDATE_HEALTH_PATH),
        "@INSTALL@": install,
        "@ROLLBACK_INSTALL@": rollback_install or "false",
        "@STAGE_INSTALLED@": HUB_UPDATE_STAGE_INSTALLED,
        "@STAGE_ROLLING_BACK@": HUB_UPDATE_STAGE_ROLLING_BACK,
        "@STAGE_ROLLED_BACK@": HUB_UPDATE_STAGE_ROLLED_BACK,
        "@STAGE_FAILED@": HUB_UPDATE_STAGE_FAILED,
        "@REASON_GATE_FAILED@": HUB_UPDATE_REASON_GATE_FAILED,
        "@REASON_INSTALL_FAILED@": HUB_UPDATE_REASON_INSTALL_FAILED,
    }
    text = SCRIPT
    for token, value in values.items():
        text = text.replace(token, value)
    return text


class HubUpdateInstaller:
    """Stages one update and hands it to the install unit."""

    def __init__(
        self,
        *,
        checker: HubReleaseChecker,
        state: HubUpdateStateFile,
        directory: Path | None = None,
        asset: str = HUB_PACKAGE_ASSET,
        family: str | None = None,
        open_url: Callable[[str], object] | None = None,
        run_command: Callable[..., object] = run,
        unit_state_of: Callable[[str], str] = unit_state,
        disk_usage: Callable[[Path], "shutil._ntuple_diskusage"] = shutil.disk_usage,
    ):
        """Set up an installer.

        Args:
            checker: What reads the releases.
            state: The state file both sides write.
            directory: Where packages, the script and the log live; None is
                the update directory under the state root, resolved at each
                call.
            asset: The name the build stamped, with ``{version}`` open.
            family: The distribution family; None reads the machine's.
            open_url: How a download is opened, answering a stream with a
                ``read(size)``; None opens it over the network.
            run_command: How the unit is started.
            unit_state_of: How a unit's state is read.
            disk_usage: How a root's usage is read.
        """
        self._checker = checker
        self._state = state
        self._directory = directory
        self._asset = asset
        self._family = family
        self._open_url = _open_url if open_url is None else open_url
        self._run = run_command
        self._unit_state = unit_state_of
        self._disk_usage = disk_usage

    @property
    def checker(self) -> HubReleaseChecker:
        """What reads the releases."""
        return self._checker

    @property
    def state(self) -> HubUpdateStateFile:
        """The state file both sides write."""
        return self._state

    @property
    def directory(self) -> Path:
        """Where packages, the script and the log live now."""
        return self._directory or constants.UTILS_STATE_ROOT / HUB_UPDATE_DIR_NAME

    def is_unit_active(self) -> bool:
        """Whether the install unit is running now.

        Returns:
            True while systemd reports it active or activating.
        """
        return self._unit_state(HUB_UPDATE_UNIT) in UNIT_ACTIVE_STATES

    def is_rollback_available(self, current: str) -> bool:
        """Whether the running version's package can be at hand.

        Args:
            current: The version running.

        Returns:
            True when its package is already in the directory, or a release
            of that version carries it.

        Raises:
            OSError: If GitHub had to be asked and could not be reached.
            ValueError: If the release read is not shaped like one, or this
                hub carries no stamp.
        """
        if self._rollback_path(current).is_file():
            return True
        return self._checker.for_version(current) is not None

    def is_rollback_present(self, current: str) -> bool:
        """Whether the running version's package is in the directory.

        Args:
            current: The version running.

        Returns:
            True when it is there, so no download would be needed.
        """
        try:
            return self._rollback_path(current).is_file()
        except ValueError:
            return False

    def prepare(
        self,
        release: HubRelease,
        *,
        current: str,
        port: int,
        on_progress: Callable[[str], None] | None = None,
    ) -> HubUpdatePlan:
        """Stage a release: room, the package, its digest, the rollback.

        Args:
            release: What to install.
            current: The version running.
            port: The panel's port, for the gate.
            on_progress: Told one line per step taken, when given.

        Returns:
            The plan the unit is handed.

        Raises:
            HubUpdateError: ``disk_space_short``, ``package_fetch_failed``,
                ``package_sha256_mismatch`` or ``rollback_fetch_failed``;
                nothing half-written remains.
        """
        say = on_progress or (lambda line: None)
        directory = self._ready_directory()
        rollback_name = asset_name(current, asset=self._asset)
        is_rollback_fetched = not (directory / rollback_name).is_file()
        check_space(
            release.asset_size,
            is_rollback_fetched=is_rollback_fetched,
            disk_usage=self._disk_usage,
        )
        self._prune(keep={release.asset_name, rollback_name})
        target = directory / release.asset_name
        try:
            digest = self._checker.digest_of(release)
        except (OSError, ValueError) as error:
            raise HubUpdateError(
                HUB_UPDATE_REASON_PACKAGE_FETCH_FAILED, detail=str(error)[:200]
            ) from error
        if target.is_file() and _file_digest(target) == digest:
            say(f"{release.asset_name} is already here and matches its digest")
        else:
            say(
                f"downloading {release.asset_name} ({_megabytes(release.asset_size)} MB)"
            )
            received = self._download(
                release.asset_url, target, total=release.asset_size, say=say
            )
            if received != digest:
                target.unlink(missing_ok=True)
                raise HubUpdateError(
                    HUB_UPDATE_REASON_PACKAGE_SHA256_MISMATCH, name=release.asset_name
                )
            say("the package matches its published digest")
        rollback = self._ensure_rollback(current, say=say)
        return HubUpdatePlan(
            from_version=current,
            to_version=release.version,
            package=target,
            rollback=rollback,
            family=self._family or distribution_family(),
            port=port,
            units=self._gate_units(),
            started_at=_now(),
        )

    def plan_for_file(
        self,
        package: Path,
        *,
        current: str,
        port: int,
        on_progress: Callable[[str], None] | None = None,
    ) -> HubUpdatePlan:
        """Stage a package file somebody brought, its version read off its name.

        Args:
            package: The file.
            current: The version running.
            port: The panel's port, for the gate.
            on_progress: Told one line per step taken, when given.

        Returns:
            The plan the unit is handed.

        Raises:
            ValueError: If the file is not this box's package at any version.
            HubUpdateError: ``disk_space_short``, ``package_fetch_failed`` when
                the file cannot be read, or ``rollback_fetch_failed``.
        """
        say = on_progress or (lambda line: None)
        version = version_of_asset(package.name, asset=self._asset)
        directory = self._ready_directory()
        rollback_name = asset_name(current, asset=self._asset)
        target = directory / package.name
        try:
            size = package.stat().st_size
        except OSError as error:
            raise HubUpdateError(
                HUB_UPDATE_REASON_PACKAGE_FETCH_FAILED, detail=str(error)[:200]
            ) from error
        is_rollback_fetched = (
            rollback_name != package.name and not (directory / rollback_name).is_file()
        )
        check_space(
            size, is_rollback_fetched=is_rollback_fetched, disk_usage=self._disk_usage
        )
        self._prune(keep={package.name, rollback_name})
        if package.resolve() != target.resolve():
            # Linked where the file is on the same filesystem: a copy is
            # another whole package written to the card just before the
            # unpack writes the next one.
            try:
                target.unlink(missing_ok=True)
                try:
                    os.link(package, target)
                except OSError:
                    shutil.copyfile(package, target)
                os.chmod(target, HUB_UPDATE_PACKAGE_MODE)
            except OSError as error:
                target.unlink(missing_ok=True)
                raise HubUpdateError(
                    HUB_UPDATE_REASON_PACKAGE_FETCH_FAILED, detail=str(error)[:200]
                ) from error
        say(f"{package.name} is in place")
        rollback = None
        if rollback_name != package.name:
            rollback = self._ensure_rollback(current, say=say)
        return HubUpdatePlan(
            from_version=current,
            to_version=version,
            package=target,
            rollback=rollback,
            family=self._family or distribution_family(),
            port=port,
            units=self._gate_units(),
            started_at=_now(),
        )

    def launch(self, plan: HubUpdatePlan) -> None:
        """Write the script and start the unit that runs it.

        Args:
            plan: What the unit is told.

        Raises:
            HubUpdateError: ``update_launch_failed`` when systemd would not start
                the unit; the state file says so.
        """
        directory = self._ready_directory()
        script = directory / HUB_UPDATE_SCRIPT_NAME
        script.write_text(render_script(plan, directory=directory), encoding="utf-8")
        os.chmod(script, HUB_UPDATE_SCRIPT_MODE)
        record = HubUpdateRecord(
            stage=HUB_UPDATE_STAGE_INSTALLING,
            from_version=plan.from_version,
            to_version=plan.to_version,
            started_at=plan.started_at,
        )
        self._state.save(record)
        try:
            self._run(
                [
                    "systemd-run",
                    "--unit",
                    HUB_UPDATE_UNIT,
                    "--collect",
                    f"--property=MemoryHigh={HUB_UPDATE_UNIT_MEMORY_HIGH}",
                    *(f"--setenv={pair}" for pair in HUB_UPDATE_UNIT_ENVIRONMENT),
                    "/bin/sh",
                    str(script),
                ],
                timeout_s=HUB_UPDATE_LAUNCH_TIMEOUT_S,
            )
        except (OSError, subprocess.SubprocessError) as error:
            record.stage = HUB_UPDATE_STAGE_FAILED
            record.reason = HUB_UPDATE_REASON_LAUNCH_FAILED
            record.finished_at = _now()
            record.output = str(error)[:200]
            self._state.save(record)
            raise HubUpdateError(
                HUB_UPDATE_REASON_LAUNCH_FAILED, detail=str(error)[:200]
            ) from error

    def _ready_directory(self) -> Path:
        directory = self.directory
        directory.mkdir(parents=True, exist_ok=True)
        os.chmod(directory, HUB_UPDATE_DIR_MODE)
        return directory

    def _rollback_path(self, current: str) -> Path:
        return self.directory / asset_name(current, asset=self._asset)

    def _prune(self, *, keep: set[str]) -> None:
        """Drop every package but the ones named, and an earlier run's files."""
        for entry in self.directory.iterdir():
            if entry.name in keep or not entry.is_file():
                continue
            if entry.name in (HUB_UPDATE_SCRIPT_NAME, HUB_UPDATE_LOG_NAME) or (
                entry.suffix in PACKAGE_SUFFIXES or entry.name.startswith(".tmp_")
            ):
                entry.unlink(missing_ok=True)

    def _ensure_rollback(
        self, current: str, *, say: Callable[[str], None]
    ) -> Path | None:
        """The running version's package, fetched when a release carries it.

        Raises:
            HubUpdateError: ``rollback_fetch_failed`` when a release carries
                it and it could not be taken down whole.
        """
        rollback = self._rollback_path(current)
        if rollback.is_file():
            say(f"rollback package {rollback.name} is present")
            return rollback
        try:
            previous = self._checker.for_version(current)
            if previous is None:
                say(f"no release carries {rollback.name}; there is no rollback")
                return None
            digest = self._checker.digest_of(previous)
            say(f"downloading rollback package {previous.asset_name}")
            received = self._download(
                previous.asset_url, rollback, total=previous.asset_size, say=say
            )
        except (OSError, ValueError) as error:
            raise HubUpdateError(
                HUB_UPDATE_REASON_ROLLBACK_FETCH_FAILED, detail=str(error)[:200]
            ) from error
        except HubUpdateError as error:
            raise HubUpdateError(
                HUB_UPDATE_REASON_ROLLBACK_FETCH_FAILED, **error.params
            ) from error
        if received != digest:
            rollback.unlink(missing_ok=True)
            raise HubUpdateError(
                HUB_UPDATE_REASON_ROLLBACK_FETCH_FAILED, name=rollback.name
            )
        say("the rollback package matches its published digest")
        return rollback

    def _gate_units(self) -> tuple[str, ...]:
        running = tuple(
            unit for unit in HUB_UPDATE_GATE_UNITS if self._unit_state(unit) == "active"
        )
        return (HUB_UPDATE_PANEL_UNIT,) + running

    def _download(
        self, url: str, destination: Path, *, total: int, say: Callable[[str], None]
    ) -> str:
        """Take one file down beside its destination, then move it there.

        Returns:
            The sha256 of what arrived.

        Raises:
            HubUpdateError: ``package_fetch_failed``; nothing remains.
        """
        digest = hashlib.sha256()
        received = 0
        next_step = 1
        handle, temporary = tempfile.mkstemp(dir=destination.parent, prefix=".tmp_")
        try:
            with os.fdopen(handle, "wb") as sink, self._open_url(url) as source:
                while True:
                    chunk = source.read(DOWNLOAD_CHUNK_BYTES)
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > HUB_UPDATE_FETCH_LIMIT_BYTES:
                        raise HubUpdateError(
                            HUB_UPDATE_REASON_PACKAGE_FETCH_FAILED,
                            detail=f"past {HUB_UPDATE_FETCH_LIMIT_BYTES} bytes",
                        )
                    sink.write(chunk)
                    digest.update(chunk)
                    while total and received * PROGRESS_STEPS >= next_step * total:
                        say(f"{next_step * 100 // PROGRESS_STEPS}%")
                        next_step += 1
                sink.flush()
                os.fsync(sink.fileno())
            os.chmod(temporary, HUB_UPDATE_PACKAGE_MODE)
            os.replace(temporary, destination)
        except OSError as error:
            Path(temporary).unlink(missing_ok=True)
            raise HubUpdateError(
                HUB_UPDATE_REASON_PACKAGE_FETCH_FAILED, detail=str(error)[:200]
            ) from error
        except HubUpdateError:
            Path(temporary).unlink(missing_ok=True)
            raise
        return digest.hexdigest()


def _open_url(url: str):
    """Open one download over the network.

    Args:
        url: What to read.

    Returns:
        The response, read in chunks and closed by the caller.

    Raises:
        OSError: If it cannot be reached.
    """
    request = urllib.request.Request(url, headers=HUB_UPDATE_HEADERS)
    return urllib.request.urlopen(request, timeout=HUB_UPDATE_FETCH_TIMEOUT_S)


def _file_digest(path: Path) -> str:
    """The sha256 of a file on disk, empty when it cannot be read."""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            while True:
                chunk = source.read(DIGEST_CHUNK_BYTES)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


def _device_of(path: Path) -> int:
    """The filesystem a path is on, read from its nearest existing parent."""
    return _existing_parent(path).stat().st_dev


def _existing_parent(path: Path) -> Path:
    """The path itself, or the nearest ancestor that exists."""
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def _megabytes(size: int) -> int:
    return size // (1024 * 1024)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
