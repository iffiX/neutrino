"""Installing and removing the cc-switch command line as a module.

The hub's cache resolves the release for this platform and fetches it once
for every machine like this one; this unpacks the one binary an order handed
down and puts it where the agent keeps it. Detection and activation — where
the binary is, which accounts point at the hub — stay in
``services/switcher.py``, because what cc-switch does with accounts is a
service decision and what is on the machine is a module one.

Not pure: writes under the install directory.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
import shutil
import tarfile
import tempfile
import zipfile

from neutrino_agent.modules.base import ModuleRunner
from neutrino_agent.modules.installers import InstallError

# Where the agent puts the CLI, per platform: a real directory on PATH's
# reach, never the POSIX ``/usr/local/bin`` on Windows, which lands off any
# search path there.
if os.name == "nt":
    SWITCHER_INSTALL_DIR = os.path.join(
        os.environ.get("ProgramData", "C:\\ProgramData"), "Neutrino", "bin"
    )
else:
    SWITCHER_INSTALL_DIR = "/usr/local/bin"

# Where a usable CLI may sit: the agent's own install directory for either
# name, then the vendor's user-local install.
SWITCHER_CLI_PATHS = (
    os.path.join(SWITCHER_INSTALL_DIR, "cc-switch"),
    os.path.join(SWITCHER_INSTALL_DIR, "cc-switch.exe"),
    os.path.expanduser("~/.local/bin/cc-switch"),
)

# What the desktop app leaves behind, per platform. Present means installed;
# none of these is executed.
SWITCHER_DESKTOP_MARKERS = (
    "/usr/lib/cc-switch",
    "/opt/cc-switch",
    "/Applications/CC Switch.app",
    "C:\\Program Files\\CC Switch",
)


def install_cli(entry: dict, archive: str) -> str:
    """Install the cc-switch CLI from an archive the hub handed down.

    Nothing is fetched here. The hub's cache resolved the release for this
    platform and fetched it once for every machine like this one, which is
    what leaves this package with no way to reach the internet at all.

    Args:
        entry: The release block the hub resolved — what the binary inside
            is called, and what kind of archive it arrived in.
        archive: The archive on local disk.

    Returns:
        The path it was installed to.

    Raises:
        InstallError: If the archive cannot be unpacked, or no build exists
            for this machine.
    """
    if not entry:
        raise InstallError("no cc-switch build for this machine")
    binary_name = entry.get("binary", "cc-switch")
    kind = entry.get("package_kind", "tar_binary")
    destination = os.path.join(SWITCHER_INSTALL_DIR, binary_name)

    with tempfile.TemporaryDirectory() as workdir:
        extracted = _extract_binary(archive, workdir, binary_name, kind)
        os.makedirs(SWITCHER_INSTALL_DIR, exist_ok=True)
        shutil.move(extracted, destination)
    os.chmod(destination, 0o755)
    return destination


def uninstall_cli() -> None:
    """Remove the CLI the agent installed, leaving the desktop app alone.

    Raises:
        InstallError: If the file is there and cannot be removed.
    """
    for candidate in SWITCHER_CLI_PATHS:
        if os.path.isfile(candidate):
            try:
                os.unlink(candidate)
            except OSError as error:
                raise InstallError(f"could not remove {candidate}: {error}")


def _extract_binary(archive: str, workdir: str, binary_name: str, kind: str) -> str:
    """Pull the one binary out of a release archive.

    Args:
        archive: The downloaded file.
        workdir: Where to unpack.
        binary_name: What the binary is called inside.
        kind: ``tar_binary`` or ``zip_binary``.

    Returns:
        Path to the extracted binary.

    Raises:
        InstallError: If the archive has no such binary.
    """
    target = os.path.join(workdir, "unpacked")
    os.makedirs(target, exist_ok=True)
    try:
        if kind == "zip_binary":
            with zipfile.ZipFile(archive) as bundle:
                bundle.extractall(target)
        else:
            with tarfile.open(archive) as bundle:
                bundle.extractall(target)
    except (OSError, tarfile.TarError, zipfile.BadZipFile) as error:
        raise InstallError(f"could not unpack cc-switch: {error}")

    for root, _, names in os.walk(target):
        if binary_name in names:
            return os.path.join(root, binary_name)
    raise InstallError(f"no {binary_name} inside the archive")


class SwitcherModuleRunner(ModuleRunner):
    """Puts the cc-switch CLI on this machine and takes it off."""

    kind = "switcher"

    def verify(self, resolved: dict) -> bool:
        """Whether the cc-switch CLI is on this machine.

        The CLI, not the desktop app: only the CLI can be driven, so it is
        what the module manages and what the AI service depends on.

        Args:
            resolved: The module as the hub resolved it.

        Returns:
            True when a usable CLI is installed.
        """
        from neutrino_agent.services import switcher

        return switcher.find_cli() is not None

    def install(self, resolved: dict, package_path: str) -> None:
        """Install the CLI from the archive the hub handed down.

        Args:
            resolved: The module as the hub resolved it.
            package_path: The archive on local disk.

        Raises:
            InstallError: If the archive cannot be unpacked.
        """
        install_cli(resolved.get("entry") or {}, package_path)

    def uninstall(self, resolved: dict) -> None:
        """Take the CLI off this machine.

        Args:
            resolved: The module as the hub resolved it.

        Raises:
            InstallError: If the file is there and cannot be removed.
        """
        uninstall_cli()
