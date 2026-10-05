"""Reaching an account: cc-switch and the account's own files, as the account.

What these pin: cc-switch runs as the account with the app selector first;
a refusal is the command's own error and its words; the delete is answered
on a terminal with the client's prompt and answer; on Linux and macOS a
file is read with ``cat``, tested with ``test -f``, written by ``sh`` from
standard input and removed with ``rm -f``; on Windows each is a PowerShell
script naming the path as a literal; the login rides along on Windows; a
login Windows refuses is ``credential_invalid``; anything else that stops a
run is ``switch_failed`` with the account.
"""

import base64
import subprocess

import pytest

from neutrino_agent.ai_tools.account_session import (
    AiToolsAccountSession,
    powershell_literal,
)
from neutrino_agent.exceptions import ModuleApplyError, ToolSwitchError


class RecordingPlatform:
    """Answers every run with a set result and records it."""

    def __init__(self, os_name="linux", *, code=0, out="", err="", refusal=None):
        self.os_name = os_name
        self.runs: list = []
        self.answered: list = []
        self._result = (code, out, err)
        self._refusal = refusal

    def run_as_account(self, account, argv, *, stdin="", timeout_s=0, password=""):
        self.runs.append(
            {
                "account": account,
                "argv": list(argv),
                "stdin": stdin,
                "password": password,
            }
        )
        if self._refusal is not None:
            raise self._refusal
        code, out, err = self._result
        return subprocess.CompletedProcess(argv, code, out, err)

    def run_as_account_answering(
        self, account, argv, *, prompt, answer, timeout_s=0, password=""
    ):
        self.answered.append((account, list(argv), prompt, answer, password))
        if self._refusal is not None:
            raise self._refusal
        return 0, "drawn"


def session_on(platform, home="/home/ann", password=""):
    return AiToolsAccountSession(
        platform=platform,
        account="ann",
        home=home,
        binary="/opt/neutrino/agent/bin/cc-switch",
        password=password,
    )


def script_of(argv) -> str:
    assert argv[:6] == [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-EncodedCommand",
    ]
    return base64.b64decode(argv[6]).decode("utf-16-le")


def test_cc_switch_runs_as_the_account_with_the_app_first():
    platform = RecordingPlatform(out="listed")

    assert session_on(platform).cc(["provider", "list"], "codex") == "listed"

    (run,) = platform.runs
    assert run["account"] == "ann"
    assert run["argv"] == [
        "/opt/neutrino/agent/bin/cc-switch",
        "--app",
        "codex",
        "provider",
        "list",
    ]


def test_a_refusal_is_the_command_s_own_error_unless_unchecked():
    platform = RecordingPlatform(code=1, err="no store")
    session = session_on(platform)

    with pytest.raises(subprocess.CalledProcessError) as caught:
        session.cc(["use", "x"], "claude")
    assert caught.value.stderr == "no store"
    assert session.cc(["use", "x"], "claude", is_checked=False) == ""


def test_the_delete_is_answered_on_a_terminal_as_the_account():
    platform = RecordingPlatform("windows")

    printed = session_on(platform, "C:\\Users\\ann", "pw").cc_answering(
        ["provider", "delete", "neutrino"], "claude", prompt="(y/N)", answer="y\n"
    )

    assert printed == "drawn"
    assert platform.answered == [
        (
            "ann",
            [
                "/opt/neutrino/agent/bin/cc-switch",
                "--app",
                "claude",
                "provider",
                "delete",
                "neutrino",
            ],
            "(y/N)",
            "y\n",
            "pw",
        )
    ]


def test_posix_files_are_reached_with_the_system_s_own_tools():
    platform = RecordingPlatform(out="text")
    session = session_on(platform)
    path = session.path(".claude", "settings.json")

    assert session.read_text(path) == "text"
    assert session.is_file(path) is True
    session.write_text(path, "{}")
    session.remove(path)

    assert [run["argv"][:2] for run in platform.runs] == [
        ["cat", "--"],
        ["test", "-f"],
        ["sh", "-c"],
        ["rm", "-f"],
    ]
    assert all(
        run["argv"][-1] == "/home/ann/.claude/settings.json" for run in platform.runs
    )
    assert platform.runs[2]["stdin"] == "{}"


def test_an_absent_file_reads_empty():
    platform = RecordingPlatform(code=1, out="cat: no such file")

    assert session_on(platform).read_text("/home/ann/x") == ""
    assert session_on(platform).is_file("/home/ann/x") is False


def test_windows_files_are_reached_by_powershell_with_the_path_as_a_literal():
    platform = RecordingPlatform("windows")
    session = session_on(platform, "C:\\Users\\o'neil", "pw")
    path = session.path(".codex", "config.toml")

    session.read_text(path)
    session.write_text(path, "model = 1")
    session.remove(path)

    assert path == "C:\\Users\\o'neil\\.codex\\config.toml"
    scripts = [script_of(run["argv"]) for run in platform.runs]
    literal = powershell_literal(path)
    assert literal == "'C:\\Users\\o''neil\\.codex\\config.toml'"
    assert all(literal in script for script in scripts)
    assert "ReadAllText" in scripts[0]
    assert "ReadToEnd" in scripts[1] and platform.runs[1]["stdin"] == "model = 1"
    assert "Remove-Item" in scripts[2]
    assert {run["password"] for run in platform.runs} == {"pw"}


def test_a_write_that_fails_is_switch_failed():
    platform = RecordingPlatform(code=1, err="read-only")

    with pytest.raises(ToolSwitchError) as caught:
        session_on(platform).write_text("/home/ann/x", "y")

    assert caught.value.code == "switch_failed"
    assert caught.value.params["account"] == "ann"
    assert "read-only" in caught.value.params["detail"]


def test_a_login_windows_refuses_is_credential_invalid():
    platform = RecordingPlatform(
        "windows", refusal=ModuleApplyError("credential_invalid", {"account": "x"})
    )

    with pytest.raises(ToolSwitchError) as caught:
        session_on(platform, "C:\\Users\\ann").cc(["provider", "list"], "claude")

    assert (caught.value.code, caught.value.params) == (
        "credential_invalid",
        {"account": "ann"},
    )


def test_a_run_that_cannot_start_is_switch_failed():
    platform = RecordingPlatform(refusal=OSError("runuser: user ann does not exist"))

    with pytest.raises(ToolSwitchError) as caught:
        session_on(platform).cc(["provider", "list"], "claude")

    assert caught.value.code == "switch_failed"
    assert "does not exist" in caught.value.params["detail"]
