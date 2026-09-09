"""Updating this agent to the hub's own release.

The hub and the agent share a version, so an agent whose heartbeat reply
names a later ``hub_version`` pulls the hub's baked package over the pinned
channel and installs it. The install runs in a transient systemd unit:
installing the package restarts ``neutrino_agent.service``, which kills the
process that asked for the update, so the process must not be the one
running it. The unit writes what the package manager said and how it
exited beside the agent's state, and the agent that install put on the
machine reads it there and carries it up.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import tempfile

from neutrino_agent.constants import (
    AGENT_PACKAGE_PATH,
    AGENT_REINSTALL_LOG_NAME,
    AGENT_REINSTALL_OUTPUT_LIMIT_BYTES,
    AGENT_REINSTALL_RESULT_NAME,
    AGENT_UPDATE_LAUNCH_TIMEOUT_S,
    AGENT_UPDATE_UNIT,
)

FAMILY_TO_PACKAGE_KIND = {"debian": "deb", "rhel": "rpm"}

# The stamp the unit writes its times with, and the pipeline that turns the
# log's tail into one JSON string: backslashes and quotes escaped, every
# line ended with an escaped newline.
_RESULT_STAMP = "date -u +%Y-%m-%dT%H:%M:%SZ"
_RESULT_ESCAPE = r"""sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/$/\\n/'"""
_RESULT_HEAD = (
    "'"
    '{"package":"%s","kind":"%s","started_at":"%s",'
    '"finished_at":"%s","exit_code":%s,"output":"'
    "'"
)


class SelfUpdateError(RuntimeError):
    """Raised when the update cannot be fetched, verified, or launched."""


def package_kind(platform: dict) -> str:
    """The hub package kind this machine installs.

    Args:
        platform: The tuple from ``platforms.detect.platform_tuple``.

    Returns:
        ``deb`` or ``rpm``, or empty when the hub bakes nothing for this
        machine's family.
    """
    return FAMILY_TO_PACKAGE_KIND.get(platform.get("family", ""), "")


def install_command(kind: str, path: str, *, data_dir: str) -> list:
    """The detached command that installs a downloaded package. Pure.

    Args:
        kind: ``deb`` or ``rpm``.
        path: The downloaded package file.
        data_dir: The agent's data directory, where the unit writes the
            install's log and its result.

    Returns:
        An argument vector that outlives the agent's own restart: a
        ``systemd-run`` transient unit.
    """
    if kind == "deb":
        # dpkg installs a same-version file where apt would call it already
        # newest, and the wire-stale path reinstalls exactly that; apt then
        # settles anything dpkg named as missing.
        install = f"dpkg -i {path} || (apt-get -f install -y && dpkg -i {path})"
        setenv = ["--setenv=DEBIAN_FRONTEND=noninteractive"]
    else:
        manager = "dnf" if shutil.which("dnf") else "yum"
        install = f"{manager} reinstall -y {path} || {manager} install -y {path}"
        setenv = []
    script = _reporting_script(install, kind=kind, path=path, data_dir=data_dir)
    return (
        ["systemd-run", "--unit", AGENT_UPDATE_UNIT, "--collect"]
        + setenv
        + ["sh", "-c", script]
    )


def read_reinstall_result(data_dir: str) -> "dict | None":
    """What the reinstall this agent came from did.

    Args:
        data_dir: The agent's data directory.

    Returns:
        ``{"package", "kind", "started_at", "finished_at", "exit_code",
        "output"}``, or None when no readable result stands there.
    """
    try:
        with open(
            _reinstall_result_path(data_dir), "r", encoding="utf-8", errors="replace"
        ) as stream:
            written = json.load(stream)
    except (OSError, ValueError):
        return None
    if not isinstance(written, dict):
        return None
    try:
        exit_code = int(written.get("exit_code"))
    except (TypeError, ValueError):
        return None
    return {
        "package": str(written.get("package", "") or ""),
        "kind": str(written.get("kind", "") or ""),
        "started_at": str(written.get("started_at", "") or ""),
        "finished_at": str(written.get("finished_at", "") or ""),
        "exit_code": exit_code,
        "output": str(written.get("output", "") or ""),
    }


def clear_reinstall_result(data_dir: str) -> None:
    """Drop what an earlier reinstall left, before a new one starts.

    Args:
        data_dir: The agent's data directory.
    """
    try:
        os.unlink(_reinstall_result_path(data_dir))
    except OSError:
        pass


def run_update(channel, *, kind: str, architecture: str, data_dir: str) -> None:
    """Fetch the hub's package over the pinned channel and install it detached.

    Args:
        channel: The gateway channel the heartbeats use.
        kind: ``deb`` or ``rpm``.
        architecture: This machine's, from the platform tuple. The package
            carries an interpreter, so the hub has one per machine.
        data_dir: The agent's data directory, where the unit writes what
            the install did.

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
        named = channel.post_download(
            AGENT_PACKAGE_PATH, {"family": kind, "architecture": architecture}, path
        )
        if not named or named != _sha256(path):
            raise SelfUpdateError("agent_package_digest_mismatch")
    except Exception:
        os.unlink(path)
        raise
    clear_reinstall_result(data_dir)
    try:
        subprocess.run(
            install_command(kind, path, data_dir=data_dir),
            capture_output=True,
            timeout=AGENT_UPDATE_LAUNCH_TIMEOUT_S,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as error:
        os.unlink(path)
        raise SelfUpdateError("agent_update_launch_failed") from error


def _reinstall_result_path(data_dir: str) -> str:
    """Where the transient unit writes what the install did.

    Args:
        data_dir: The agent's data directory.

    Returns:
        The result file's path.
    """
    return os.path.join(data_dir, AGENT_REINSTALL_RESULT_NAME)


def _reporting_script(install: str, *, kind: str, path: str, data_dir: str) -> str:
    """The shell the transient unit runs: the install, its log, its result.

    Args:
        install: The package manager's own command line.
        kind: ``deb`` or ``rpm``.
        path: The downloaded package file.
        data_dir: Where the log and the result are written.

    Returns:
        One ``sh -c`` script. The umask makes both files 0600, and the
        install runs in a subshell so its own exit cannot skip the result.
    """
    log = shlex.quote(os.path.join(data_dir, AGENT_REINSTALL_LOG_NAME))
    result = shlex.quote(os.path.join(data_dir, AGENT_REINSTALL_RESULT_NAME))
    tail = AGENT_REINSTALL_OUTPUT_LIMIT_BYTES
    return "\n".join(
        [
            "umask 077",
            f": > {log}",
            f"started=$({_RESULT_STAMP})",
            f"( {install} ) >> {log} 2>&1",
            "code=$?",
            f"finished=$({_RESULT_STAMP})",
            f"printf {_RESULT_HEAD} {shlex.quote(os.path.basename(path))} "
            f'{shlex.quote(kind)} "$started" "$finished" "$code" > {result}',
            f"tail -c {tail} {log} | tr -d '\\r' | tr '\\t' ' ' "
            f"| {_RESULT_ESCAPE} | tr -d '\\n' >> {result}",
            f"""printf '"}}\\n' >> {result}""",
        ]
    )


def _sha256(path: str) -> str:
    """The SHA-256 hex digest of a file.

    Args:
        path: The file to digest.

    Returns:
        The digest.
    """
    with open(path, "rb") as stream:
        return hashlib.sha256(stream.read()).hexdigest()
