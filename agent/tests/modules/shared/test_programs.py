"""The shared runner of the command line programs, against fake copies and a faked login shell.

What these pin: ``find`` reads the account's login shell's ``PATH`` before
the known places, passes over the module's own link and launcher, takes the
first copy whose ``--version`` prints a dotted number at the floor or newer,
reads ``copy_version_unsupported`` for an older one, leaves a shell that
fails or runs past its time to the known places with one line naming the
account and the shell, and plans the task again when what it finds changes
whether the module's copy is needed; the account step makes the link as the
account only where nothing stands, reads ``link_name_taken`` where something
does, makes and records ``~/.local/bin``, and takes the link away when the
account's own copy appears; on Windows the find and the ``PATH`` entry are
one run as the account each, the entry's change keeping every other entry;
``configure`` writes the launcher only beside the module's copy, Claude
Code's setting ``DISABLE_UPDATES=1``, and lets go of an account no longer
enabled; a read asks for a task once when a recorded copy went, fell below
the floor or its link was replaced, and keeps a new version of a supported
copy; an uninstall removes the module's directory and only the links that
carry the mark, a ``~/.local/bin`` it made only when empty, and no file of the
person's.
"""

import functools
import json
import os
import shutil
import stat
import subprocess

import pytest

from neutrino_agent.exceptions import ModuleApplyError, StepSuperseded
from neutrino_agent.modules.claude_code.hooks import ClaudeCodeHooks
from neutrino_agent.modules.codex.hooks import CodexHooks
from neutrino_agent.modules.shared.account_service import (
    AccountEntry,
    ServiceMachine,
)
from neutrino_agent.modules.shared.programs import (
    EXECUTABLES_SHELL,
    ProgramConfig,
    ProgramsModuleRunner,
    first_version,
    is_supported,
    launcher_text,
)
from neutrino_agent.modules.shared.subprocess_run import CommandResult
from neutrino_agent.platforms.base import (
    AgentPlatform,
    launcher_folders,
    with_launcher_folders,
)

pwsh = shutil.which("pwsh")
FLOOR = "2.0.0"


class Hooks(ClaudeCodeHooks):
    """Claude Code, its known places under the test's own folder."""

    known_places = {"linux": ("~/.local/bin/claude",), "windows": ("%X%\\claude.exe",)}


class Platform(AgentPlatform):
    """A machine whose login shells print a set PATH and whose other commands run for real, as the test's own user."""

    def __init__(self, root, os_name="linux"):
        self.os_name = os_name
        self.root = str(root)
        self.paths: dict = {}
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
        if argv[1:4] == ["-l", "-i", "-c"]:
            if self.shell_error is not None:
                raise self.shell_error
            return subprocess.CompletedProcess(
                list(argv), 0, f"welcome\n{self.paths.get(account, '')}\n", ""
            )
        env = dict(os.environ, **(environment or {}))
        return subprocess.run(
            argv, input=stdin, capture_output=True, text=True, env=env, timeout=30
        )


def entry_of(root):
    """Each account's home under the test's folder; ``ghost`` has none."""

    def lookup(account):
        if account == "ghost":
            raise KeyError(account)
        return AccountEntry(1000, 1000, os.path.join(str(root), "home", account), "")

    return lookup


def runner_for(tmp_path, os_name="linux", hooks=Hooks, recipe=None):
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
            lookup_account=entry_of(tmp_path),
        ),
    )
    runner.take_recipe(
        recipe
        if recipe is not None
        else {
            "runner": hooks.runner,
            "method": "hub",
            "params": {"version": "2.1.311", "user_copy_min_version": FLOOR},
        }
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
    """The module's own copy, unpacked."""
    copy_at(runner.program_path, "2.1.311")
    with open(
        os.path.join(runner.package_dir, "package.json"), "w", encoding="utf-8"
    ) as stream:
        stream.write('{"version": "2.1.311"}')


def home_of(tmp_path, account="ann"):
    return os.path.join(str(tmp_path), "home", account)


CONFIG = {"accounts": [{"account": "ann"}]}


def find(runner, config=CONFIG):
    """Run ``find`` with the basis the plan would have."""
    step = runner.find_step(config)
    try:
        step.run(None)
    except StepSuperseded:
        return "replanned"
    return "kept"


def records(runner):
    with open(runner.record_path, "r", encoding="utf-8") as stream:
        return json.load(stream)["accounts"]


# --- the pure parts ---


def test_a_version_is_the_first_dotted_number_and_the_floor_admits_it_or_newer():
    assert first_version("2.1.311 (Claude Code)") == "2.1.311"
    assert first_version("codex-cli 0.166.0") == "0.166.0"
    assert first_version("no version") == ""
    assert is_supported("2.1.311", "2.0.0") is True
    assert is_supported("2.0.0", "2.0.0") is True
    assert is_supported("1.9.10", "2.0.0") is False
    assert is_supported("2.10.0", "2.9.0") is True
    assert is_supported("", "2.0.0") is False
    assert is_supported("1.0.0", "") is True


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


def test_every_launcher_folder_ends_a_path_once_whether_installed_or_not():
    assert launcher_folders("/var/lib/neutrino/agent", "linux") == [
        "/var/lib/neutrino/agent/claude_code/bin",
        "/var/lib/neutrino/agent/codex/bin",
    ]
    ended = with_launcher_folders("/usr/bin:/bin", "/s", "linux")
    assert ended == "/usr/bin:/bin:/s/claude_code/bin:/s/codex/bin"
    assert with_launcher_folders(ended, "/s", "linux") == ended
    assert with_launcher_folders("", "/s", "linux") == "/s/claude_code/bin:/s/codex/bin"
    assert (
        with_launcher_folders("%PATH%", "C:\\s", "windows")
        == "%PATH%;C:\\s\\claude_code\\bin;C:\\s\\codex\\bin"
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


# --- the find ---


def test_the_login_shell_s_path_comes_before_the_known_places(tmp_path):
    runner, platform = runner_for(tmp_path)
    home = home_of(tmp_path)
    first = copy_at(os.path.join(str(tmp_path), "nvm", "bin", "claude"), "2.1.300")
    copy_at(os.path.join(home, ".local", "bin", "claude"), "2.1.311")
    platform.paths["ann"] = f"/nowhere:{os.path.dirname(first)}"

    assert find(runner) == "replanned"

    record = records(runner)["ann"]
    assert record["copy"] == "user"
    assert (record["path"], record["version"]) == (first, "2.1.300")
    shell = platform.runs[0]
    assert shell["argv"] == ["/bin/sh", "-l", "-i", "-c", 'printf "%s\\n" "$PATH"']
    assert (shell["stdin"], shell["timeout_s"]) == ("", 5)
    version = next(run for run in platform.runs if run["argv"][-1] == "--version")
    assert version["timeout_s"] == 10
    assert version["environment"] == {"PATH": platform.paths["ann"]}


def test_the_module_s_own_link_and_launcher_are_passed_over(tmp_path):
    runner, platform = runner_for(tmp_path)
    module_copy(runner)
    runner.apply(CONFIG)
    home = home_of(tmp_path)
    link = os.path.join(home, ".local", "bin", "claude")
    os.makedirs(os.path.dirname(link))
    os.symlink(runner.launcher_path, link)
    own = copy_at(os.path.join(str(tmp_path), "later", "claude"), "2.1.320")
    platform.paths["ann"] = ":".join(
        [os.path.dirname(link), runner.launcher_dir, os.path.dirname(own)]
    )

    find(runner)

    assert records(runner)["ann"]["path"] == own


def test_an_older_copy_reads_copy_version_unsupported_and_uses_the_module_s(tmp_path):
    runner, platform = runner_for(tmp_path)
    old = copy_at(os.path.join(home_of(tmp_path), ".local", "bin", "claude"), "1.0.9")
    platform.paths["ann"] = ""

    assert find(runner) == "kept"

    record = records(runner)["ann"]
    assert record["copy"] == "module"
    assert record["path"] == runner.launcher_path
    assert (record["code"], record["params"]) == (
        "copy_version_unsupported",
        {"account": "ann", "version": "1.0.9", "min": FLOOR},
    )
    assert os.path.isfile(old)


@pytest.mark.parametrize(
    "error",
    [subprocess.TimeoutExpired(["zsh"], 5), OSError("no such shell")],
)
def test_a_shell_that_fails_or_runs_past_its_time_leaves_the_known_places(
    tmp_path, error
):
    runner, platform = runner_for(tmp_path)
    platform.shell_error = error
    known = copy_at(os.path.join(home_of(tmp_path), ".local", "bin", "claude"))

    find(runner)

    assert records(runner)["ann"]["path"] == known
    assert any("ann" in line and "/bin/sh" in line for line in LOG)


def test_a_copy_whose_version_cannot_be_read_counts_as_not_found(tmp_path):
    runner, platform = runner_for(tmp_path)
    broken = os.path.join(str(tmp_path), "broken", "claude")
    os.makedirs(os.path.dirname(broken))
    with open(broken, "w", encoding="utf-8") as stream:
        stream.write("#!/bin/sh\nexit 3\n")
    os.chmod(broken, 0o755)
    known = copy_at(os.path.join(home_of(tmp_path), ".local", "bin", "claude"))
    platform.paths["ann"] = os.path.dirname(broken)

    find(runner)

    assert records(runner)["ann"]["path"] == known


def test_a_file_the_account_cannot_run_is_no_copy(tmp_path):
    runner, platform = runner_for(tmp_path)
    plain = copy_at(os.path.join(str(tmp_path), "plain", "claude"))
    os.chmod(plain, 0o644)
    platform.paths["ann"] = os.path.dirname(plain)

    assert find(runner) == "kept"

    assert records(runner)["ann"]["copy"] == "module"
    sh = next(run for run in platform.runs if run["argv"][:2] == ["/bin/sh", "-c"])
    assert sh["argv"][2] == EXECUTABLES_SHELL


def test_find_plans_again_only_when_the_need_for_the_module_s_copy_changes(tmp_path):
    runner, platform = runner_for(tmp_path)
    assert runner.needs_module_copy(CONFIG) is True
    assert find(runner) == "kept"

    copy_at(os.path.join(home_of(tmp_path), ".local", "bin", "claude"))
    assert find(runner) == "replanned"
    assert runner.needs_module_copy(CONFIG) is False
    assert find(runner) == "kept"
    assert runner.needs_module_copy({"accounts": []}) is True


def test_an_account_the_machine_does_not_have_is_refused(tmp_path):
    runner, _platform = runner_for(tmp_path)
    with pytest.raises(ModuleApplyError) as refused:
        find(runner, {"accounts": [{"account": "ghost"}]})
    assert refused.value.code == "account_no_profile" or refused.value.code == (
        "account_unknown"
    )


# --- the launcher and the link ---


def test_configure_writes_the_launcher_beside_the_module_s_copy_alone(tmp_path):
    runner, platform = runner_for(tmp_path)
    runner.apply(CONFIG)
    assert not os.path.exists(runner.launcher_path)

    module_copy(runner)
    runner.apply(CONFIG)

    with open(runner.launcher_path, "r", encoding="utf-8") as stream:
        text = stream.read()
    assert "DISABLE_UPDATES=1\nexport DISABLE_UPDATES\n" in text
    assert f'exec "{runner.program_path}" "$@"' in text
    assert stat.S_IMODE(os.stat(runner.launcher_path).st_mode) == 0o755
    assert os.listdir(runner.launcher_dir) == ["claude"]
    assert runner.launcher_dir in platform.labelled
    assert runner.module_dir in platform.opened


def test_the_link_is_made_as_the_account_only_where_nothing_stands(tmp_path):
    runner, platform = runner_for(tmp_path)
    runner.take_config(CONFIG)
    module_copy(runner)
    runner.apply(CONFIG)
    find(runner)
    home = home_of(tmp_path)
    os.makedirs(home)

    step = runner.configure_steps(CONFIG, "running", [])[1]
    assert (step.name, step.params) == ("account", {"account": "ann"})
    step.run(None)

    link = os.path.join(home, ".local", "bin", "claude")
    assert os.readlink(link) == runner.launcher_path
    record = records(runner)["ann"]
    assert (record["is_link_made"], record["is_local_bin_made"]) == (True, True)
    assert platform.runs[-1]["account"] == "ann"
    assert runner.details(runner._recipe)["accounts"] == [
        {
            "account": "ann",
            "copy": "module",
            "path": runner.launcher_path,
            "version": "2.1.311",
            "code": "",
            "params": {},
        }
    ]


def test_a_name_that_is_taken_stays_the_person_s_and_reads_link_name_taken(tmp_path):
    runner, platform = runner_for(tmp_path)
    module_copy(runner)
    runner.apply(CONFIG)
    find(runner)
    link = os.path.join(home_of(tmp_path), ".local", "bin", "claude")
    os.makedirs(os.path.dirname(link))
    with open(link, "w", encoding="utf-8") as stream:
        stream.write("the person's own")

    runner.configure_steps(CONFIG, "running", [])[1].run(None)

    with open(link, "r", encoding="utf-8") as stream:
        assert stream.read() == "the person's own"
    record = records(runner)["ann"]
    assert record["is_link_made"] is False
    assert record["is_local_bin_made"] is False
    assert (record["code"], record["params"]) == (
        "link_name_taken",
        {"account": "ann", "path": link},
    )


def test_the_link_goes_when_the_account_s_own_copy_appears(tmp_path):
    runner, platform = runner_for(tmp_path)
    module_copy(runner)
    runner.apply(CONFIG)
    find(runner)
    account_step = runner.configure_steps(CONFIG, "running", [])[1]
    os.makedirs(home_of(tmp_path))
    account_step.run(None)
    local_bin = os.path.join(home_of(tmp_path), ".local", "bin")
    own = copy_at(os.path.join(str(tmp_path), "own", "claude"), "2.2.0")
    platform.paths["ann"] = os.path.dirname(own)

    assert find(runner) == "replanned"
    account_step.run(None)

    assert not os.path.lexists(os.path.join(local_bin, "claude"))
    assert not os.path.exists(local_bin)
    record = records(runner)["ann"]
    assert (record["copy"], record["path"], record["is_link_made"]) == (
        "user",
        own,
        False,
    )
    assert os.path.isfile(own)


def test_configure_lets_go_of_an_account_no_longer_enabled(tmp_path):
    runner, platform = runner_for(tmp_path)
    module_copy(runner)
    runner.apply(CONFIG)
    find(runner)
    os.makedirs(os.path.join(home_of(tmp_path), ".local", "bin"))
    runner.configure_steps(CONFIG, "running", [])[1].run(None)
    link = os.path.join(home_of(tmp_path), ".local", "bin", "claude")
    assert os.path.islink(link)

    runner.apply({"accounts": []})

    assert not os.path.lexists(link)
    assert os.path.isdir(os.path.dirname(link))
    assert records(runner) == {}


# --- the read ---


def test_a_read_asks_once_when_a_copy_goes_or_falls_below_the_floor(tmp_path):
    runner, platform = runner_for(tmp_path)
    runner.take_config(CONFIG)
    own = copy_at(os.path.join(home_of(tmp_path), ".local", "bin", "claude"))
    find(runner)
    assert runner.has_person_copies() is True
    assert runner.asked == []

    copy_at(own, "2.2.5")
    os.utime(own, ns=(1, 1))
    assert runner.has_person_copies() is True
    assert records(runner)["ann"]["version"] == "2.2.5"
    assert runner.asked == []

    copy_at(own, "1.0.0")
    os.utime(own, ns=(2, 2))
    assert runner.has_person_copies() is False
    assert runner.has_person_copies() is False
    assert runner.asked == [True]

    os.unlink(own)
    assert runner.has_person_copies() is False
    assert runner.asked == [True, True]


def test_a_read_asks_when_the_link_no_longer_points_at_the_launcher(tmp_path):
    runner, platform = runner_for(tmp_path)
    runner.take_config(CONFIG)
    module_copy(runner)
    runner.apply(CONFIG)
    find(runner)
    os.makedirs(home_of(tmp_path))
    runner.configure_steps(CONFIG, "running", [])[1].run(None)
    runner.details(runner._recipe)
    assert runner.asked == []

    link = os.path.join(home_of(tmp_path), ".local", "bin", "claude")
    os.unlink(link)
    os.symlink("/opt/the-publisher/claude", link)
    runner.details(runner._recipe)
    runner.details(runner._recipe)

    assert runner.asked == [True]
    runner.details({})
    assert runner.asked == [True]


# --- the uninstall ---


def test_an_uninstall_removes_the_module_s_files_and_marked_links_alone(tmp_path):
    runner, platform = runner_for(tmp_path)
    config = {"accounts": [{"account": "ann"}, {"account": "bob"}]}
    runner.take_config(config)
    module_copy(runner)
    runner.apply(config)
    find(runner, config)
    os.makedirs(os.path.join(home_of(tmp_path, "ann"), ".local", "bin"))
    os.makedirs(home_of(tmp_path, "bob"))
    for step in runner.configure_steps(config, "running", [])[1:]:
        step.run(None)
    ann_link = os.path.join(home_of(tmp_path, "ann"), ".local", "bin", "claude")
    bob_bin = os.path.join(home_of(tmp_path, "bob"), ".local", "bin")
    with open(os.path.join(bob_bin, "notes"), "w", encoding="utf-8") as stream:
        stream.write("the person's")
    os.unlink(ann_link)
    copy_at(ann_link, "2.3.0")

    runner.uninstall({})

    assert not os.path.exists(runner.module_dir)
    assert os.path.isfile(ann_link)
    assert os.path.isdir(os.path.join(home_of(tmp_path, "ann"), ".local", "bin"))
    assert not os.path.lexists(os.path.join(bob_bin, "claude"))
    assert os.listdir(bob_bin) == ["notes"]


def test_a_journal_is_the_agent_s_own_lines_that_name_the_module(tmp_path):
    lines = [
        "2026-11-04T01:00:00 neutrino_agent: claude_code: ann runs its own copy",
        "2026-11-04T01:00:01 neutrino_agent: codeg: started",
        "2026-11-04T01:00:02 neutrino_agent: claude_code task: step 1/3: find",
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


def test_windows_finds_with_one_run_as_the_account_and_keeps_its_login(tmp_path):
    runner, platform = runner_for(tmp_path, "windows")
    own = copy_at(os.path.join(str(tmp_path), "own.exe"))
    platform.answers = [answer(path=own, version="2.1.311")]

    find(runner, WINDOWS_CONFIG)

    (run,) = platform.runs
    assert run["account"] == "ann" and run["password"] == "pw"
    assert run["argv"][:2] == ["powershell.exe", "-NoProfile"]
    assert run["argv"][-1].endswith(os.path.join("data", "windows", "program_find.ps1"))
    assert json.loads(run["stdin"]) == {
        "name": "claude",
        "skip": runner.launcher_dir,
        "places": ["%X%\\claude.exe"],
    }
    record = records(runner)["ann"]
    assert (record["copy"], record["path"], record["password"]) == ("user", own, "pw")
    assert runner.icacls and runner.icacls[0][2:4] == ["/inheritance:r", "/grant:r"]


def test_windows_adds_the_launcher_folder_to_the_user_path_as_the_account(tmp_path):
    runner, platform = runner_for(tmp_path, "windows")
    platform.answers = [answer(path="", version=""), answer(result="added")]
    find(runner, WINDOWS_CONFIG)

    runner.configure_steps(WINDOWS_CONFIG, "running", [])[1].run(None)

    run = platform.runs[-1]
    assert run["argv"][-1].endswith(os.path.join("data", "windows", "program_path.ps1"))
    assert json.loads(run["stdin"]) == {"verb": "add", "folder": runner.launcher_dir}
    assert records(runner)["ann"]["is_link_made"] is True

    platform.answers = [answer(result="removed")]
    runner.take_config({"accounts": []})
    assert runner.remove_ways_in() == ["claude_code: removed the way in of ann"]
    assert json.loads(platform.runs[-1]["stdin"])["verb"] == "remove"
    assert platform.runs[-1]["password"] == "pw"


CHANGED_PATH_DRIVER = """
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:SCRIPT, [ref]$null, [ref]$null)
$function = $ast.FindAll({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Get-ChangedPath' }, $true)[0]
. ([scriptblock]::Create($function.Extent.Text))
$cases = Get-Content -Raw -LiteralPath $env:CASES | ConvertFrom-Json
$answers = foreach ($case in $cases) { $changed = Get-ChangedPath $case[0] $case[1] $case[2]; if ($null -eq $changed) { '<same>' } else { $changed } }
$answers | ConvertTo-Json -Compress
"""


def test_the_user_path_entry_keeps_every_other_entry_byte_for_byte(tmp_path):
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
        [held, folder, "add"],
        [held + ";", folder, "add"],
        ["", folder, "add"],
        [held + ";" + folder, folder, "add"],
        [held + ";" + folder.upper() + "\\", folder, "add"],
        [held + ";" + folder, folder, "remove"],
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
        held + ";" + folder,
        held + ";" + folder,
        folder,
        "<same>",
        "<same>",
        held,
        "<same>",
    ]


class CodexAt(CodexHooks):
    """Codex, its known places under the test's own folder."""

    known_places = {"linux": ("~/.local/bin/codex",)}


def test_a_local_bin_either_program_made_goes_with_the_last_link_in_it(
    monkeypatch, tmp_path
):
    from neutrino_agent.modules.codex import hooks as codex_hooks

    monkeypatch.setattr(codex_hooks, "platform_tuple", lambda: {"arch": "amd64"})
    claude, _platform = runner_for(tmp_path)
    codex, _other = runner_for(tmp_path, hooks=CodexAt)
    os.makedirs(home_of(tmp_path))
    local_bin = os.path.join(home_of(tmp_path), ".local", "bin")
    for runner in (claude, codex):
        runner.take_config(CONFIG)
        module_copy(runner)
        runner.apply(CONFIG)
        find(runner)
        runner.configure_steps(CONFIG, "running", [])[1].run(None)
    assert records(claude)["ann"]["is_local_bin_made"] is True
    assert records(codex)["ann"]["is_local_bin_made"] is True

    claude.uninstall({})
    assert os.listdir(local_bin) == ["codex"]

    codex.uninstall({})
    assert not os.path.exists(local_bin)
