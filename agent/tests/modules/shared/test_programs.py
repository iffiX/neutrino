"""The shared runner of the command line programs, against fake copies and a faked login shell.

What these pin: ``find`` reads the account's login shell's ``PATH`` before
the known places, passes over the module's launcher and says whether it
comes first, finds a copy that prints no version, and leaves a shell that
fails or runs past its time to the known places with one line naming the
account and the shell; the ``account`` step puts the module's copy first at
the account's first enabling alone, and reads ``copy_runs_first``,
``copy_unreached`` or on Windows ``copy_in_system_path`` without moving
anything; the ``find`` and ``prefer`` verbs; ``configure`` writes the
launcher beside the module's copy alone and lets go of an account no longer
enabled; a read asks for a task once when a startup file changed; on
Windows the find and the ``PATH`` entry are one run as the account each, the
entry's change keeping every other entry; and an uninstall removes the
module's directory and gives every account's ``PATH`` back.
"""

import functools
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


class Hooks(ClaudeCodeHooks):
    """Claude Code, its known places under the test's own folder."""

    known_places = {"linux": ("~/.local/bin/claude",), "windows": ("%X%\\claude.exe",)}


class Platform(AgentPlatform):
    """A machine whose login shells print a set PATH and whose other commands run for real, as the test's own user."""

    def __init__(self, root, os_name="linux"):
        self.os_name = os_name
        self.root = str(root)
        self.paths: dict = {}
        # The PATH of a shell that is no login shell, by account; the login
        # shell's where none is set.
        self.plain_paths: dict = {}
        self.shell_error = None
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
        if argv[1:4] == ["-l", "-i", "-c"] or argv[1:3] == ["-i", "-c"]:
            if self.shell_error is not None:
                raise self.shell_error
            printed = self.paths.get(account, "")
            if argv[1] == "-i":
                printed = self.plain_paths.get(account, printed)
            return subprocess.CompletedProcess(
                list(argv), 0, f"welcome\n{printed}\n", ""
            )
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


def runner_for(tmp_path, os_name="linux", hooks=Hooks, shell="/bin/bash"):
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
    asked: list = []
    runner.bind_configure_asker(functools.partial(asked.append, True))
    runner.asked = asked
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
    assert first_version("2.1.311 (Claude Code)") == "2.1.311"
    assert first_version("codex-cli 0.166.0") == "0.166.0"
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


# --- the find ---


def find(runner, account="ann", password=""):
    outcome = runner.command("find", {"account": account, "password": password})
    assert outcome["exit_code"] == 0, outcome
    return outcome["result"]


def test_the_login_shell_s_path_comes_before_the_known_places(tmp_path):
    runner, platform = runner_for(tmp_path)
    home = home_of(tmp_path)
    first = copy_at(os.path.join(str(tmp_path), "nvm", "bin", "claude"), "2.1.300")
    copy_at(os.path.join(home, ".local", "bin", "claude"), "2.1.311")
    platform.paths["ann"] = f"/nowhere:{os.path.dirname(first)}"

    assert find(runner) == {
        "path": first,
        "version": "2.1.300",
        "is_on_path": True,
        "is_system_path": False,
        "is_module_first": False,
    }
    shell = platform.runs[0]
    assert shell["argv"] == ["/bin/bash", "-l", "-i", "-c", 'printf "%s\\n" "$PATH"']
    assert (shell["stdin"], shell["timeout_s"]) == ("", 5)
    version = next(run for run in platform.runs if run["argv"][-1] == "--version")
    assert version["timeout_s"] == 10
    assert version["environment"] == {"PATH": platform.paths["ann"]}


def test_a_copy_in_the_known_places_alone_is_found_off_the_path(tmp_path):
    runner, platform = runner_for(tmp_path)
    own = copy_at(os.path.join(home_of(tmp_path), ".local", "bin", "claude"))
    platform.paths["ann"] = "/usr/bin"

    found = find(runner)

    assert (found["path"], found["is_on_path"]) == (own, False)


def test_the_module_s_launcher_is_passed_over_and_said_to_come_first(tmp_path):
    runner, platform = runner_for(tmp_path)
    module_copy(runner)
    behind = copy_at(os.path.join(str(tmp_path), "npm", "bin", "claude"), "2.0.1")
    platform.paths["ann"] = f"{runner.launcher_dir}:{os.path.dirname(behind)}"

    found = find(runner)

    assert (found["path"], found["is_module_first"]) == (behind, True)


def test_a_program_of_the_name_that_prints_no_version_is_still_found(tmp_path):
    runner, platform = runner_for(tmp_path)
    tool = os.path.join(home_of(tmp_path), ".local", "bin", "claude")
    os.makedirs(os.path.dirname(tool))
    with open(tool, "w", encoding="utf-8") as stream:
        stream.write('#!/bin/sh\necho "my own claude tool"\n')
    os.chmod(tool, 0o755)

    found = find(runner)

    assert (found["path"], found["version"]) == (tool, "")


def test_a_file_the_account_cannot_run_is_no_copy(tmp_path):
    runner, platform = runner_for(tmp_path)
    plain = os.path.join(home_of(tmp_path), ".local", "bin", "claude")
    os.makedirs(os.path.dirname(plain))
    with open(plain, "w", encoding="utf-8") as stream:
        stream.write("not a program")

    assert find(runner)["path"] == ""


@pytest.mark.parametrize(
    "error",
    [OSError("no shell"), subprocess.TimeoutExpired(["bash"], 5)],
    ids=["fails", "runs past its time"],
)
def test_a_shell_that_fails_or_runs_past_its_time_leaves_the_known_places(
    tmp_path, error
):
    runner, platform = runner_for(tmp_path)
    platform.shell_error = error
    own = copy_at(os.path.join(home_of(tmp_path), ".local", "bin", "claude"))

    assert find(runner)["path"] == own
    assert any("the login shell /bin/bash of ann gave no PATH" in line for line in LOG)


def test_the_find_verb_refuses_an_account_the_machine_does_not_have(tmp_path):
    runner, _platform = runner_for(tmp_path)

    outcome = runner.command("find", {"account": "ghost"})

    assert (outcome["code"], outcome["params"]) == (
        "account_unknown",
        {"account": "ghost"},
    )


# --- the account step ---


def test_the_first_enabling_puts_the_module_s_copy_first_and_reads_no_code(tmp_path):
    runner, platform = runner_for(tmp_path)
    module_copy(runner)
    platform.paths["ann"] = f"{runner.launcher_dir}:/usr/bin"

    account_step(runner)

    assert bashrc(tmp_path).endswith(b"# Neutrino\n")
    record = records(runner)["ann"]
    assert (record["is_path_set"], record["code"], record["params"]) == (True, "", {})
    assert sorted(record["stamps"]) == sorted(
        [
            os.path.join(home_of(tmp_path), ".bashrc"),
            os.path.join(home_of(tmp_path), ".profile"),
            os.path.join(
                home_of(tmp_path), ".local", "share", "neutrino", "agent", "env.sh"
            ),
        ]
    )
    assert runner.details(runner._recipe)["accounts"] == [
        {"account": "ann", "code": "", "params": {}}
    ]


def test_a_copy_the_shell_runs_first_reads_copy_runs_first_and_moves_nothing(
    tmp_path,
):
    runner, platform = runner_for(tmp_path)
    module_copy(runner)
    platform.paths["ann"] = f"{runner.launcher_dir}:/usr/bin"
    account_step(runner)
    with open(os.path.join(home_of(tmp_path), ".bashrc"), "ab") as stream:
        stream.write(b'export PATH="$HOME/.local/bin:$PATH"\n')
    after = bashrc(tmp_path)
    own = copy_at(os.path.join(home_of(tmp_path), ".local", "bin", "claude"), "2.1.400")
    platform.paths["ann"] = f"{os.path.dirname(own)}:{runner.launcher_dir}:/usr/bin"

    account_step(runner)

    assert bashrc(tmp_path) == after
    record = records(runner)["ann"]
    assert (record["code"], record["params"]) == (
        "copy_runs_first",
        {"account": "ann", "path": own, "version": "2.1.400"},
    )


def test_bash_s_shell_that_is_no_login_shell_is_read_too(tmp_path):
    """A line the person adds at the end of ``.bashrc`` puts their copy first in
    ``bash -i`` alone, where Debian's ``.profile`` runs the module's line last
    in a login shell."""
    runner, platform = runner_for(tmp_path)
    module_copy(runner)
    own = copy_at(os.path.join(home_of(tmp_path), ".local", "bin", "claude"), "2.1.400")
    platform.paths["ann"] = f"{runner.launcher_dir}:{os.path.dirname(own)}"
    platform.plain_paths["ann"] = f"{os.path.dirname(own)}:{runner.launcher_dir}"

    account_step(runner)

    shells = [run["argv"][1:3] for run in platform.runs if run["argv"][-2:-1] == ["-c"]]
    assert shells[:2] == [["-l", "-i"], ["-i", "-c"]]
    assert records(runner)["ann"]["params"] == {
        "account": "ann",
        "path": own,
        "version": "2.1.400",
    }
    assert records(runner)["ann"]["code"] == "copy_runs_first"


def test_a_shell_other_than_bash_is_read_as_a_login_shell_alone(tmp_path):
    runner, platform = runner_for(tmp_path, shell="/bin/zsh")
    module_copy(runner)
    platform.paths["ann"] = runner.launcher_dir
    platform.plain_paths["ann"] = "/usr/bin"

    account_step(runner)

    assert records(runner)["ann"]["code"] == ""
    assert not any(run["argv"][1:3] == ["-i", "-c"] for run in platform.runs)


def test_a_shell_that_finds_no_copy_reads_copy_unreached(tmp_path):
    runner, platform = runner_for(tmp_path)
    module_copy(runner)
    platform.paths["ann"] = "/usr/bin"

    account_step(runner)

    assert records(runner)["ann"]["code"] == "copy_unreached"


def test_prefer_moves_the_line_to_the_end_again_and_clears_the_code(tmp_path):
    runner, platform = runner_for(tmp_path)
    module_copy(runner)
    own = copy_at(os.path.join(home_of(tmp_path), ".local", "bin", "claude"), "2.1.400")
    platform.paths["ann"] = f"{os.path.dirname(own)}:{runner.launcher_dir}"
    account_step(runner)
    with open(os.path.join(home_of(tmp_path), ".bashrc"), "ab") as stream:
        stream.write(b"export PATH=$HOME/.local/bin:$PATH\n")
    assert records(runner)["ann"]["code"] == "copy_runs_first"
    platform.paths["ann"] = f"{runner.launcher_dir}:{os.path.dirname(own)}"

    outcome = runner.command("prefer", {"account": "ann"})

    assert outcome["exit_code"] == 0
    assert bashrc(tmp_path).endswith(
        b"export PATH=$HOME/.local/bin:$PATH\n"
        b'[ -f "$HOME/.local/share/neutrino/agent/env.sh" ] && '
        b'. "$HOME/.local/share/neutrino/agent/env.sh" # Neutrino\n'
    )
    assert records(runner)["ann"]["code"] == ""


def test_prefer_refuses_an_account_the_module_does_not_enable(tmp_path):
    runner, _platform = runner_for(tmp_path)
    runner.take_config(CONFIG)

    outcome = runner.command("prefer", {"account": "bob"})

    assert (outcome["exit_code"], outcome["code"], outcome["params"]) == (
        1,
        "account_not_enabled",
        {"account": "bob"},
    )


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


# --- the read ---


def test_a_read_asks_once_when_a_startup_file_changes(tmp_path):
    runner, platform = runner_for(tmp_path)
    module_copy(runner)
    platform.paths["ann"] = runner.launcher_dir
    account_step(runner)

    runner.details(runner._recipe)
    assert runner.asked == []

    with open(os.path.join(home_of(tmp_path), ".bashrc"), "ab") as stream:
        stream.write(b"export A=1\n")
    runner.details(runner._recipe)
    runner.details(runner._recipe)
    assert runner.asked == [True]

    account_step(runner)
    runner.details(runner._recipe)
    assert runner.asked == [True]


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
        hooks_class=Hooks,
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
NOT_FOUND = {
    "path": "",
    "version": "",
    "is_on_path": False,
    "is_system_path": False,
    "is_module_first": True,
}


def test_windows_finds_with_one_run_as_the_account(tmp_path):
    runner, platform = runner_for(tmp_path, "windows")
    platform.answers = [
        answer(
            path="C:\\Tools\\claude.exe",
            version="2.1.311",
            is_on_path=True,
            is_system_path=True,
            is_module_first=False,
        )
    ]

    found = find(runner, password="pw")

    (run,) = platform.runs
    assert run["account"] == "ann" and run["password"] == "pw"
    assert run["argv"][:2] == ["powershell.exe", "-NoProfile"]
    assert run["argv"][-1].endswith(os.path.join("data", "windows", "program_find.ps1"))
    assert json.loads(run["stdin"]) == {
        "name": "claude",
        "module_folder": runner.launcher_dir,
        "places": ["%X%\\claude.exe"],
    }
    assert (found["path"], found["is_system_path"]) == ("C:\\Tools\\claude.exe", True)
    assert runner.command("find", {"account": "ann"})["code"] == "credential_missing"


def test_windows_puts_the_launcher_folder_first_and_gives_the_value_back(tmp_path):
    runner, platform = runner_for(tmp_path, "windows")
    platform.answers = [answer(result="added", is_made=True), answer(**NOT_FOUND)]

    account_step(runner, WINDOWS_CONFIG)

    first = platform.runs[0]
    assert first["argv"][-1].endswith(
        os.path.join("data", "windows", "program_path.ps1")
    )
    assert json.loads(first["stdin"]) == {
        "verb": "first",
        "folder": runner.launcher_dir,
        "is_made": False,
    }
    record = records(runner)["ann"]
    assert (record["is_path_set"], record["is_value_made"], record["code"]) == (
        True,
        True,
        "",
    )
    assert record["password"] == "pw"
    assert runner.icacls and runner.icacls[0][2:4] == ["/inheritance:r", "/grant:r"]

    platform.answers = [answer(**NOT_FOUND)]
    account_step(runner, WINDOWS_CONFIG)
    assert json.loads(platform.runs[-1]["stdin"])["name"] == "claude"

    platform.answers = [answer(result="removed", is_made=False)]
    runner.take_config({"accounts": []})
    assert runner.remove_ways_in() == ["claude_code: gave back the PATH of ann"]
    assert json.loads(platform.runs[-1]["stdin"]) == {
        "verb": "remove",
        "folder": runner.launcher_dir,
        "is_made": True,
    }
    assert platform.runs[-1]["password"] == "pw"


def test_windows_reads_a_copy_in_the_system_path(tmp_path):
    runner, platform = runner_for(tmp_path, "windows")
    platform.answers = [
        answer(result="added", is_made=False),
        answer(
            path="C:\\Tools\\claude.exe",
            version="2.1.400",
            is_on_path=True,
            is_system_path=True,
            is_module_first=False,
        ),
    ]

    account_step(runner, WINDOWS_CONFIG)

    record = records(runner)["ann"]
    assert (record["code"], record["params"]) == (
        "copy_in_system_path",
        {"account": "ann", "path": "C:\\Tools\\claude.exe", "version": "2.1.400"},
    )


def test_windows_removes_an_account_s_entry_with_the_login_its_record_keeps(tmp_path):
    """module_template.md: the state names no login for an account it no
    longer enables, so the record's root-only login removes its entry."""
    runner, platform = runner_for(tmp_path, "windows")
    platform.answers = [answer(result="added", is_made=False), answer(**NOT_FOUND)]
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
    assert runner.details({}) == {
        "has_module_copy": False,
        "version": "",
        "accounts": [],
    }
    module_copy(runner)

    assert runner.details({})["version"] == "2.1.311"
