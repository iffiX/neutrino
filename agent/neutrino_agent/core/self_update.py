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

launchd keeps a submitted job alive and runs it again every ten seconds,
so the macOS job removes itself as its last act, and an agent that starts
removes a job of that label that is not running.
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
import time

from neutrino_agent.constants import (
    AGENT_REINSTALL_LOG_NAME,
    AGENT_REINSTALL_OUTPUT_LIMIT_BYTES,
    AGENT_REINSTALL_POLL_S,
    AGENT_REINSTALL_RESULT_NAME,
    AGENT_UPDATE_LAUNCH_TIMEOUT_S,
    AGENT_UPDATE_UNIT,
)
from neutrino_agent.exceptions import GatewayUnreachable, SelfUpdateError
from neutrino_agent.modules.log_tail import mask_secrets
from neutrino_agent.platforms import win32
from neutrino_agent.streams.package import (
    CODE_DIGEST_MISMATCH,
    CODE_UNREACHABLE,
    PackageStream,
)

FAMILY_TO_PACKAGE_KIND = {"debian": "deb", "rhel": "rpm"}
# The received package's final name before its kind's extension, when the
# hub sends no release name; ``installer`` and ``dnf`` refuse a file that
# does not end in ``.pkg`` or ``.rpm``.
PACKAGE_FILE_STEM = "neutrino_agent"
# The package kind a machine installs by its operating system alone.
OS_TO_PACKAGE_KIND = {"windows": "msi", "darwin": "pkg"}

# How the Windows install is started: with a console that has no window,
# and outside any job the service runs in, so stopping the service does not
# end it. A process started detached from every console never writes the
# result.
WINDOWS_CREATE_BREAKAWAY_FROM_JOB = 0x01000000

# The PowerShell the Windows install runs in: msiexec, its verbose log, and
# the result in the shape the reporting script writes elsewhere, UTF-8
# without a byte order mark.
_WINDOWS_SCRIPT = """$ErrorActionPreference = 'Continue'
$log = {log}
$started = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
$run = Start-Process -FilePath msiexec.exe -Wait -PassThru -NoNewWindow -ArgumentList {arguments}
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


def install_command(kind: str, path: str, *, state_dir: str) -> list:
    """The detached command that installs a received package. Pure.

    Args:
        kind: ``deb``, ``rpm``, ``msi`` or ``pkg``.
        path: The received package file.
        state_dir: The agent's state directory, where the install's log and
            its result are written.

    Returns:
        An argument vector that outlives the agent's own restart: a
        ``systemd-run`` transient unit, a PowerShell running msiexec, or a
        ``launchctl submit`` of ``installer``.
    """
    if kind == "msi":
        return _windows_install_command(path, state_dir=state_dir)
    if kind == "pkg":
        install = f"installer -pkg {shlex.quote(path)} -target /"
        script = _reporting_script(install, kind=kind, path=path, state_dir=state_dir)
        script += f"\nlaunchctl remove {AGENT_UPDATE_UNIT}"
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
    script = _reporting_script(install, kind=kind, path=path, state_dir=state_dir)
    return (
        ["systemd-run", "--unit", AGENT_UPDATE_UNIT, "--collect"]
        + setenv
        + ["sh", "-c", script]
    )


def remove_stale_job(kind: str) -> bool:
    """Remove a submitted update job launchd still holds and is not running.

    A job an earlier build submitted stays with launchd and runs its
    install again every ten seconds. One that is running now is the install
    that is starting this agent, and is left to end and remove itself.

    Args:
        kind: The machine's package kind; only ``pkg`` submits a job.

    Returns:
        Whether a job was removed.
    """
    if kind != "pkg":
        return False
    try:
        held = subprocess.run(
            ["launchctl", "print", f"system/{AGENT_UPDATE_UNIT}"],
            capture_output=True,
            text=True,
            timeout=AGENT_UPDATE_LAUNCH_TIMEOUT_S,
        )
        if held.returncode != 0 or "state = running" in (held.stdout or ""):
            return False
        subprocess.run(
            ["launchctl", "remove", AGENT_UPDATE_UNIT],
            capture_output=True,
            timeout=AGENT_UPDATE_LAUNCH_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def read_reinstall_result(state_dir: str) -> "dict | None":
    """What the reinstall this agent came from did.

    Args:
        state_dir: The agent's state directory.

    Returns:
        ``{"package", "kind", "started_at", "finished_at", "exit_code",
        "output"}``, the output's tokens masked, or None when no readable
        result stands there.
    """
    try:
        with open(
            _reinstall_result_path(state_dir), "r", encoding="utf-8", errors="replace"
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
        "output": mask_secrets(str(written.get("output", "") or "")),
    }


def wait_reinstall_result(
    state_dir: str, *, timeout_s: float, sleep=time.sleep, clock=time.monotonic
) -> "dict | None":
    """What the launched install did, once its result is written.

    An install that goes through restarts this process, which ends the wait.

    Args:
        state_dir: The agent's state directory.
        timeout_s: How long to wait for the result.
        sleep: Waits the given seconds between looks.
        clock: Returns monotonic seconds.

    Returns:
        The result as :func:`read_reinstall_result` reads it, or None when
        none was written in time.
    """
    deadline = clock() + timeout_s
    while True:
        result = read_reinstall_result(state_dir)
        if result is not None or clock() >= deadline:
            return result
        sleep(AGENT_REINSTALL_POLL_S)


def clear_reinstall_result(state_dir: str) -> None:
    """Drop what an earlier reinstall left, before a new one starts.

    Args:
        state_dir: The agent's state directory.
    """
    try:
        os.unlink(_reinstall_result_path(state_dir))
    except OSError:
        pass


def receive_package(channel, *, directory: str, kind: str) -> str:
    """Take the agent's own package down a ``package {}`` stream.

    Args:
        channel: The stream's channel, already opened as ``package {}``.
        directory: Where the file lands.
        kind: ``deb``, ``rpm``, ``msi`` or ``pkg``, the final name's
            extension.

    Returns:
        The path of the file whose digest matched the close's ``sha256``,
        renamed to the release file name the close carried, or
        ``neutrino_agent.<kind>`` when it carried none or an unsafe one.

    Raises:
        SelfUpdateError: When the bytes do not match the digest the hub
            named, as ``agent_package_digest_mismatch``, or the hub closed
            the stream with a code, which is the message; no file remains.
        GatewayUnreachable: When the socket went away mid-transfer; no
            file remains.
    """
    received = PackageStream(
        channel, directory=directory, name=f"{PACKAGE_FILE_STEM}.{kind}"
    ).receive()
    if "path" in received:
        return received["path"]
    code = received["code"]
    if code == CODE_UNREACHABLE:
        raise GatewayUnreachable("the package stream ended before its close")
    if code == CODE_DIGEST_MISMATCH:
        raise SelfUpdateError("agent_package_digest_mismatch")
    raise SelfUpdateError(code)


def run_update(package_path: str, *, kind: str, state_dir: str) -> None:
    """Install a package whose digest was checked, detached from this process.

    Args:
        package_path: The package file :func:`receive_package` handed over.
            It outlives this process: the install restarts the service,
            and the agent that starts then clears the directory.
        kind: ``deb``, ``rpm``, ``msi`` or ``pkg``.
        state_dir: The agent's state directory, where the install writes
            what it did.

    Raises:
        SelfUpdateError: When the install cannot be launched, as
            ``agent_update_launch_failed``; the file is deleted.
    """
    clear_reinstall_result(state_dir)
    command = install_command(kind, package_path, state_dir=state_dir)
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
    """Start the Windows install with no window and outside the service's job.

    A job that refuses breakaway refuses the start; the install is then
    started with no window alone.

    Args:
        command: The argument vector.

    Raises:
        OSError: When the process cannot be started at all.
    """
    for flags in (
        win32.CREATE_NO_WINDOW | WINDOWS_CREATE_BREAKAWAY_FROM_JOB,
        win32.CREATE_NO_WINDOW,
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


def _windows_install_command(path: str, *, state_dir: str) -> list:
    """The PowerShell that runs msiexec and writes its result.

    Args:
        path: The received ``.msi``.
        state_dir: Where the log and the result are written.

    Returns:
        The argument vector.
    """
    log = ntpath.join(state_dir, AGENT_REINSTALL_LOG_NAME)
    arguments = (
        f'/i "{path}" REINSTALL=ALL REINSTALLMODE=vomus /qn /norestart /l*v "{log}"'
    )
    script = _WINDOWS_SCRIPT.format(
        log=_powershell_quote(log),
        arguments=_powershell_quote(arguments),
        tail=AGENT_REINSTALL_OUTPUT_LIMIT_BYTES,
        package=_powershell_quote(ntpath.basename(path)),
        result=_powershell_quote(ntpath.join(state_dir, AGENT_REINSTALL_RESULT_NAME)),
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


def _reinstall_result_path(state_dir: str) -> str:
    """Where the transient unit writes what the install did.

    Args:
        state_dir: The agent's state directory.

    Returns:
        The result file's path.
    """
    return os.path.join(state_dir, AGENT_REINSTALL_RESULT_NAME)


def _reporting_script(install: str, *, kind: str, path: str, state_dir: str) -> str:
    """The shell the transient unit runs: the install, its log, its result.

    Args:
        install: The package manager's own command line.
        kind: ``deb``, ``rpm`` or ``pkg``.
        path: The received package file.
        state_dir: Where the log and the result are written.

    Returns:
        One ``sh -c`` script. The umask makes both files 0600, and the
        install runs in a subshell so its own exit cannot skip the result.
    """
    log = shlex.quote(os.path.join(state_dir, AGENT_REINSTALL_LOG_NAME))
    result = shlex.quote(os.path.join(state_dir, AGENT_REINSTALL_RESULT_NAME))
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
