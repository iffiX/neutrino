"""Updating this agent to the hub's own release.

The hub and the agent share a version, so an agent whose heartbeat reply
names a later ``hub_version`` pulls the hub's baked package over the pinned
channel and installs it. The install runs in a transient systemd unit:
installing the package restarts ``neutrino_agent.service``, which kills the
process that asked for the update, so the process must not be the one
running it.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile

from neutrino_agent.constants import (
    AGENT_PACKAGE_PATH,
    AGENT_UPDATE_LAUNCH_TIMEOUT_S,
    AGENT_UPDATE_UNIT,
)

FAMILY_TO_PACKAGE_KIND = {"debian": "deb", "rhel": "rpm"}


class SelfUpdateError(RuntimeError):
    """Raised when the update cannot be fetched, verified, or launched."""


def package_kind(platform: dict) -> str:
    """The hub package kind this machine installs.

    Args:
        platform: The tuple from ``platforms.detect.platform_tuple``.

    Returns:
        ``deb`` or ``rpm``, or empty when the hub bakes nothing for this
        platform.
    """
    return FAMILY_TO_PACKAGE_KIND.get(platform.get("family", ""), "")


def install_command(kind: str, path: str) -> list:
    """The detached command that installs a downloaded package. Pure.

    Args:
        kind: ``deb`` or ``rpm``.
        path: The downloaded package file.

    Returns:
        A ``systemd-run`` argument vector for a transient unit.
    """
    if kind == "deb":
        # dpkg installs a same-version file where apt would call it already
        # newest, and the wire-stale path reinstalls exactly that; apt then
        # settles anything dpkg named as missing.
        script = f"dpkg -i {path} || (apt-get -f install -y && dpkg -i {path})"
        install = [
            "--setenv=DEBIAN_FRONTEND=noninteractive",
            "sh",
            "-c",
            script,
        ]
    else:
        manager = "dnf" if shutil.which("dnf") else "yum"
        install = [
            "sh",
            "-c",
            f"{manager} reinstall -y {path} || {manager} install -y {path}",
        ]
    return ["systemd-run", "--unit", AGENT_UPDATE_UNIT, "--collect"] + install


def run_update(channel, *, kind: str) -> None:
    """Fetch the hub's package over the pinned channel and install it detached.

    Args:
        channel: The gateway channel the heartbeats use.
        kind: ``deb`` or ``rpm``.

    Raises:
        SelfUpdateError: When the digest does not match or the install cannot
            be launched; the message names the failure code.
        GatewayRefused: When the gateway rejected this machine's token.
        GatewayUnreachable: When the package cannot be fetched.
        GatewayUntrusted: When what answers is not the pinned hub.
    """
    handle, path = tempfile.mkstemp(prefix="neutrino_agent_update_", suffix=f".{kind}")
    os.close(handle)
    try:
        named = channel.post_download(AGENT_PACKAGE_PATH, {"family": kind}, path)
        if not named or named != _sha256(path):
            raise SelfUpdateError("agent_package_digest_mismatch")
    except Exception:
        os.unlink(path)
        raise
    try:
        subprocess.run(
            install_command(kind, path),
            capture_output=True,
            timeout=AGENT_UPDATE_LAUNCH_TIMEOUT_S,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as error:
        os.unlink(path)
        raise SelfUpdateError("agent_update_launch_failed") from error


def _sha256(path: str) -> str:
    """The SHA-256 hex digest of a file.

    Args:
        path: The file to digest.

    Returns:
        The digest.
    """
    with open(path, "rb") as stream:
        return hashlib.sha256(stream.read()).hexdigest()
