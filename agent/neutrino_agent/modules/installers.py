"""Installing a downloaded package, the way each platform installs things.

One function per package kind, each doing what that platform's own tooling
does unattended: dpkg with an apt fix-up on Debian, dnf on RHEL, msiexec
quietly on Windows, the vendor's own silent switch for an exe, and mounting
and copying an app out of a dmg on macOS.

Not pure: runs installers.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile

from neutrino_agent.constants import AGENT_MODULE_OUTPUT_LIMIT_BYTES

INSTALL_TIMEOUT_S = 1800
COMMAND_TIMEOUT_S = 120

MOUNT_POINT_PATTERN = re.compile(r"(/Volumes/[^\n]+)")


class InstallError(RuntimeError):
    """Raised when a package cannot be installed."""


def install_package(path: str, *, package_kind: str, entry: dict) -> None:
    """Install one downloaded package.

    Args:
        path: The downloaded file.
        package_kind: ``deb`` / ``rpm`` / ``msi`` / ``exe`` / ``dmg``.
        entry: The manifest's platform entry, for per-package details like an
            exe's silent switch or the app to copy out of a dmg.

    Raises:
        InstallError: If the installer fails or the kind is unknown.
    """
    if package_kind == "deb":
        _install_deb(path)
    elif package_kind == "rpm":
        _install_rpm(path)
    elif package_kind == "msi":
        _install_msi(path)
    elif package_kind == "exe":
        _install_exe(path, entry.get("install_args", []))
    elif package_kind == "dmg":
        _install_dmg(path, entry.get("app_name", ""))
    else:
        raise InstallError(f"unknown package kind {package_kind!r}")


def run_checked(command: list, *, timeout_s: int = COMMAND_TIMEOUT_S) -> str:
    """Run a command, raising with its output when it fails.

    Args:
        command: Argument vector.
        timeout_s: How long to wait.

    Returns:
        Standard output.

    Raises:
        InstallError: If the command fails or times out.
    """
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout_s
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise InstallError(f"{command[0]} could not run: {error}")
    if result.returncode != 0:
        output = (result.stderr or result.stdout or "").strip()
        raise InstallError(
            f"{command[0]} failed: {output[-AGENT_MODULE_OUTPUT_LIMIT_BYTES:]}"
        )
    return result.stdout or ""


def _apt_env() -> dict:
    env = dict(os.environ)
    env["DEBIAN_FRONTEND"] = "noninteractive"
    return env


def _install_deb(path: str) -> None:
    # dpkg first, then apt to pull in whatever it named as missing: a vendor
    # package usually depends on libraries the machine may not have, and
    # `apt install ./file.deb` refuses relative paths on older releases.
    result = subprocess.run(
        ["dpkg", "-i", path],
        capture_output=True,
        text=True,
        timeout=INSTALL_TIMEOUT_S,
        env=_apt_env(),
    )
    if result.returncode != 0:
        fix = subprocess.run(
            ["apt-get", "-f", "install", "-y"],
            capture_output=True,
            text=True,
            timeout=INSTALL_TIMEOUT_S,
            env=_apt_env(),
        )
        if fix.returncode != 0:
            output = (result.stderr or "") + (fix.stderr or "")
            raise InstallError(
                f"dpkg failed: {output.strip()[-AGENT_MODULE_OUTPUT_LIMIT_BYTES:]}"
            )


def _install_rpm(path: str) -> None:
    manager = "dnf" if shutil.which("dnf") else "yum"
    run_checked([manager, "install", "-y", path], timeout_s=INSTALL_TIMEOUT_S)


def _install_msi(path: str) -> None:
    run_checked(
        ["msiexec", "/i", path, "/quiet", "/norestart"], timeout_s=INSTALL_TIMEOUT_S
    )


def _install_exe(path: str, install_args: list) -> None:
    # Silent switches are the vendor's own, so they come from the manifest;
    # with none given the installer is run bare and may want a click.
    run_checked([path] + list(install_args), timeout_s=INSTALL_TIMEOUT_S)


def _install_dmg(path: str, app_name: str) -> None:
    output = run_checked(
        ["hdiutil", "attach", "-nobrowse", "-readonly", path], timeout_s=600
    )
    match = MOUNT_POINT_PATTERN.search(output)
    if match is None:
        raise InstallError("the disk image mounted nowhere findable")
    mount_point = match.group(1).strip()
    try:
        source = _find_app(mount_point, app_name)
        if source is None:
            raise InstallError(f"no application inside {os.path.basename(path)}")
        destination = os.path.join("/Applications", os.path.basename(source))
        if os.path.exists(destination):
            shutil.rmtree(destination, ignore_errors=True)
        shutil.copytree(source, destination, symlinks=True)
    finally:
        subprocess.run(
            ["hdiutil", "detach", mount_point, "-quiet"],
            capture_output=True,
            timeout=COMMAND_TIMEOUT_S,
        )


def _find_app(mount_point: str, app_name: str) -> "str | None":
    if app_name:
        candidate = os.path.join(mount_point, app_name)
        if os.path.isdir(candidate):
            return candidate
    try:
        for entry in sorted(os.listdir(mount_point)):
            if entry.endswith(".app"):
                return os.path.join(mount_point, entry)
    except OSError:
        return None
    return None


def uninstall_package(command: str) -> None:
    """Remove a package the way its manifest says to.

    Every platform removes things differently — apt, dnf, an uninstaller the
    vendor left behind, or deleting an app bundle — so the manifest carries
    the command rather than this guessing from the package kind.

    Args:
        command: The manifest's removal command for this platform.

    Raises:
        InstallError: If the removal fails.
    """
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=INSTALL_TIMEOUT_S,
            env=_apt_env(),
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise InstallError(f"removal could not run: {error}")
    if result.returncode != 0:
        output = (result.stderr or result.stdout or "").strip()
        raise InstallError(
            f"removal failed: {output[-AGENT_MODULE_OUTPUT_LIMIT_BYTES:]}"
        )
