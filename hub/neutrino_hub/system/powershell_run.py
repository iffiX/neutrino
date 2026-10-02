"""Running one PowerShell script on a Windows hub, JSON in and out.

The script travels as ``-EncodedCommand``, so no quoting of the command line
can change it, and its document travels on standard input. Every script
starts with a prologue that reads the document as ``$d``; the script's
answer is the last JSON object it prints. The shape is the agent's own
runner, copied, since the packages share no code.

Not pure: runs PowerShell.
"""

import base64
import json

from neutrino_hub.system.constants import (
    SYSTEM_POWERSHELL_PROGRAM,
    SYSTEM_POWERSHELL_TIMEOUT_S,
)
from neutrino_hub.utils.subprocess_run import run

# Every script reads its document from standard input and writes UTF-8.
POWERSHELL_PROLOGUE = """
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::InputEncoding = [Text.Encoding]::UTF8
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$d = [Console]::In.ReadToEnd() | ConvertFrom-Json
"""


def run_powershell(script: str, document: dict) -> dict:
    """Run one script with a JSON document on its standard input.

    Args:
        script: The script, without the prologue that reads the document.
        document: What the script reads as ``$d``.

    Returns:
        The JSON object the script printed last.

    Raises:
        OSError: When PowerShell cannot run, fails, or prints no JSON object.
    """
    encoded = base64.b64encode((POWERSHELL_PROLOGUE + script).encode("utf-16-le"))
    result = run(
        [
            SYSTEM_POWERSHELL_PROGRAM,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-EncodedCommand",
            encoded.decode("ascii"),
        ],
        is_checked=False,
        input_text=json.dumps(document),
        timeout_s=SYSTEM_POWERSHELL_TIMEOUT_S,
    )
    if not result.is_success:
        raise OSError(
            f"powershell exited {result.exit_code}: "
            + (result.stderr.strip() or result.stdout.strip())[-500:]
        )
    answer = _last_json_object(result.stdout)
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
