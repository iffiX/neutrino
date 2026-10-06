"""cc-switch and an account's own files, reached as that account.

Everything the steps of the machine's AI tools do in an account's home is
done as the account, through the platform's way of running as it: cc-switch
itself, and reading, writing and removing a tool's file. Nothing the agent
does as root or SYSTEM touches the account's home. On Linux and macOS the
files are read with ``cat`` and written with ``sh``; on Windows each is a
small PowerShell script, run in the account's own one-shot task.

Not pure: runs processes as an account.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import base64
import ntpath
import posixpath
import subprocess

from neutrino_agent.ai_tools.constants import (
    AI_TOOLS_CODE_CREDENTIAL_INVALID,
    AI_TOOLS_CODE_SWITCH_FAILED,
    AI_TOOLS_COMMAND_TIMEOUT_S,
    AI_TOOLS_DETAIL_LIMIT,
    AI_TOOLS_PAYLOAD_BASE,
    AI_TOOLS_PAYLOAD_NAME,
    AI_TOOLS_PAYLOAD_TREE,
)
from neutrino_agent.exceptions import (
    ModuleApplyError,
    PlatformUnsupportedError,
    ToolSwitchError,
)

# Writes standard input to the file the first argument names, its directory
# made first.
POSIX_WRITE_SHELL = 'mkdir -p -- "$(dirname -- "$1")" && cat > "$1"'
# Removes the file the first argument names, then each directory after it
# that is empty, stopping at the first that is not.
POSIX_REMOVE_SHELL = (
    'rm -f -- "$1"; shift; for d do rmdir -- "$d" 2>/dev/null || exit 0; done'
)
# The PowerShell that does the same four things on Windows, each given the
# path as a literal.
WINDOWS_READ_SCRIPT = """
$p = {path}
if (-not (Test-Path -LiteralPath $p -PathType Leaf)) {{ exit 1 }}
$out = New-Object IO.StreamWriter ([Console]::OpenStandardOutput()), (New-Object Text.UTF8Encoding $false)
$out.Write([IO.File]::ReadAllText($p))
$out.Flush()
exit 0
"""
WINDOWS_IS_FILE_SCRIPT = """
if (Test-Path -LiteralPath {path} -PathType Leaf) {{ exit 0 }}
exit 1
"""
WINDOWS_WRITE_SCRIPT = """
$p = {path}
$in = New-Object IO.StreamReader ([Console]::OpenStandardInput()), (New-Object Text.UTF8Encoding $false)
$text = $in.ReadToEnd()
$dir = Split-Path -Parent $p
if (-not (Test-Path -LiteralPath $dir)) {{ New-Item -ItemType Directory -Path $dir -Force | Out-Null }}
[IO.File]::WriteAllText($p, $text, (New-Object Text.UTF8Encoding $false))
exit 0
"""
WINDOWS_REMOVE_SCRIPT = """
Remove-Item -LiteralPath {path} -Force -ErrorAction SilentlyContinue
exit 0
"""
WINDOWS_IS_DIR_SCRIPT = """
if (Test-Path -LiteralPath {path} -PathType Container) {{ exit 0 }}
exit 1
"""
WINDOWS_MAKE_DIR_SCRIPT = """
New-Item -ItemType Directory -Path {path} -Force | Out-Null
exit 0
"""
WINDOWS_REMOVE_EMPTY_DIR_SCRIPT = """
$d = {path}
if ((Test-Path -LiteralPath $d -PathType Container) -and -not (Get-ChildItem -LiteralPath $d -Force)) {{
    Remove-Item -LiteralPath $d -Force -ErrorAction SilentlyContinue
}}
exit 0
"""
WINDOWS_REMOVE_WITH_DIRS_SCRIPT = """
Remove-Item -LiteralPath {path} -Force -ErrorAction SilentlyContinue
foreach ($d in @({dirs})) {{
    if (-not (Test-Path -LiteralPath $d -PathType Container)) {{ continue }}
    if (Get-ChildItem -LiteralPath $d -Force) {{ break }}
    Remove-Item -LiteralPath $d -Force -ErrorAction SilentlyContinue
}}
exit 0
"""


def powershell_literal(text: str) -> str:
    """A string as a single-quoted PowerShell literal."""
    return "'" + text.replace("'", "''") + "'"


def powershell_argv(script: str) -> list:
    """PowerShell running one script, carried as ``-EncodedCommand``."""
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-EncodedCommand",
        encoded,
    ]


class AiToolsAccountSession:
    """One account, as the steps of its AI tools reach it."""

    def __init__(
        self,
        *,
        platform,
        account: str,
        home: str,
        binary: str,
        password: str = "",
    ):
        """
        Args:
            platform: The machine's platform, which runs as the account.
            account: The account.
            home: The account's home, as its system spells it.
            binary: The cc-switch the agent's package carries.
            password: The account's login; Windows needs it.
        """
        self.account = account
        self.home = home
        self._platform = platform
        self._binary = binary
        self._password = password
        self._os_name = platform.os_name
        self._is_windows = platform.os_name == "windows"
        self._join = ntpath.join if self._is_windows else posixpath.join

    def path(self, *parts: str) -> str:
        """One path below the account's home."""
        return self._join(self.home, *parts)

    def failure(self, detail: str) -> ToolSwitchError:
        """``switch_failed {account, detail}`` for this account."""
        return ToolSwitchError(
            AI_TOOLS_CODE_SWITCH_FAILED,
            {"account": self.account, "detail": detail[:AI_TOOLS_DETAIL_LIMIT]},
        )

    def cc(self, arguments: list, app: str, *, is_checked: bool = True) -> str:
        """Run cc-switch as the account for one tool.

        Args:
            arguments: Arguments after the app selector.
            app: Which tool's configuration to act on.
            is_checked: Whether a non-zero exit is an error.

        Returns:
            Standard output.

        Raises:
            ToolSwitchError: When it cannot run as the account.
            subprocess.CalledProcessError: On a non-zero exit while checked.
        """
        command = [self._binary, "--app", app] + list(arguments)
        result = self._run(command)
        if is_checked and result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode, command, output=result.stdout, stderr=result.stderr
            )
        return result.stdout or ""

    def cc_answering(
        self, arguments: list, app: str, *, prompt: str, answer: str
    ) -> str:
        """Run cc-switch as the account on a terminal of its own, answering its question.

        Args:
            arguments: Arguments after the app selector.
            app: Which tool's configuration to act on.
            prompt: The question's text.
            answer: The answer, newline included.

        Returns:
            What the terminal drew.

        Raises:
            ToolSwitchError: When no terminal can be made or it cannot run
                as the account.
        """
        command = [self._binary, "--app", app] + list(arguments)
        try:
            _code, printed = self._platform.run_as_account_answering(
                self.account,
                command,
                prompt=prompt,
                answer=answer,
                timeout_s=AI_TOOLS_COMMAND_TIMEOUT_S,
                password=self._password,
            )
        except ModuleApplyError as error:
            raise self._refused(error) from error
        except (PlatformUnsupportedError, OSError) as error:
            raise self.failure(f"could not answer cc-switch: {error}") from error
        return str(printed or "")

    def read_text(self, path: str) -> str:
        """One file of the account's, read as the account; empty when absent."""
        if self._is_windows:
            command = powershell_argv(
                WINDOWS_READ_SCRIPT.format(path=powershell_literal(path))
            )
        else:
            command = ["cat", "--", path]
        result = self._run(command)
        return (result.stdout or "") if result.returncode == 0 else ""

    def is_file(self, path: str) -> bool:
        """Whether a file of the account's is there, as the account sees it."""
        if self._is_windows:
            command = powershell_argv(
                WINDOWS_IS_FILE_SCRIPT.format(path=powershell_literal(path))
            )
        else:
            command = ["test", "-f", path]
        return self._run(command).returncode == 0

    def is_dir(self, path: str) -> bool:
        """Whether a directory of the account's is there, as the account sees it."""
        if self._is_windows:
            command = powershell_argv(
                WINDOWS_IS_DIR_SCRIPT.format(path=powershell_literal(path))
            )
        else:
            command = ["test", "-d", path]
        return self._run(command).returncode == 0

    def make_dir(self, path: str) -> None:
        """Make one directory of the account's, as the account, with its parents.

        Raises:
            ToolSwitchError: When it cannot be made.
        """
        if self._is_windows:
            command = powershell_argv(
                WINDOWS_MAKE_DIR_SCRIPT.format(path=powershell_literal(path))
            )
        else:
            command = ["mkdir", "-p", "--", path]
        result = self._run(command)
        if result.returncode != 0:
            words = (result.stderr or result.stdout or "").strip()
            raise self.failure(f"could not make {path}: {words}")

    def remove_empty_dir(self, path: str) -> None:
        """Delete one directory of the account's, as the account, when it holds nothing."""
        if self._is_windows:
            command = powershell_argv(
                WINDOWS_REMOVE_EMPTY_DIR_SCRIPT.format(path=powershell_literal(path))
            )
        else:
            command = ["rmdir", "--", path]
        self._run(command)

    def write_text(self, path: str, text: str) -> None:
        """Write one file of the account's, as the account, its directory made.

        Raises:
            ToolSwitchError: When the file cannot be written.
        """
        if self._is_windows:
            command = powershell_argv(
                WINDOWS_WRITE_SCRIPT.format(path=powershell_literal(path))
            )
        else:
            command = ["sh", "-c", POSIX_WRITE_SHELL, "sh", path]
        result = self._run(command, stdin=text)
        if result.returncode != 0:
            words = (result.stderr or result.stdout or "").strip()
            raise self.failure(f"could not write {path}: {words}")

    def remove(self, path: str) -> None:
        """Delete one file of the account's, as the account; quiet when absent."""
        if self._is_windows:
            command = powershell_argv(
                WINDOWS_REMOVE_SCRIPT.format(path=powershell_literal(path))
            )
        else:
            command = ["rm", "-f", "--", path]
        self._run(command)

    def payload_path(self) -> str:
        """The file a payload for cc-switch is handed in, in the account's Neutrino tree."""
        return self._join(self._payload_dirs()[0], AI_TOOLS_PAYLOAD_NAME)

    def remove_payload(self) -> None:
        """Delete the payload as the account, then each directory of its tree left empty.

        ``ai_tools``, ``agent`` and the Neutrino directory go in that order;
        the first that holds anything else stays, with those above it.
        """
        dirs = self._payload_dirs()
        if self._is_windows:
            command = powershell_argv(
                WINDOWS_REMOVE_WITH_DIRS_SCRIPT.format(
                    path=powershell_literal(self.payload_path()),
                    dirs=", ".join(powershell_literal(d) for d in dirs),
                )
            )
        else:
            command = ["sh", "-c", POSIX_REMOVE_SHELL, "sh", self.payload_path()]
            command += dirs
        self._run(command)

    def _payload_dirs(self) -> list:
        """The payload's tree in the account's home, deepest directory first."""
        key = self._os_name if self._os_name in AI_TOOLS_PAYLOAD_TREE else "linux"
        base = AI_TOOLS_PAYLOAD_BASE[key]
        tree = AI_TOOLS_PAYLOAD_TREE[key]
        return [self.path(*base, *tree[:depth]) for depth in range(len(tree), 0, -1)]

    def _run(self, command: list, *, stdin: str = ""):
        """Run one command as the account.

        Raises:
            ToolSwitchError: ``credential_invalid`` when Windows refuses the
                login, ``switch_failed`` when it cannot run.
        """
        try:
            return self._platform.run_as_account(
                self.account,
                command,
                stdin=stdin,
                timeout_s=AI_TOOLS_COMMAND_TIMEOUT_S,
                password=self._password,
            )
        except ModuleApplyError as error:
            raise self._refused(error) from error
        except (PlatformUnsupportedError, OSError, subprocess.SubprocessError) as error:
            raise self.failure(f"could not run as {self.account}: {error}") from error

    def _refused(self, error: ModuleApplyError) -> ToolSwitchError:
        """A refusal the platform raised, as this account's."""
        if error.code == AI_TOOLS_CODE_CREDENTIAL_INVALID:
            return ToolSwitchError(error.code, {"account": self.account})
        return self.failure(f"{error.code} {error.params}")
