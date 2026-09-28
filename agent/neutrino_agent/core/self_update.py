"""Updating this agent to the hub's own release.

An agent whose welcome names a later ``software`` than its own takes the
hub's package down a ``package {}`` stream it opens, checks the digest the
close named, and installs the file. Installing the package restarts the
agent's service, which ends the process that asked for the update, so the
install runs outside it: in a transient systemd unit on Linux, in a
PowerShell detached from the service on Windows, and in a job submitted to
launchd on macOS. Each writes what the installer said and how it exited
beside the agent's state, in one shape, and the agent that install put on
the machine reads it there and carries it up.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import json
import ntpath
import os
import shlex
import shutil
import subprocess

from neutrino_agent.constants import (
    AGENT_REINSTALL_LOG_NAME,
    AGENT_REINSTALL_OUTPUT_LIMIT_BYTES,
    AGENT_REINSTALL_RESULT_NAME,
    AGENT_UPDATE_LAUNCH_TIMEOUT_S,
    AGENT_UPDATE_UNIT,
)
from neutrino_agent.exceptions import GatewayUnreachable, SelfUpdateError
from neutrino_agent.streams.package import (
    CODE_DIGEST_MISMATCH,
    CODE_UNREACHABLE,
    PackageStream,
)

FAMILY_TO_PACKAGE_KIND = {"debian": "deb", "rhel": "rpm"}
# The package kind a machine installs by its operating system alone.
OS_TO_PACKAGE_KIND = {"windows": "msi", "darwin": "pkg"}

# How the Windows install is started: with no console, and outside any job
# the service runs in, so stopping the service does not end it.
WINDOWS_DETACHED_PROCESS = 0x00000008
WINDOWS_CREATE_BREAKAWAY_FROM_JOB = 0x01000000

# The PowerShell the Windows install runs in: msiexec, its verbose log, and
# the result in the shape the reporting script writes elsewhere, UTF-8
# without a byte order mark.
_WINDOWS_SCRIPT = """$ErrorActionPreference = 'Continue'
$log = {log}
$started = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
$run = Start-Process -FilePath msiexec.exe -Wait -PassThru -WindowStyle Hidden -ArgumentList {arguments}
$code = $run.ExitCode
$finished = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
$output = ''
if (Test-Path -LiteralPath $log) {{
    $output = [string](Get-Content -LiteralPath $log -Raw)
    if ($output.Length -gt {tail}) {{ $output = $output.Substring($output.Length - {tail}) }}
    $output = $output.Replace("`r", '')
}}
$result = [ordered]@{{package = {package}; kind = 'msi'; started_at = $started; finished_at = $finished; exit_code = $code; output = $output}}
[IO.File]::WriteAllText({result}, ($result | ConvertTo-Json -Compress))
"""

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


def package_kind(platform: dict) -> str:
    """The hub package kind this machine installs.

    Args:
        platform: The tuple from ``platforms.detect.platform_tuple``.

    Returns:
        ``msi`` on Windows, ``pkg`` on macOS, ``deb`` or ``rpm`` by the
        distribution family, or empty when the hub bakes nothing for this
        machine.
    """
    by_os = OS_TO_PACKAGE_KIND.get(platform.get("os", ""), "")
    if by_os:
        return by_os
    return FAMILY_TO_PACKAGE_KIND.get(platform.get("family", ""), "")


def install_command(kind: str, path: str, *, data_dir: str) -> list:
    """The detached command that installs a received package. Pure.

    Args:
        kind: ``deb``, ``rpm``, ``msi`` or ``pkg``.
        path: The received package file.
        data_dir: The agent's data directory, where the install's log and
            its result are written.

    Returns:
        An argument vector that outlives the agent's own restart: a
        ``systemd-run`` transient unit, a PowerShell running msiexec, or a
        ``launchctl submit`` of ``installer``.
    """
    if kind == "msi":
        return _windows_install_command(path, data_dir=data_dir)
    if kind == "pkg":
        install = f"installer -pkg {shlex.quote(path)} -target /"
        script = _reporting_script(install, kind=kind, path=path, data_dir=data_dir)
        return [
            "launchctl",
            "submit",
            "-l",
            AGENT_UPDATE_UNIT,
            "--",
            "sh",
            "-c",
            script,
        ]
    if kind == "deb":
        # dpkg installs a same-version file where apt would call it already
        # newest, and the reinstall verb installs exactly that; apt then
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


def receive_package(channel, *, directory: str) -> str:
    """Take the agent's own package down a ``package {}`` stream.

    Args:
        channel: The stream's channel, already opened as ``package {}``.
        directory: Where the file lands.

    Returns:
        The path of the file whose digest matched the close's ``sha256``.

    Raises:
        SelfUpdateError: When the bytes do not match the digest the hub
            named, as ``agent_package_digest_mismatch``, or the hub closed
            the stream with a code, which is the message; no file remains.
        GatewayUnreachable: When the socket went away mid-transfer; no
            file remains.
    """
    received = PackageStream(channel, directory=directory).receive()
    if "path" in received:
        return received["path"]
    code = received["code"]
    if code == CODE_UNREACHABLE:
        raise GatewayUnreachable("the package stream ended before its close")
    if code == CODE_DIGEST_MISMATCH:
        raise SelfUpdateError("agent_package_digest_mismatch")
    raise SelfUpdateError(code)


def run_update(package_path: str, *, kind: str, data_dir: str) -> None:
    """Install a package whose digest was checked, detached from this process.

    Args:
        package_path: The package file :func:`receive_package` handed over.
            It outlives this process: the install restarts the service,
            and the agent that starts then clears the directory.
        kind: ``deb``, ``rpm``, ``msi`` or ``pkg``.
        data_dir: The agent's data directory, where the install writes
            what it did.

    Raises:
        SelfUpdateError: When the install cannot be launched, as
            ``agent_update_launch_failed``; the file is deleted.
    """
    clear_reinstall_result(data_dir)
    command = install_command(kind, package_path, data_dir=data_dir)
    try:
        if kind == "msi":
            _start_detached(command)
            return
        if kind == "pkg":
            # A job an earlier update submitted keeps its label until removed.
            subprocess.run(
                ["launchctl", "remove", AGENT_UPDATE_UNIT],
                capture_output=True,
                timeout=AGENT_UPDATE_LAUNCH_TIMEOUT_S,
            )
        subprocess.run(
            command,
            capture_output=True,
            timeout=AGENT_UPDATE_LAUNCH_TIMEOUT_S,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as error:
        os.unlink(package_path)
        raise SelfUpdateError("agent_update_launch_failed") from error


def _start_detached(command: list) -> None:
    """Start the Windows install with no console and outside the service's job.

    A job that refuses breakaway refuses the start; the install is then
    started with no console alone.

    Args:
        command: The argument vector.

    Raises:
        OSError: When the process cannot be started at all.
    """
    for flags in (
        WINDOWS_DETACHED_PROCESS | WINDOWS_CREATE_BREAKAWAY_FROM_JOB,
        WINDOWS_DETACHED_PROCESS,
    ):
        try:
            subprocess.Popen(
                command,
                creationflags=flags,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
            return
        except OSError as error:
            refusal = error
    raise refusal


def _windows_install_command(path: str, *, data_dir: str) -> list:
    """The PowerShell that runs msiexec and writes its result.

    Args:
        path: The received ``.msi``.
        data_dir: Where the log and the result are written.

    Returns:
        The argument vector.
    """
    log = ntpath.join(data_dir, AGENT_REINSTALL_LOG_NAME)
    arguments = f'/i "{path}" /qn /norestart /l*v "{log}"'
    script = _WINDOWS_SCRIPT.format(
        log=_powershell_quote(log),
        arguments=_powershell_quote(arguments),
        tail=AGENT_REINSTALL_OUTPUT_LIMIT_BYTES,
        package=_powershell_quote(ntpath.basename(path)),
        result=_powershell_quote(ntpath.join(data_dir, AGENT_REINSTALL_RESULT_NAME)),
    )
    return [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        script,
    ]


def _powershell_quote(text: str) -> str:
    """One value as a PowerShell literal string."""
    return "'" + text.replace("'", "''") + "'"


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
        kind: ``deb``, ``rpm`` or ``pkg``.
        path: The received package file.
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
