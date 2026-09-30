"""Running one PowerShell script for a module on Windows, JSON in and out.

The script travels as ``-EncodedCommand``, so no quoting of the command line
can change it, and its document, passwords included, travels on standard
input and never touches the command line. Every script starts with a
prologue that reads the document as ``$d`` and defines ``Send-Refusal``,
which prints ``{code, params}`` and exits 3; the script's answer is the last
JSON object it prints.

Not pure: runs PowerShell.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import base64
import json

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.subprocess_run import run

# Every script reads its document from standard input and writes UTF-8. A
# native tool's complaint on standard error is not an error here: the
# script reads the tool's exit code.
POWERSHELL_PROLOGUE = """
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::InputEncoding = [Text.Encoding]::UTF8
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$d = [Console]::In.ReadToEnd() | ConvertFrom-Json
function Send-Refusal($code, $params) {
  @{code = $code; params = $params} | ConvertTo-Json -Compress -Depth 5
  exit 3
}
function Invoke-Icacls {
  $ErrorActionPreference = 'Continue'
  & icacls.exe @args 2>&1 | Out-Null
  return $LASTEXITCODE
}
"""
# The exit status a script ends with when it prints a refusal.
POWERSHELL_REFUSAL_EXIT = 3
POWERSHELL_TIMEOUT_S = 120


def run_powershell(script: str, document: dict) -> dict:
    """Run one script with a JSON document on its standard input.

    Args:
        script: The script, without the prologue that reads the document.
        document: What the script reads as ``$d``.

    Returns:
        The JSON object the script printed last.

    Raises:
        ModuleApplyError: The code and params of a refusal the script sent.
        OSError: When PowerShell cannot run, fails, or prints no JSON object.
    """
    encoded = base64.b64encode((POWERSHELL_PROLOGUE + script).encode("utf-16-le"))
    result = run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-EncodedCommand",
            encoded.decode("ascii"),
        ],
        is_checked=False,
        input_text=json.dumps(document),
        timeout_s=POWERSHELL_TIMEOUT_S,
    )
    answer = _last_json_object(result.stdout)
    if result.exit_code == POWERSHELL_REFUSAL_EXIT and answer is not None:
        raise ModuleApplyError(
            str(answer.get("code", "") or "apply_failed"),
            dict(answer.get("params") or {}),
        )
    if not result.is_success:
        raise OSError(
            f"powershell exited {result.exit_code}: "
            + (result.stderr.strip() or result.stdout.strip())[-500:]
        )
    if answer is None:
        raise OSError("powershell printed no JSON object")
    return answer


def listed(value) -> list:
    """A PowerShell JSON member as a list: one object comes back bare.

    Args:
        value: The member as parsed.

    Returns:
        The member itself when it is a list, empty for null, else a list of
        the one value.
    """
    if isinstance(value, list):
        return value
    return [] if value is None else [value]


def _last_json_object(text: str) -> "dict | None":
    """The last line of the output that parses as a JSON object."""
    for line in reversed((text or "").splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None
