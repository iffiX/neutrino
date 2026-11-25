"""The shared runner of the command line programs, against fake copies.

What these pin: the ``account`` step puts the module's copy first at the
account's first enabling alone and keeps no code for the account;
``configure`` writes the launcher beside the module's copy alone and lets go
of an account no longer enabled; the runner has no verb of its own; on
Windows the ``PATH`` entry is one run as the account, the entry's change
keeping every other entry; and an uninstall removes the module's directory
and gives every account's ``PATH`` back.
"""

import json
import os
import shutil
import stat
import subprocess

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.claude_code.hooks import ClaudeCodeHooks
from neutrino_agent.modules.codex.hooks import CodexHooks
from neutrino_agent.modules.opencode.hooks import OpencodeHooks
from neutrino_agent.modules.shared.account_service import (
    AccountEntry,
    ServiceMachine,
)
from neutrino_agent.modules.shared.programs import (
    ProgramConfig,
    ProgramsModuleRunner,
    first_version,
    launcher_text,
)
from neutrino_agent.modules.shared.subprocess_run import CommandResult
from neutrino_agent.platforms.base import (
    AgentPlatform,
    launcher_folders,
    with_launcher_folders,
)

pwsh = shutil.which("pwsh")


class Platform(AgentPlatform):
    """A machine whose commands run for real as the test's own user, and whose Windows runs answer what the test sets."""

    def __init__(self, root, os_name="linux"):
        self.os_name = os_name
        self.root = str(root)
        self.runs: list = []
        self.answers: list = []
        self.labelled: list = []
        self.opened: list = []

    def agent_var_dir(self) -> str:
        return os.path.join(self.root, "state")

    def has_account(self, account):
        return account != "ghost"

    def label_programs(self, path):
        self.labelled.append(path)

    def open_to_accounts(self, directory):
        self.opened.append(directory)

    def account_process(self, account, argv):
        return list(argv), {}

    def run_as_account(
        self, account, argv, *, stdin="", timeout_s=0, password="", environment=None
    ):
        self.runs.append(
            {
                "account": account,
                "argv": list(argv),
                "stdin": stdin,
                "timeout_s": timeout_s,
                "password": password,
                "environment": environment,
            }
        )
        if self.os_name == "windows":
            answer = self.answers.pop(0)
            return subprocess.CompletedProcess(list(argv), 0, answer, "")
        env = dict(os.environ, **(environment or {}))
        return subprocess.run(
            argv, input=stdin, capture_output=True, text=True, env=env, timeout=30
        )


def entry_of(root, shell="/bin/bash"):
    """Each account's home under the test's folder; ``ghost`` has none."""

    def lookup(account):
        if account == "ghost":
            raise KeyError(account)
        home = os.path.join(str(root), "home", account)
        os.makedirs(home, exist_ok=True)
        return AccountEntry(1000, 1000, home, shell)

    return lookup


def runner_for(tmp_path, os_name="linux", hooks=ClaudeCodeHooks, shell="/bin/bash"):
    platform = Platform(tmp_path, os_name)
    icacls: list = []

    def run(command, **kwargs):
        icacls.append(list(command))
        return CommandResult(list(command), 0, "", "")

    runner = ProgramsModuleRunner(
        hooks_class=hooks,
        platform=platform,
        log=LOG.append,
        run=run,
        machine=ServiceMachine(
            os_name=os_name,
            module_dir=os.path.join(platform.agent_var_dir(), hooks.name),
            record_dir=os.path.join(platform.agent_var_dir(), hooks.name),
            lookup_account=entry_of(tmp_path, shell),
        ),
    )
    runner.take_recipe(
        {"runner": hooks.runner, "method": "hub", "params": {"version": "2.1.311"}}
    )
    runner.icacls = icacls
    return runner, platform


LOG: list = []


@pytest.fixture(autouse=True)
def clear_log():
    LOG.clear()


def copy_at(path, version="2.1.311"):
    """A fake copy that prints its version."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as stream:
        stream.write(f'#!/bin/sh\necho "{version} (Claude Code)"\n')
    os.chmod(path, 0o755)
    return path


def module_copy(runner):
    """The module's own copy, unpacked, and its launcher."""
    copy_at(runner.program_path, "2.1.311")
    with open(
        os.path.join(runner.package_dir, "package.json"), "w", encoding="utf-8"
    ) as stream:
        stream.write('{"version": "2.1.311"}')
    runner.apply({"accounts": []})


def home_of(tmp_path, account="ann"):
    return os.path.join(str(tmp_path), "home", account)


CONFIG = {"accounts": [{"account": "ann"}]}


def account_step(runner, config=CONFIG, index=1):
    runner.take_config(config)
    runner.configure_steps(config, "running", [])[index].run(None)


def records(runner):
    with open(runner.record_path, "r", encoding="utf-8") as stream:
        return json.load(stream)["accounts"]


def bashrc(tmp_path) -> bytes:
    with open(os.path.join(home_of(tmp_path), ".bashrc"), "rb") as stream:
        return stream.read()


# --- the pure parts ---


def test_a_version_is_the_first_dotted_number():
    assert first_version("2.1.311") == "2.1.311"
    assert first_version("v0.166.0-beta") == "0.166.0"
    assert first_version("no version") == ""


def test_the_launchers_are_pinned():
    assert launcher_text(
        "/var/lib/neutrino/agent/claude_code/package/claude",
        (("DISABLE_UPDATES", "1"),),
        "linux",
    ) == (
        "#!/bin/sh\n"
        "DISABLE_UPDATES=1\n"
        "export DISABLE_UPDATES\n"
        'exec "/var/lib/neutrino/agent/claude_code/package/claude" "$@"\n'
    )
    assert launcher_text(
        "C:\\ProgramData\\Neutrino\\agent\\state\\claude_code\\package\\claude.exe",
        (("DISABLE_UPDATES", "1"),),
        "windows",
    ) == (
        "@echo off\r\n"
        "setlocal\r\n"
        'set "DISABLE_UPDATES=1"\r\n'
        '"C:\\ProgramData\\Neutrino\\agent\\state\\claude_code\\package\\claude.exe" %*\r\n'
        "exit /b %ERRORLEVEL%\r\n"
    )
    assert launcher_text(
        "/var/lib/neutrino/agent/codex/package/vendor/x/bin/codex", (), "linux"
    ) == (
        "#!/bin/sh\n"
        'exec "/var/lib/neutrino/agent/codex/package/vendor/x/bin/codex" "$@"\n'
    )


def test_the_launcher_folders_of_an_account_s_programs_start_its_path_once():
    assert launcher_folders("/v", "linux", ("codex", "claude_code", "x")) == [
        "/v/claude_code/bin",
        "/v/codex/bin",
    ]
    started = with_launcher_folders(
        "/usr/bin:/v/codex/bin:/bin", "/v", "linux", ("codex",)
    )
    assert started == "/v/codex/bin:/usr/bin:/bin"
    assert with_launcher_folders(started, "/v", "linux", ("codex",)) == started
    assert with_launcher_folders("/usr/bin", "/v", "linux", ()) == "/usr/bin"
    assert with_launcher_folders("", "/v", "linux", ("codex",)) == "/v/codex/bin"
    assert (
        with_launcher_folders("%PATH%", "C:\\s", "windows", ("claude_code",))
        == "C:\\s\\claude_code\\bin;%PATH%"
    )


def test_the_configuration_refuses_a_bad_or_doubled_account_and_on_windows_one_with_no_login():
    with pytest.raises(ModuleApplyError) as refused:
        ProgramConfig.from_dict({"accounts": [{"account": "a b"}]}).validate()
    assert refused.value.code == "account_invalid"
    with pytest.raises(ModuleApplyError) as refused:
        ProgramConfig.from_dict(
            {"accounts": [{"account": "ann"}, {"account": "Ann"}]}
        ).validate()
    assert refused.value.code == "account_duplicate"
    with pytest.raises(ModuleApplyError) as refused:
        ProgramConfig.from_dict({"accounts": [{"account": "ann"}]}).validate(
            os_name="windows"
        )
    assert (refused.value.code, refused.value.params) == (
        "credential_missing",
        {"account": "ann"},
    )


def test_codex_s_program_sits_under_its_target(monkeypatch, tmp_path):
    from neutrino_agent.modules.codex import hooks as codex_hooks

    monkeypatch.setattr(codex_hooks, "platform_tuple", lambda: {"arch": "arm64"})
    runner, _platform = runner_for(tmp_path, hooks=CodexHooks)
    assert runner.program_path.endswith(
        "codex/package/vendor/aarch64-unknown-linux-musl/bin/codex"
    )
    assert runner.launcher_path.endswith("codex/bin/codex")


def test_a_program_plans_configure_and_one_account_step_each_and_no_start(tmp_path):
    runner, _platform = runner_for(tmp_path)

    steps = runner.configure_steps(
        {"accounts": [{"account": "ann"}, {"account": "bob"}]}, "running", []
    )

    assert [(step.name, step.params) for step in steps] == [
        ("configure", {}),
        ("account", {"account": "ann"}),
        ("account", {"account": "bob"}),
    ]


# --- the account step ---


def test_the_first_enabling_puts_the_module_s_copy_first_and_keeps_no_code(tmp_path):
    runner, _platform = runner_for(tmp_path)
    module_copy(runner)

    account_step(runner)

    assert bashrc(tmp_path).endswith(b"# Neutrino\n")
    assert records(runner) == {"ann": {"account": "ann", "is_path_set": True}}
    assert runner.details(runner._recipe) == {
        "has_module_copy": True,
        "version": "2.1.311",
    }


def test_a_later_account_step_moves_no_line_the_person_added_after(tmp_path):
    runner, _platform = runner_for(tmp_path)
    module_copy(runner)
    account_step(runner)
    with open(os.path.join(home_of(tmp_path), ".bashrc"), "ab") as stream:
        stream.write(b'export PATH="$HOME/.local/bin:$PATH"\n')
    after = bashrc(tmp_path)

    account_step(runner)

    assert bashrc(tmp_path) == after
    assert records(runner)["ann"]["is_path_set"] is True


def test_the_runner_has_no_verb_of_its_own(tmp_path):
    runner, _platform = runner_for(tmp_path)

    for verb in ("find", "prefer"):
        closed = runner.command(verb, {"account": "ann"})
        assert (closed["exit_code"], closed["code"]) == (1, "verb_unknown")


def test_an_account_the_machine_does_not_have_is_refused(tmp_path):
    runner, _platform = runner_for(tmp_path)
    config = {"accounts": [{"account": "ghost"}]}

    with pytest.raises(ModuleApplyError) as refused:
        account_step(runner, config)

    assert (refused.value.code, refused.value.params) == (
        "account_unknown",
        {"account": "ghost"},
    )


def test_configure_writes_the_launcher_beside_the_module_s_copy_alone(tmp_path):
    runner, platform = runner_for(tmp_path)
    runner.apply(CONFIG)
    assert not os.path.exists(runner.launcher_path)

    module_copy(runner)

    with open(runner.launcher_path, "r", encoding="utf-8") as stream:
        assert "DISABLE_UPDATES=1" in stream.read()
    assert stat.S_IMODE(os.stat(runner.launcher_path).st_mode) == 0o755
    assert os.listdir(runner.launcher_dir) == ["claude"]
    assert runner.launcher_dir in platform.labelled
    assert runner.module_dir in platform.opened


def test_configure_lets_go_of_an_account_no_longer_enabled(tmp_path):
    runner, platform = runner_for(tmp_path)
    module_copy(runner)
    os.makedirs(home_of(tmp_path))
    with open(os.path.join(home_of(tmp_path), ".bashrc"), "wb") as stream:
        stream.write(b"set -o vi\n")
    account_step(runner)

    runner.apply({"accounts": []})

    assert bashrc(tmp_path) == b"set -o vi\n"
    assert records(runner) == {}
    assert any("let go of ann" in line for line in LOG)


def test_the_second_program_shares_the_line_and_the_last_one_takes_it_away(
    monkeypatch, tmp_path
):
    from neutrino_agent.modules.codex import hooks as codex_hooks

    monkeypatch.setattr(codex_hooks, "platform_tuple", lambda: {"arch": "amd64"})
    claude, platform = runner_for(tmp_path)
    codex, _other = runner_for(tmp_path, hooks=CodexHooks)
    os.makedirs(home_of(tmp_path))
    with open(os.path.join(home_of(tmp_path), ".bashrc"), "wb") as stream:
        stream.write(b"set -o vi")
    local_bin = os.path.join(home_of(tmp_path), ".local", "bin")
    os.makedirs(local_bin)
    for runner in (claude, codex):
        module_copy(runner)
        account_step(runner)
    shared = bashrc(tmp_path)
    assert shared.count(b"# Neutrino") == 1

    claude.uninstall({})
    assert bashrc(tmp_path) == shared
    env = os.path.join(
        home_of(tmp_path), ".local", "share", "neutrino", "agent", "env.sh"
    )
    with open(env, "r", encoding="utf-8") as stream:
        assert "claude_code" not in stream.read()

    codex.uninstall({})
    assert bashrc(tmp_path) == b"set -o vi"
    assert not os.path.exists(os.path.join(home_of(tmp_path), ".profile"))
    assert not os.path.exists(env)
    assert os.listdir(local_bin) == []
    assert not os.path.exists(claude.module_dir)
    assert not os.path.exists(codex.module_dir)


# --- the journal ---


def test_a_journal_is_the_agent_s_own_lines_that_name_the_module(tmp_path):
    lines = [
        "2026-11-04T01:00:00 neutrino_agent: claude_code: ann runs the module's copy first",
        "2026-11-04T01:00:01 neutrino_agent: codeg: started",
        "2026-11-04T01:00:02 neutrino_agent: claude_code task: step 1/3: configure",
    ]
    asked = []

    def journal(units, count):
        asked.append((units, count))
        return lines

    runner = ProgramsModuleRunner(
        hooks_class=ClaudeCodeHooks,
        platform=Platform(tmp_path),
        log=LOG.append,
        journal=journal,
    )

    assert runner.journal_text(10) == [lines[0]]
    assert asked == [(["neutrino_agent.service"], 5000)]


# --- Windows ---


def answer(**fields) -> str:
    return "noise\n" + json.dumps(fields) + "\n"


WINDOWS_CONFIG = {"accounts": [{"account": "ann", "password": "pw"}]}


def test_windows_puts_the_launcher_folder_first_and_gives_the_value_back(tmp_path):
    runner, platform = runner_for(tmp_path, "windows")
    platform.answers = [answer(result="added", is_made=True)]

    account_step(runner, WINDOWS_CONFIG)

    (first,) = platform.runs
    assert first["argv"][-1].endswith(
        os.path.join("data", "windows", "program_path.ps1")
    )
    assert json.loads(first["stdin"]) == {
        "verb": "first",
        "folder": runner.launcher_dir,
        "is_made": False,
    }
    assert records(runner)["ann"] == {
        "account": "ann",
        "is_path_set": True,
        "is_value_made": True,
        "password": "pw",
    }
    assert runner.icacls and runner.icacls[0][2:4] == ["/inheritance:r", "/grant:r"]

    account_step(runner, WINDOWS_CONFIG)
    assert len(platform.runs) == 1
    assert records(runner)["ann"]["is_value_made"] is True

    platform.answers = [answer(result="removed", is_made=False)]
    runner.take_config({"accounts": []})
    assert runner.remove_ways_in() == ["claude_code: gave back the PATH of ann"]
    assert json.loads(platform.runs[-1]["stdin"]) == {
        "verb": "remove",
        "folder": runner.launcher_dir,
        "is_made": True,
    }
    assert platform.runs[-1]["password"] == "pw"


def test_windows_removes_an_account_s_entry_with_the_login_its_record_keeps(tmp_path):
    """module_template.md: the state names no login for an account it no
    longer enables, so the record's root-only login removes its entry."""
    runner, platform = runner_for(tmp_path, "windows")
    platform.answers = [answer(result="added", is_made=False)]
    account_step(runner, WINDOWS_CONFIG)
    platform.answers = [answer(result="removed", is_made=False)]

    runner.apply({"accounts": []})

    run = platform.runs[-1]
    assert json.loads(run["stdin"]) == {
        "verb": "remove",
        "folder": runner.launcher_dir,
        "is_made": False,
    }
    assert (run["account"], run["password"]) == ("ann", "pw")
    assert records(runner) == {}


CHANGED_PATH_DRIVER = """
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:SCRIPT, [ref]$null, [ref]$null)
$functions = $ast.FindAll({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and @('Test-Ours', 'Get-ChangedPath') -contains $node.Name }, $true)
foreach ($function in $functions) { . ([scriptblock]::Create($function.Extent.Text)) }
$cases = Get-Content -Raw -LiteralPath $env:CASES | ConvertFrom-Json
$answers = foreach ($case in $cases) { $changed = Get-ChangedPath $case[0] $case[1] $case[2]; if ($null -eq $changed) { '<same>' } else { $changed } }
$answers | ConvertTo-Json -Compress
"""


def test_the_user_path_entry_goes_first_and_keeps_every_other_entry_byte_for_byte(
    tmp_path,
):
    if pwsh is None:
        pytest.skip("PowerShell is not installed")
    script = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
        "neutrino_agent",
        "data",
        "windows",
        "program_path.ps1",
    )
    folder = "C:\\ProgramData\\Neutrino\\agent\\state\\claude_code\\bin"
    held = "%USERPROFILE%\\bin;C:\\Tools ;;%LOCALAPPDATA%\\x"
    cases = [
        [held, folder, "first"],
        [held + ";", folder, "first"],
        ["", folder, "first"],
        [folder + ";" + held, folder, "first"],
        [held + ";" + folder.upper() + "\\", folder, "first"],
        [folder + ";" + held, folder, "remove"],
        [folder + ";" + held + ";", folder, "remove"],
        [folder, folder, "remove"],
        [held, folder, "remove"],
    ]
    (tmp_path / "cases.json").write_text(json.dumps(cases))
    (tmp_path / "driver.ps1").write_text(CHANGED_PATH_DRIVER)
    done = subprocess.run(
        [pwsh, "-NoProfile", "-NonInteractive", "-File", str(tmp_path / "driver.ps1")],
        capture_output=True,
        text=True,
        env={
            "PATH": os.environ["PATH"],
            "HOME": str(tmp_path),
            "SCRIPT": script,
            "CASES": str(tmp_path / "cases.json"),
        },
        timeout=60,
    )

    assert json.loads(done.stdout.strip().splitlines()[-1]) == [
        folder + ";" + held,
        folder + ";" + held + ";",
        folder,
        "<same>",
        folder + ";" + held,
        held,
        held + ";",
        "",
        "<same>",
    ]


# --- the module's own copy ---


def test_codex_s_verify_runs_with_codex_home_in_the_module_s_folder(tmp_path):
    """codex.md: every start of Codex, ``--version`` too, writes under its
    home folder, so ``verify`` points it at ``verify_home`` in the module's
    directory and nothing lands in root's home. The folder is made only
    while the module's copy is there, so a read after an uninstall leaves no
    module directory behind."""
    runner, _platform = runner_for(tmp_path, hooks=CodexHooks)
    folder = os.path.join(runner.module_dir, "verify_home")

    assert runner.verify_environment() == {"CODEX_HOME": folder}
    assert not os.path.exists(runner.module_dir)

    copy_at(runner.program_path, "0.166.0")
    assert runner.verify_environment() == {"CODEX_HOME": folder}
    assert stat.S_IMODE(os.stat(folder).st_mode) == 0o700


def test_opencode_s_verify_runs_with_its_home_in_the_module_s_folder(tmp_path):
    """opencode.md: every start of OpenCode, ``--version`` too, makes its
    folders under the home folder it reads from ``HOME``, so ``verify``
    points that at ``verify_home`` in the module's directory and nothing
    lands in root's home."""
    runner, _platform = runner_for(tmp_path, hooks=OpencodeHooks)
    folder = os.path.join(runner.module_dir, "verify_home")

    assert runner.program_path.endswith("opencode/package/bin/opencode")
    assert runner.launcher_path.endswith("opencode/bin/opencode")
    assert runner.verify_environment() == {"HOME": folder}
    assert not os.path.exists(runner.module_dir)

    copy_at(runner.program_path, "1.19.5")
    assert runner.verify_environment() == {"HOME": folder}
    assert stat.S_IMODE(os.stat(folder).st_mode) == 0o700


def test_claude_code_s_verify_runs_with_no_variable_of_its_own(tmp_path):
    runner, _platform = runner_for(tmp_path)

    assert runner.verify_environment() == {}
    assert not os.path.exists(os.path.join(runner.module_dir, "verify_home"))


def test_the_details_name_the_module_copy_s_version(tmp_path):
    runner, _platform = runner_for(tmp_path)
    assert runner.details({}) == {"has_module_copy": False, "version": ""}
    module_copy(runner)

    assert runner.details({})["version"] == "2.1.311"
