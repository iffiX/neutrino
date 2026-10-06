"""Reaching an account: cc-switch and the account's own files, as the account.

What these pin: cc-switch runs as the account with the app selector first;
a refusal is the command's own error and its words; the delete is answered
on a terminal with the client's prompt and answer; on Linux and macOS a
file is read with ``cat``, tested with ``test -f``, written by ``sh`` from
standard input and removed with ``rm -f``; on Windows each is a PowerShell
script naming the path as a literal; the login rides along on Windows; a
login Windows refuses is ``credential_invalid``; anything else that stops a
run is ``switch_failed`` with the account. The payload lives in the
account's own Neutrino tree on each system, and its removal, as the
account, takes the tree's directories left empty and stops at the first
that holds anything else.
"""

import base64
import shutil
import subprocess

import pytest

from neutrino_agent.ai_tools.account_session import (
    POSIX_REMOVE_SHELL,
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

    def run_as_account(
        self, account, argv, *, stdin="", timeout_s=0, password="", environment=None
    ):
        self.runs.append(
            {
                "environment": environment,
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
        self,
        account,
        argv,
        *,
        prompt,
        answer,
        timeout_s=0,
        password="",
        environment=None,
    ):
        self.answered.append((account, list(argv), prompt, answer, password))
        self.answered_environment = environment
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


@pytest.mark.parametrize(
    "os_name,home,path",
    [
        (
            "linux",
            "/home/ann",
            "/home/ann/.local/share/neutrino/agent/ai_tools/payload",
        ),
        (
            "darwin",
            "/Users/ann",
            "/Users/ann/Library/Application Support/Neutrino/agent/ai_tools/payload",
        ),
        (
            "windows",
            "C:\\Users\\ann",
            "C:\\Users\\ann\\AppData\\Local\\Neutrino\\agent\\ai_tools\\payload",
        ),
    ],
)
def test_the_payload_lives_in_the_account_s_own_neutrino_tree(os_name, home, path):
    assert session_on(RecordingPlatform(os_name), home).payload_path() == path


def test_the_payload_is_removed_as_the_account_with_its_tree_deepest_first():
    platform = RecordingPlatform()

    session_on(platform).remove_payload()

    (run,) = platform.runs
    assert run["account"] == "ann"
    assert run["argv"][:3] == ["sh", "-c", POSIX_REMOVE_SHELL]
    assert run["argv"][4:] == [
        "/home/ann/.local/share/neutrino/agent/ai_tools/payload",
        "/home/ann/.local/share/neutrino/agent/ai_tools",
        "/home/ann/.local/share/neutrino/agent",
        "/home/ann/.local/share/neutrino",
    ]


def test_windows_removes_the_payload_and_its_empty_tree_by_powershell():
    platform = RecordingPlatform("windows")

    session_on(platform, "C:\\Users\\ann", "pw").remove_payload()

    script = script_of(platform.runs[0]["argv"])
    tree = "C:\\Users\\ann\\AppData\\Local\\Neutrino"
    assert powershell_literal(tree + "\\agent\\ai_tools\\payload") in script
    dirs = [tree + "\\agent\\ai_tools", tree + "\\agent", tree]
    assert ", ".join(powershell_literal(d) for d in dirs) in script
    assert "Get-ChildItem" in script and "break" in script


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX shell")
@pytest.mark.parametrize(
    "kept,left",
    [
        (None, []),
        ("neutrino/agent/cloudcli", ["neutrino/agent"]),
        ("neutrino/client", ["neutrino"]),
    ],
)
def test_the_posix_removal_leaves_no_empty_neutrino_directory(tmp_path, kept, left):
    share = tmp_path / ".local" / "share"
    tree = share / "neutrino" / "agent" / "ai_tools"
    tree.mkdir(parents=True)
    (tree / "payload").write_text("{}")
    if kept:
        (share / kept).mkdir(parents=True, exist_ok=True)
    dirs = [str(tree), str(tree.parent), str(tree.parent.parent)]

    subprocess.run(
        ["sh", "-c", POSIX_REMOVE_SHELL, "sh", str(tree / "payload")] + dirs,
        check=True,
    )

    assert not tree.exists()
    assert share.exists()
    for name in left:
        assert (share / name).is_dir()
    if not kept:
        assert not (share / "neutrino").exists()


@pytest.mark.parametrize(
    "listed, bits",
    [
        ("-rw-r--r--", 0o644),
        ("-rw-------@", 0o600),
        ("-rwsr-x--x", 0o4751),
        ("-rw-r-Sr-T", 0o3644),
        ("short", None),
    ],
)
def test_ls_letters_read_as_permission_bits(listed, bits):
    from neutrino_agent.ai_tools.account_session import permission_bits

    assert permission_bits(listed) == bits


def test_a_mode_is_read_and_set_as_the_account_and_never_on_windows():
    platform = RecordingPlatform(out="-rw-r--r-- 1 1000 1000 30 Oct 6 auth.json\n")
    session = session_on(platform)

    assert session.mode_of("/home/ann/.codex/auth.json") == 0o644
    session.set_mode("/home/ann/.codex/auth.json", 0o600)

    assert [run["argv"][:2] for run in platform.runs] == [
        ["ls", "-ldn"],
        ["chmod", "600"],
    ]
    assert {run["account"] for run in platform.runs} == {"ann"}
    windows = RecordingPlatform("windows")
    assert session_on(windows, "C:\\Users\\ann").mode_of("C:\\x") is None
    session_on(windows, "C:\\Users\\ann").set_mode("C:\\x", 0o600)
    assert windows.runs == []


STORE = "/home/ann/.local/share/neutrino/agent/ai_tools/cc_switch"


def test_cc_switch_runs_on_the_store_in_the_account_s_neutrino_tree():
    platform = RecordingPlatform()
    session = session_on(platform)

    session.cc(["provider", "list"], "claude")
    session.cc_answering(
        ["provider", "delete", "neutrino"], "claude", prompt="(y/N)", answer="y\n"
    )
    session.is_own_store = False
    session.cc(["provider", "list"], "claude")

    assert session.store_path() == STORE
    assert platform.runs[0]["environment"] == {"CC_SWITCH_CONFIG_DIR": STORE}
    assert platform.answered_environment == {"CC_SWITCH_CONFIG_DIR": STORE}
    assert platform.runs[1]["environment"] is None


def test_the_store_is_made_the_account_s_alone_and_taken_away_with_its_empty_tree():
    platform = RecordingPlatform()
    session = session_on(platform)

    session.prepare_store()
    session.remove_store()

    made, removed = (run["argv"] for run in platform.runs)
    assert made[:2] == ["sh", "-c"] and "chmod 700" in made[2] and made[-1] == STORE
    assert "rm -rf" in removed[2] and removed[4] == STORE
    assert removed[5:] == [
        "/home/ann/.local/share/neutrino/agent/ai_tools",
        "/home/ann/.local/share/neutrino/agent",
        "/home/ann/.local/share/neutrino",
    ]
    assert {run["account"] for run in platform.runs} == {"ann"}
