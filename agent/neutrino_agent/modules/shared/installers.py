"""Installing a downloaded package, the way this machine installs things.

One function per artifact kind, each doing what the machine's own tooling
does unattended: msiexec on Windows once the Windows Installer is free, and
``installer`` for a macOS pkg; and the shell steps a recipe names.

Not pure: runs installers.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
import subprocess

from neutrino_agent.constants import (
    AGENT_MODULE_OUTPUT_LIMIT_BYTES,
    AGENT_REINSTALL_INSTALLED_CODES,
    AGENT_UPDATE_LOCK_TIMEOUT_S,
    AGENT_UPDATE_MSI_BUSY_CODE,
    AGENT_UPDATE_MSI_MUTEX,
    AGENT_UPDATE_MSI_REBOOT_CODE,
)
from neutrino_agent.exceptions import InstallError, ModuleApplyError

INSTALL_TIMEOUT_S = 1800
COMMAND_TIMEOUT_S = 120

# The PowerShell that runs msiexec: a wait while another install holds the
# Windows Installer's mutex, msiexec with no window, waited for, and msiexec
# once more after a busy answer. The exit code is left in ``$code``.
_MSIEXEC_SCRIPT = """function Wait-Installer {{
    $deadline = (Get-Date).AddSeconds({lock_timeout})
    while ((Get-Date) -lt $deadline) {{
        $held = $null
        try {{
            if (-not [Threading.Mutex]::TryOpenExisting({mutex}, [ref]$held)) {{ return }}
            $held.Dispose()
        }} catch [UnauthorizedAccessException] {{
        }}
        Start-Sleep -Seconds 1
    }}
}}
function Invoke-Install {{
    Wait-Installer
{before}    $run = Start-Process -FilePath msiexec.exe -Wait -PassThru -NoNewWindow -ArgumentList {arguments}
    return $run.ExitCode
}}
$code = Invoke-Install
if ($code -eq {busy}) {{ $code = Invoke-Install }}
"""

# What runs msiexec in place: the script, then msiexec's exit code as
# PowerShell's own, and 1 when msiexec did not start. msiexec writes its own
# messages to the standard output it inherits, which is dropped; PowerShell's
# errors stay on standard error.
_MSIEXEC_RUN_HEAD = "$ErrorActionPreference = 'Continue'\n"
_MSIEXEC_RUN_TAIL = "if ($code -isnot [int]) { exit 1 }\nexit $code\n"


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
            f"{command[0]} failed: {output[-AGENT_MODULE_OUTPUT_LIMIT_BYTES:]}",
            exit_code=result.returncode,
        )
    return result.stdout or ""


def powershell_quote(text: str) -> str:
    """One value as a PowerShell literal string. Pure.

    Args:
        text: The value.

    Returns:
        The value in single quotes, each single quote in it doubled.
    """
    return "'" + text.replace("'", "''") + "'"


def powershell_command(script: str) -> list:
    """The argument vector that runs one PowerShell script. Pure.

    Args:
        script: The script's text.

    Returns:
        ``powershell.exe`` with no profile, no prompt and any execution
        policy, running the script as its command.
    """
    return [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        script,
    ]


def msiexec_arguments(path: str, *, log_path: str, properties=()) -> str:
    """msiexec's command line for one quiet install. Pure.

    Args:
        path: The ``.msi`` file.
        log_path: Where msiexec writes its verbose log.
        properties: Public properties, each ``NAME=value`` as msiexec takes
            it, such as ``ALLUSERS=1``, in order after the log.

    Returns:
        ``/i "<path>" /qn /norestart /l*v "<log>"`` and the properties.
    """
    arguments = f'/i "{path}" /qn /norestart /l*v "{log_path}"'
    return "".join([arguments] + [f" {setting}" for setting in properties])


def msiexec_script(arguments: str, *, before: str = "") -> str:
    """The PowerShell that runs msiexec once the Windows Installer is free. Pure.

    The script waits while another install holds the Windows Installer's
    mutex, for as long as an install waits for a package manager's lock,
    runs msiexec with no window and waits for it, and runs it once more
    when it answers 1618, busy. It leaves the exit code in ``$code``.

    Args:
        arguments: msiexec's command line, such as
            :func:`msiexec_arguments` gives.
        before: PowerShell lines run after each wait and before msiexec,
            each indented four spaces and ended with a newline; a
            ``return`` among them is taken as the exit code, and msiexec
            does not run.

    Returns:
        The script's lines, each ended with a newline.
    """
    return _MSIEXEC_SCRIPT.format(
        lock_timeout=AGENT_UPDATE_LOCK_TIMEOUT_S,
        mutex=powershell_quote(AGENT_UPDATE_MSI_MUTEX),
        before=before,
        arguments=powershell_quote(arguments),
        busy=AGENT_UPDATE_MSI_BUSY_CODE,
    )


def install_msi(path: str, *, log_path: str, properties=()) -> bool:
    """Install one ``.msi`` with msiexec, quietly, and wait for it.

    Args:
        path: The ``.msi`` file.
        log_path: Where msiexec writes its verbose log.
        properties: Public properties, as :func:`msiexec_arguments` takes
            them.

    Returns:
        Whether the install finished with a restart owed, exit code 3010.

    Raises:
        ModuleApplyError: ``package_manager_busy {holder}`` when another
            install still held the Windows Installer after the wait.
        InstallError: When msiexec exits other than 0 and 3010, with its
            exit code, 1 when msiexec did not start; when PowerShell cannot
            run, with none.
    """
    arguments = msiexec_arguments(path, log_path=log_path, properties=properties)
    return _run_msiexec(arguments) == AGENT_UPDATE_MSI_REBOOT_CODE


def uninstall_msi(product_code: str, *, log_path: str) -> bool:
    """Uninstall one Windows Installer product, quietly, and wait for it.

    Args:
        product_code: The product's code, such as
            ``{12345678-1234-1234-1234-123456789ABC}``.
        log_path: Where msiexec writes its verbose log.

    Returns:
        Whether the uninstall finished with a restart owed, exit code 3010.

    Raises:
        ModuleApplyError: ``package_manager_busy {holder}`` when another
            install still held the Windows Installer after the wait.
        InstallError: When msiexec exits other than 0 and 3010, with its
            exit code, 1 when msiexec did not start; when PowerShell cannot
            run, with none.
    """
    return (
        _run_msiexec(f'/x {product_code} /qn /norestart /l*v "{log_path}"')
        == AGENT_UPDATE_MSI_REBOOT_CODE
    )


def install_pkg(path: str) -> None:
    """Install one macOS ``.pkg`` with the system's installer, and wait for it.

    Args:
        path: The ``.pkg`` file.

    Raises:
        InstallError: When ``installer`` fails, with its exit code and its
            own words, or cannot run.
    """
    run_checked(
        ["installer", "-pkg", path, "-target", "/"], timeout_s=INSTALL_TIMEOUT_S
    )


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


def _run_msiexec(arguments: str) -> int:
    """msiexec's exit code, 0 or 3010, run through :func:`msiexec_script`."""
    script = _MSIEXEC_RUN_HEAD + msiexec_script(arguments) + _MSIEXEC_RUN_TAIL
    try:
        result = subprocess.run(
            powershell_command(script),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            timeout=INSTALL_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise InstallError(f"msiexec could not run: {error}")
    code = result.returncode
    if code == AGENT_UPDATE_MSI_BUSY_CODE:
        raise ModuleApplyError("package_manager_busy", {"holder": ""})
    if code not in AGENT_REINSTALL_INSTALLED_CODES:
        message = f"msiexec exited {code}"
        said = (result.stderr or "").strip()
        if said:
            message += f": {said[-AGENT_MODULE_OUTPUT_LIMIT_BYTES:]}"
        raise InstallError(message, exit_code=code)
    return code


def _apt_env() -> dict:
    env = dict(os.environ)
    env["DEBIAN_FRONTEND"] = "noninteractive"
    return env
