"""Install the newest release of the hub, or a package file, on this box.

    sudo nhub update [--yes] [--package <file>]

The same staging and the same install unit the panel uses: the package is
downloaded and checked, the running version's own package is kept beside it
as the rollback, and systemd installs it outside this process, holding a
health gate and putting the previous version back when the new one does not
answer. This command waits for the unit's record and prints how it ended.
"""

import argparse
import sys
import time
from pathlib import Path

from neutrino_hub import HUB_VERSION
from neutrino_hub.exceptions import HubUpdateError
from neutrino_hub.modules.hub_update.constants import (
    HUB_UPDATE_RELATION_CURRENT,
    HUB_UPDATE_RELATION_MAJOR,
    HUB_UPDATE_STAGE_INSTALLED,
    HUB_UPDATE_STAGES_SETTLED,
    HUB_UPDATE_UNIT,
)
from neutrino_hub.modules.hub_update.installer import (
    HubUpdateInstaller,
    check_space,
    free_bytes,
)
from neutrino_hub.modules.hub_update.release import (
    HubRelease,
    HubReleaseChecker,
    relation,
)
from neutrino_hub.modules.hub_update.state import HubUpdateStateFile
from neutrino_hub.system.installation import is_packaged
from neutrino_hub.utils.json_file import read_config
from neutrino_hub.web.constants import WEB_DEFAULT_LISTEN_PORT

# --- config ---
UPDATE_NOTES_LINES = 20
# The unit installs, holds a gate of three minutes, and may do both again for
# the rollback; the wait outlasts that.
UPDATE_WAIT_TIMEOUT_S = 15 * 60
UPDATE_WAIT_POLL_S = 2
PANEL_SETTINGS_FILE = "web/settings.json"
# Exit statuses: 0 done or nothing to do, 1 refused by the person or failed,
# 2 cannot be done from here.
STATUS_DONE = 0
STATUS_FAILED = 1
STATUS_CANNOT = 2


def main() -> int:
    """Check, ask, stage, hand over, and wait.

    Returns:
        Process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--yes", action="store_true", help="install without asking first"
    )
    parser.add_argument(
        "--package",
        type=Path,
        default=None,
        help="install this package file instead of the newest release",
    )
    arguments = parser.parse_args()
    return update(is_confirmed=arguments.yes, package=arguments.package)


def update(*, is_confirmed: bool, package: "Path | None") -> int:
    """The command's work, with its answers on standard output.

    Args:
        is_confirmed: Whether to install without asking.
        package: A package file to install instead of the newest release.

    Returns:
        Process exit status.
    """
    if not is_packaged():
        print("this hub runs from a checkout; update it with git", file=sys.stderr)
        return STATUS_CANNOT
    installer = _installer()
    if installer.is_unit_active():
        print("an update is already under way", file=sys.stderr)
        return STATUS_FAILED
    port = _configured_port()
    try:
        if package is None:
            status, plan = _plan_from_release(
                installer, is_confirmed=is_confirmed, port=port
            )
        else:
            status, plan = _plan_from_file(
                installer, package, is_confirmed=is_confirmed, port=port
            )
    except HubUpdateError as error:
        print(f"error: {_worded(error)}", file=sys.stderr)
        return STATUS_FAILED
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return STATUS_FAILED
    if plan is None:
        return status
    try:
        installer.launch(plan)
    except HubUpdateError as error:
        print(f"error: {_worded(error)}", file=sys.stderr)
        return STATUS_FAILED
    print(f"handed to systemd as {HUB_UPDATE_UNIT}; the panel restarts now")
    return _wait(installer.state)


def _plan_from_release(installer: HubUpdateInstaller, *, is_confirmed: bool, port: int):
    """Read the newest release, say how it stands, ask, and stage it.

    Returns:
        The exit status and the plan; no plan means the status is the answer:
        done when there is nothing to do, failed when the person declined,
        cannot when a major is ahead.

    Raises:
        HubUpdateError: When the staging fails.
        OSError: When GitHub cannot be reached.
        ValueError: When a reply is not a release with this box's package.
    """
    found = installer.checker.latest()
    if found is None:
        print("nothing has been published yet")
        return STATUS_DONE, None
    standing = relation(HUB_VERSION, found.version)
    print(f"running {HUB_VERSION}; newest release {found.version}")
    if standing == HUB_UPDATE_RELATION_CURRENT:
        print("already on the newest release")
        return STATUS_DONE, None
    _print_release(found)
    if standing == HUB_UPDATE_RELATION_MAJOR:
        print(
            f"{found.version} is a new major version; a major changes the shape "
            "of the configuration, so the upgrade guide carries the box across "
            "by hand",
            file=sys.stderr,
        )
        return STATUS_CANNOT, None
    is_rollback_fetched = not installer.is_rollback_present(HUB_VERSION)
    needed, free = free_bytes(found.asset_size, is_rollback_fetched=is_rollback_fetched)
    print(f"needs {_megabytes(needed)} MB free; {_megabytes(free)} MB are")
    check_space(found.asset_size, is_rollback_fetched=is_rollback_fetched)
    if not installer.is_rollback_available(HUB_VERSION):
        print(
            f"no release carries the package of {HUB_VERSION}: nothing can be put "
            f"back if {found.version} does not come up"
        )
    if not is_confirmed and not _asked(f"install {found.version} over {HUB_VERSION}?"):
        return STATUS_FAILED, None
    plan = installer.prepare(found, current=HUB_VERSION, port=port, on_progress=print)
    return STATUS_DONE, plan


def _plan_from_file(
    installer: HubUpdateInstaller, package: Path, *, is_confirmed: bool, port: int
):
    """Ask about a package file somebody brought, and stage it.

    Returns:
        The exit status and the plan; no plan means the person declined.

    Raises:
        HubUpdateError: When the staging fails.
        ValueError: When the file is not this box's package.
    """
    if not package.is_file():
        raise ValueError(f"{package} is not a file")
    if not is_confirmed and not _asked(f"install {package.name} over {HUB_VERSION}?"):
        return STATUS_FAILED, None
    plan = installer.plan_for_file(
        package, current=HUB_VERSION, port=port, on_progress=print
    )
    return STATUS_DONE, plan


def _wait(state: HubUpdateStateFile) -> int:
    """Follow the unit's record until it settles.

    Args:
        state: The record the unit writes.

    Returns:
        0 when the new version is installed, 1 otherwise.
    """
    deadline = time.monotonic() + UPDATE_WAIT_TIMEOUT_S
    try:
        while time.monotonic() < deadline:
            record = state.load()
            if record is not None and record.stage in HUB_UPDATE_STAGES_SETTLED:
                break
            time.sleep(UPDATE_WAIT_POLL_S)
        else:
            print(
                f"still not settled; follow it with: journalctl -u {HUB_UPDATE_UNIT}",
                file=sys.stderr,
            )
            return STATUS_FAILED
    except KeyboardInterrupt:
        print(
            f"\nthe install goes on without this terminal; follow it with: "
            f"journalctl -u {HUB_UPDATE_UNIT}",
            file=sys.stderr,
        )
        return STATUS_FAILED
    if record.stage == HUB_UPDATE_STAGE_INSTALLED:
        print(f"installed {record.to_version} over {record.from_version}")
        return STATUS_DONE
    print(
        f"{record.stage}: {record.to_version} was given up on ({record.reason})",
        file=sys.stderr,
    )
    if record.output.strip():
        print(record.output.rstrip(), file=sys.stderr)
    return STATUS_FAILED


def _print_release(found: HubRelease) -> None:
    """The release as a person reads it: when, how big, what it says."""
    print(f"published {found.published_at}; {_megabytes(found.asset_size)} MB")
    if found.page_url:
        print(found.page_url)
    lines = found.notes.strip().splitlines()
    if lines:
        print()
        for line in lines[:UPDATE_NOTES_LINES]:
            print(f"  {line}")
        if len(lines) > UPDATE_NOTES_LINES:
            print("  …")
        print()


def _asked(question: str) -> bool:
    """One yes-or-no question on the terminal."""
    answer = input(f"{question} [y/N] ").strip().lower()
    return answer in ("y", "yes")


def _worded(error: HubUpdateError) -> str:
    """The reason and its details, for the terminal."""
    if not error.params:
        return error.code
    details = ", ".join(f"{key}={value}" for key, value in error.params.items())
    return f"{error.code} ({details})"


def _installer() -> HubUpdateInstaller:
    """The installer this command uses; a test replaces this."""
    return HubUpdateInstaller(checker=HubReleaseChecker(), state=HubUpdateStateFile())


def _configured_port() -> int:
    """The port the panel listens on, from the settings or the default."""
    try:
        return int(
            read_config(PANEL_SETTINGS_FILE).get("listen_port", WEB_DEFAULT_LISTEN_PORT)
        )
    except (FileNotFoundError, ValueError):
        return WEB_DEFAULT_LISTEN_PORT


def _megabytes(size: int) -> int:
    return size // (1024 * 1024)


if __name__ == "__main__":
    sys.exit(main())
