"""Installing a downloaded package, the way this machine installs things.

One function per package kind, each doing what the machine's own tooling
does unattended: dpkg with an apt fix-up on Debian family, dnf or yum on
RHEL family.

Not pure: runs installers.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
import shutil
import subprocess

from neutrino_agent.constants import AGENT_MODULE_OUTPUT_LIMIT_BYTES
from neutrino_agent.exceptions import InstallError

INSTALL_TIMEOUT_S = 1800
COMMAND_TIMEOUT_S = 120


def install_package(path: str, *, package_kind: str, entry: dict) -> None:
    """Install one downloaded package.

    Args:
        path: The downloaded file.
        package_kind: ``deb`` or ``rpm``.
        entry: The manifest's platform entry.

    Raises:
        InstallError: If the installer fails or the kind is unknown.
    """
    if package_kind == "deb":
        _install_deb(path)
    elif package_kind == "rpm":
        _install_rpm(path)
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


def run_shell(command: str, *, timeout_s: int = INSTALL_TIMEOUT_S) -> str:
    """Run one shell step a manifest names, raising with its output on failure.

    Args:
        command: The shell command.
        timeout_s: How long to wait.

    Returns:
        Standard output.

    Raises:
        InstallError: If the step fails or times out.
    """
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=_apt_env(),
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise InstallError(f"step could not run: {error}")
    if result.returncode != 0:
        output = (result.stderr or result.stdout or "").strip()
        raise InstallError(f"step failed: {output[-AGENT_MODULE_OUTPUT_LIMIT_BYTES:]}")
    return result.stdout or ""


def uninstall_package(command: str) -> None:
    """Remove a package the way its manifest says to.

    Every platform removes things differently — apt, dnf, an uninstaller the
    vendor left behind, or deleting an app bundle — so the manifest carries
    the command rather than this guessing from the package kind.

    Args:
        command: The manifest's uninstall command for this platform.

    Raises:
        InstallError: If the uninstall fails.
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
        raise InstallError(f"uninstall could not run: {error}")
    if result.returncode != 0:
        output = (result.stderr or result.stdout or "").strip()
        raise InstallError(
            f"uninstall failed: {output[-AGENT_MODULE_OUTPUT_LIMIT_BYTES:]}"
        )


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
