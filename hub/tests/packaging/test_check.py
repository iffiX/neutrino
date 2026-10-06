"""The parts of ``packaging/ci/check.py`` the hub targets lean on.

The checks themselves install real packages on a runner; what is asserted
here is what they hand the hub and the install scripts: answers ``nhub
setup`` accepts, and a directory the scripts install from.
"""

import hashlib
import io
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest
from types import SimpleNamespace

from neutrino_hub.cli import wizard
from neutrino_hub.utils.passwords import (
    PASSWORDS_MASTER_RULES,
    PASSWORDS_PANEL_RULES,
    validate,
)

CHECK = Path(__file__).resolve().parents[3] / "packaging" / "ci" / "check.py"


@pytest.fixture(scope="module")
def check():
    spec = importlib.util.spec_from_file_location("ci_check", CHECK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_both_hub_targets_are_offered(check):
    assert {"hub_macos", "hub_windows"} <= set(check.CHECKS)


def test_the_setup_answers_are_a_server_hub_setup_accepts(check, monkeypatch):
    seen = []

    class Finished:
        returncode = 0

    def run(command, **kwargs):
        seen.append(json.loads(Path(command[-1]).read_text()))
        assert command[-3:-1] == ["setup", "--json"]
        return Finished()

    monkeypatch.setattr(check.subprocess, "run", run)

    check._set_up_hub(["nhub"])

    (answers,) = seen
    assert set(answers) <= set(wizard.WIZARD_DOCUMENT_KEYS)
    assert answers["network"] == {"mode": "server"}
    validate(answers["password"], PASSWORDS_PANEL_RULES)
    validate(answers["vault_passphrase"], PASSWORDS_MASTER_RULES)


def test_the_install_script_is_handed_the_package_and_its_checksum(
    check, monkeypatch, tmp_path
):
    package = tmp_path / "neutrino-hub-9.9.9-macos-arm64.pkg"
    package.write_bytes(b"package")
    seen = []

    class Finished:
        returncode = 0

    def run(command, **kwargs):
        assets = Path(kwargs["env"]["NEUTRINO_ASSET_DIR"])
        seen.append(
            (
                command,
                (assets / "SHA256SUMS").read_text(),
                (assets / package.name).read_bytes(),
                kwargs["stdin"],
            )
        )
        return Finished()

    monkeypatch.setattr(check.subprocess, "run", run)

    check._run_install_script(package, ["sh", "install.sh", "hub"])

    ((command, sums, copied, stdin),) = seen
    assert command == ["sh", "install.sh", "hub"]
    assert sums == f"{hashlib.sha256(b'package').hexdigest()}  {package.name}\n"
    assert copied == b"package"
    assert stdin == check.subprocess.DEVNULL


def test_a_failing_install_script_fails_the_check(check, monkeypatch, tmp_path):
    package = tmp_path / "neutrino-hub-9.9.9-windows-amd64.msi"
    package.write_bytes(b"msi")

    class Failed:
        returncode = 1

    monkeypatch.setattr(check.subprocess, "run", lambda command, **kwargs: Failed())

    with pytest.raises(SystemExit) as refused:
        check._run_install_script(package, ["powershell.exe", "install.ps1", "hub"])

    assert "install.ps1 exited 1" in str(refused.value)


def test_the_scripts_it_runs_are_the_ones_a_release_publishes(check):
    assert (check.INSTALL_SCRIPTS_DIR / "install.sh").is_file()
    assert (check.INSTALL_SCRIPTS_DIR / "install.ps1").is_file()


class _Page:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exception):
        return False

    def close(self):
        pass


def _refused(check, url, code):
    return check.urllib.error.HTTPError(url, code, "refused", {}, None)


def test_the_wizard_is_the_page_and_an_api_that_refuses_without_the_token(
    check, monkeypatch
):
    asked = []

    def urlopen(url, timeout):
        asked.append(url)
        if url == check.HUB_WIZARD_API_URL:
            raise _refused(check, url, 403)
        return _Page()

    monkeypatch.setattr(check.urllib.request, "urlopen", urlopen)

    check._wait_for_wizard()

    assert asked == [check.HUB_WIZARD_PAGE_URL, check.HUB_WIZARD_API_URL]


def test_a_panel_answering_before_setup_is_not_the_wizard(check, monkeypatch):
    def urlopen(url, timeout):
        if url == check.HUB_WIZARD_API_URL:
            raise _refused(check, url, 404)
        return _Page()

    monkeypatch.setattr(check.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(check, "HUB_PANEL_WAIT_S", 0.01)
    monkeypatch.setattr(check.time, "sleep", lambda seconds: None)

    with pytest.raises(SystemExit, match="answered 404"):
        check._wait_for_wizard()


def _fake_container_run(stdout: str, calls: list, stderr: str = ""):
    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout=stdout, stderr=stderr)

    return run


def test_the_linux_hub_check_reads_the_address_from_nhub_open(
    check, monkeypatch, tmp_path
):
    calls = []
    monkeypatch.setattr(
        check.shutil,
        "which",
        lambda name: "/usr/bin/docker" if name == "docker" else None,
    )
    monkeypatch.setattr(
        check.subprocess,
        "run",
        _fake_container_run(
            "\n  Neutrino Hub installed. Set it up in a browser at:\n\n"
            "agent cache: neutrino-agent-0.5.0-1.x86_64.rpm\n"
            "nhub 0.5.0\nhttp://10.0.0.2:8080/?token=abc\n",
            calls,
        ),
    )
    package = tmp_path / "neutrino-hub-0.5.0-1.x86_64.rpm"
    package.write_bytes(b"rpm")
    check.check_linux(package)
    script = calls[0][-1]
    assert script.startswith("dnf -y install ")
    assert check.HUB_AGENT_CACHE_DIR in script
    assert script.endswith(" && nhub --version && nhub open --print")


@pytest.mark.parametrize(
    ("hub", "agent"),
    [
        ("neutrino-hub_0.5.0_arm64.deb", ["neutrino-agent_0.5.0_arm64.deb"]),
        ("neutrino-hub-0.5.0-1.aarch64.rpm", ["neutrino-agent-0.5.0-1.aarch64.rpm"]),
        ("neutrino-hub-0.5.0-1-x86_64.pkg.tar.zst", []),
    ],
)
def test_a_linux_hub_carries_the_agent_package_of_its_own_platform(check, hub, agent):
    assert check.hub_agent_cache(hub) == agent


def test_the_linux_hub_check_fails_when_the_cache_holds_another_platform(
    check, monkeypatch, tmp_path
):
    calls = []
    monkeypatch.setattr(
        check.shutil,
        "which",
        lambda name: "/usr/bin/docker" if name == "docker" else None,
    )
    monkeypatch.setattr(
        check.subprocess,
        "run",
        _fake_container_run(
            "  Neutrino Hub installed.\n"
            "agent cache: neutrino-agent_0.5.0_amd64.deb\n"
            "agent cache: neutrino-agent-0.5.0-1.x86_64.rpm\n"
            "nhub 0.5.0\nhttp://10.0.0.2:8080/?token=abc\n",
            calls,
        ),
    )
    package = tmp_path / "neutrino-hub_0.5.0_amd64.deb"
    package.write_bytes(b"deb")
    with pytest.raises(SystemExit, match="agent cache holds"):
        check.check_linux(package)


def test_the_linux_hub_check_fails_when_the_install_hid_its_address(
    check, monkeypatch, tmp_path
):
    calls = []
    monkeypatch.setattr(
        check.shutil,
        "which",
        lambda name: "/usr/bin/docker" if name == "docker" else None,
    )
    monkeypatch.setattr(
        check.subprocess,
        "run",
        _fake_container_run("nhub 0.5.0\nhttp://10.0.0.2:8080/?token=abc\n", calls),
    )
    package = tmp_path / "neutrino-hub_0.5.0_amd64.deb"
    package.write_bytes(b"deb")
    with pytest.raises(SystemExit, match="printed no setup wizard address"):
        check.check_linux(package)


def test_the_linux_hub_check_reads_dnf_scriptlet_words_from_its_error_stream(
    check, monkeypatch, tmp_path
):
    calls = []
    monkeypatch.setattr(
        check.shutil,
        "which",
        lambda name: "/usr/bin/docker" if name == "docker" else None,
    )
    monkeypatch.setattr(
        check.subprocess,
        "run",
        _fake_container_run(
            "agent cache: neutrino-agent-0.5.0-1.x86_64.rpm\n"
            "nhub 0.5.0\nhttp://10.0.0.2:8080/?token=abc\n",
            calls,
            stderr=">>> Scriptlet output:\n>>>   Neutrino Hub installed. Set it up in a browser at:\n",
        ),
    )
    package = tmp_path / "neutrino-hub-0.5.0-1.x86_64.rpm"
    package.write_bytes(b"rpm")
    check.check_linux(package)
    assert calls[0][-1].startswith("dnf -y install ")


def _macos_agent_check(check, monkeypatch, tmp_path, *, is_foreign_taken):
    """Run the macOS agent check with the Mac stood in for.

    ``nagent service uninstall`` is faked to delete the module's plist, the
    command and, when asked, the hub's plist too.
    """
    added = tmp_path / "com.neutrino.check.plist"
    foreign = tmp_path / "com.neutrino.hub_check.plist"
    command = tmp_path / "nagent"
    command.write_text("")
    ran = []

    def sudo(arguments):
        ran.append(arguments)
        if arguments[0] == "cp":
            Path(arguments[2]).write_text(Path(arguments[1]).read_text())
        if arguments[1:] == ["service", "uninstall", "--yes"]:
            added.unlink()
            command.unlink()
            if is_foreign_taken:
                foreign.unlink()

    monkeypatch.setattr(check, "AGENT_MACOS_ADDED_PLIST", added)
    monkeypatch.setattr(check, "AGENT_MACOS_FOREIGN_PLIST", foreign)
    monkeypatch.setattr(check, "AGENT_MACOS_COMMAND", str(command))
    monkeypatch.setattr(check, "_macos_rustdesk_problem", lambda: "")
    monkeypatch.setattr(check, "AGENT_MACOS_ROOT_MODES", {})
    monkeypatch.setattr(check, "_require_host", lambda platform, name: None)
    monkeypatch.setattr(check, "_sudo", sudo)
    monkeypatch.setattr(check, "_answer", lambda command: "state = running")
    monkeypatch.setattr(check, "_wait_for_job_gone", lambda job: True)
    monkeypatch.setattr(
        check.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=1)
    )
    check.check_agent_macos(tmp_path / "agent.pkg")
    return ran


def test_the_macos_agent_is_removed_by_its_own_command(check, monkeypatch, tmp_path):
    ran = _macos_agent_check(check, monkeypatch, tmp_path, is_foreign_taken=False)

    assert [str(tmp_path / "nagent"), "service", "uninstall", "--yes"] in ran
    assert not any(arguments[:2] == ["launchctl", "bootout"] for arguments in ran)


def test_the_macos_agent_check_fails_when_the_hubs_job_was_taken(
    check, monkeypatch, tmp_path
):
    with pytest.raises(SystemExit) as failed:
        _macos_agent_check(check, monkeypatch, tmp_path, is_foreign_taken=True)

    assert "wrong LaunchDaemons" in str(failed.value)


def test_the_windows_agent_check_plants_a_task_and_rules_named_both_ways(check):
    names = {
        "task": check.AGENT_WINDOWS_ADDED_TASK,
        "rule": check.AGENT_WINDOWS_ADDED_RULE,
        "foreign": check.AGENT_WINDOWS_FOREIGN_RULE,
    }
    planted = check.AGENT_WINDOWS_PLANT_SCRIPT.format(**names)

    assert "Register-ScheduledTask -TaskName neutrino_check_task" in planted
    assert "'neutrino_check_rule', 'neutrino_hub_check_rule'" in planted
    assert check.AGENT_WINDOWS_FOREIGN_RULE.startswith("neutrino_hub_")


@pytest.fixture
def windows_box(check, monkeypatch, tmp_path):
    """Program Files and ProgramData of this test's own, the vault written."""
    program_files = tmp_path / "Program Files"
    (program_files / "Neutrino" / "hub").mkdir(parents=True)
    vault = tmp_path / "ProgramData" / "Neutrino" / "hub" / "config" / "vault.json"
    vault.parent.mkdir(parents=True)
    vault.write_text("{}")
    access = {
        "text": "vault.json NT AUTHORITY\\SYSTEM:(I)(F)\n BUILTIN\\Administrators:(I)(F)"
    }
    monkeypatch.setattr(check, "PROGRAM_FILES", program_files)
    monkeypatch.setattr(check, "HUB_WINDOWS_VAULT", vault)
    monkeypatch.setattr(check, "_answer", lambda command: access["text"])
    return program_files, access


def test_a_vault_under_programdata_closed_to_people_passes(check, windows_box):
    check._check_hub_windows_config()


def test_a_configuration_under_program_files_fails_the_check(check, windows_box):
    program_files, _ = windows_box
    (program_files / "Neutrino" / "config").mkdir()

    with pytest.raises(SystemExit, match="under Program Files"):
        check._check_hub_windows_config()


def test_a_vault_every_person_can_read_fails_the_check(check, windows_box):
    _, access = windows_box
    access["text"] += "\n BUILTIN\\Users:(I)(RX)"

    with pytest.raises(SystemExit, match="BUILTIN"):
        check._check_hub_windows_config()


def test_no_vault_under_programdata_fails_the_check(
    check, windows_box, monkeypatch, tmp_path
):
    monkeypatch.setattr(check, "HUB_WINDOWS_VAULT", tmp_path / "nowhere" / "vault.json")

    with pytest.raises(SystemExit, match="no vault"):
        check._check_hub_windows_config()


@pytest.fixture
def client_data(check, monkeypatch, tmp_path):
    """The client's data folder of this test's own, and icacls answered per path."""
    data = tmp_path / "ProgramData" / "Neutrino" / "client"
    for relative in check.CLIENT_WINDOWS_DATA_FOLDERS:
        (data / relative).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(check, "CLIENT_WINDOWS_DATA", data)
    closed = (
        "NT AUTHORITY\\SYSTEM:(I)(OI)(CI)(F)\n BUILTIN\\Administrators:(I)(OI)(CI)(F)"
    )
    access = {}
    asked = []

    def answer(command):
        asked.append(command[1])
        return command[1] + " " + access.get(command[1], closed)

    monkeypatch.setattr(check, "_answer", answer)
    check._plant_client_windows_leftovers()
    return data, access, asked


def test_a_client_data_tree_closed_to_people_passes(check, client_data):
    data, _, asked = client_data
    (data / "state" / "netbird").mkdir()

    check._check_client_windows_data()

    assert asked == [
        str(data / ""),
        str(data / "state"),
        str(data / "log"),
        str(data / "state" / "netbird"),
        str(data / "log" / "earlier_build.log"),
        str(data / "state" / "earlier_build.txt"),
    ]


@pytest.mark.parametrize(
    "relative, grant",
    [
        ("state", "\n BUILTIN\\Users:(I)(OI)(CI)(RX)"),
        ("state/netbird", "\n NT AUTHORITY\\Authenticated Users:(I)(M)"),
        ("log/earlier_build.log", "\n Everyone:(I)(R)"),
    ],
)
def test_a_folder_or_leftover_every_person_can_read_fails_the_check(
    check, client_data, relative, grant
):
    data, access, _ = client_data
    (data / "state" / "netbird").mkdir()
    access[str(data / relative)] = "NT AUTHORITY\\SYSTEM:(I)(F)" + grant

    with pytest.raises(SystemExit, match="is open to"):
        check._check_client_windows_data()


def test_a_client_data_tree_with_no_log_folder_fails_the_check(check, client_data):
    data, _, _ = client_data
    for item in (data / "log").iterdir():
        item.unlink()
    (data / "log").rmdir()

    with pytest.raises(SystemExit, match="no .*log"):
        check._check_client_windows_data()


class FakeMac:
    """The runner as the client's upgrade check sees it: the app's pids move
    as the steps say."""

    def __init__(self, *, is_at_screen=True, is_reopened=True, is_opened_unasked=False):
        self.is_at_screen = is_at_screen
        self.is_reopened = is_reopened
        self.is_opened_unasked = is_opened_unasked
        self.pids: set = set()
        self.next_pid = 100
        self.steps: list = []

    def run(self, command, **kwargs):
        self.steps.append(list(command))
        if command[:2] == ["open", "-a"]:
            self._start()
        if command[-1] == "quit":
            self.pids = set()
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def sudo(self, command):
        self.steps.append(["sudo", *command])
        if self.pids:
            self.pids = set()
            if self.is_reopened:
                self._start()
        elif self.is_opened_unasked:
            self._start()

    def _start(self):
        self.next_pid += 1
        self.pids = {self.next_pid}


def _upgrade_check(check, monkeypatch, mac):
    monkeypatch.setattr(check.subprocess, "run", mac.run)
    monkeypatch.setattr(check, "_sudo", mac.sudo)
    monkeypatch.setattr(check, "_client_app_pids", lambda: set(mac.pids))
    monkeypatch.setattr(check.time, "sleep", lambda seconds: None)
    uid = check.os.getuid()
    monkeypatch.setattr(
        check, "_console_uid", lambda: uid if mac.is_at_screen else uid + 1
    )
    check._check_client_macos_upgrade(Path("client.pkg"))


def test_an_upgrade_over_the_running_client_app_leaves_a_new_one(check, monkeypatch):
    mac = FakeMac()

    _upgrade_check(check, monkeypatch, mac)

    assert [step[0] for step in mac.steps] == [
        "open",
        "sudo",
        check.CLIENT_MACOS_PROGRAM,
        "sudo",
    ]
    assert mac.pids == set()


def test_an_upgrade_that_leaves_no_client_app_fails_the_check(check, monkeypatch):
    monkeypatch.setattr(check, "CLIENT_MACOS_APP_WAIT_S", 0)

    with pytest.raises(SystemExit) as failed:
        _upgrade_check(check, monkeypatch, FakeMac(is_reopened=False))

    assert "no new client app" in str(failed.value)


def test_an_install_that_opens_an_app_nobody_had_open_fails_the_check(
    check, monkeypatch
):
    with pytest.raises(SystemExit) as failed:
        _upgrade_check(check, monkeypatch, FakeMac(is_opened_unasked=True))

    assert "opened one" in str(failed.value)


def test_a_runner_whose_account_is_not_at_the_screen_checks_no_reopen(
    check, monkeypatch, capsys
):
    mac = FakeMac(is_at_screen=False)

    _upgrade_check(check, monkeypatch, mac)

    assert mac.steps == []
    assert "not checked" in capsys.readouterr().out


@pytest.fixture
def relaunch_box(check, monkeypatch, tmp_path):
    """The runner's tasks, processes and msiexec, scripted."""
    marker = tmp_path / "relaunch_marker.txt"
    box = {"tasks": [], "windows": "", "commands": [], "repairs": [], "starts": True}
    monkeypatch.setattr(check, "CLIENT_WINDOWS_RELAUNCH_MARKER", marker)
    monkeypatch.setattr(check, "CLIENT_WINDOWS_RELAUNCH_WAIT_S", 0)
    monkeypatch.setattr(check, "_relaunch_tasks", lambda: list(box["tasks"]))

    def answer(command):
        box["commands"].append(command)
        if command[0] == "tasklist":
            return box["windows"]
        return ""

    def msiexec(action, msi, log, properties=()):
        box["repairs"].append((action, properties))
        if box["starts"]:
            marker.write_text("started")
        return 0

    monkeypatch.setattr(check, "_answer", answer)
    monkeypatch.setattr(check, "_msiexec", msiexec)
    monkeypatch.setattr(check, "_pending_renames", list)
    return box, marker


def test_a_repair_that_starts_the_planted_relaunch_task_passes(check, relaunch_box):
    box, marker = relaunch_box

    check._client_windows_repair(Path("client.msi"))
    check._client_windows_marker(Path("client.msi"))

    (planted,) = [c for c in box["commands"] if c[:2] == ["schtasks", "/create"]]
    assert planted[3] == "NeutrinoClientRelaunch_cicheck"
    assert planted[planted.index("/ru") + 1] == "SYSTEM"
    assert box["repairs"] == [("/i", ("REINSTALL=ALL", "REINSTALLMODE=vomus"))]
    assert not marker.exists()


def test_an_install_that_left_a_relaunch_task_fails_the_check(check, relaunch_box):
    box, _ = relaunch_box
    box["tasks"] = ["NeutrinoClientRelaunch_runner"]

    with pytest.raises(SystemExit, match="left relaunch tasks"):
        check._check_client_windows_nothing_started()


def test_an_install_that_started_a_window_fails_the_check(check, relaunch_box):
    box, _ = relaunch_box
    box["windows"] = '"nclientw.exe","4100","Console","1","40,000 K"'

    with pytest.raises(SystemExit, match="started one"):
        check._check_client_windows_nothing_started()


def test_a_repair_that_starts_no_relaunch_task_fails_the_check(check, relaunch_box):
    box, _ = relaunch_box
    box["starts"] = False

    check._client_windows_repair(Path("client.msi"))
    with pytest.raises(SystemExit, match="did not start the relaunch task"):
        check._client_windows_marker(Path("client.msi"))


@pytest.fixture
def phases(check, monkeypatch, tmp_path):
    """The client check's phases with their work recorded, evidence in tmp_path."""
    ran = []
    failing = set()

    def run_of(phase):
        def run(msi):
            ran.append(phase)
            if phase in failing:
                raise SystemExit(f"{phase} failed")

        return run

    monkeypatch.setattr(
        check,
        "CLIENT_WINDOWS_PHASE_RUNS",
        {phase: run_of(phase) for phase in check.CLIENT_WINDOWS_PHASES},
    )
    monkeypatch.setattr(check, "CHECK_EVIDENCE", tmp_path)
    monkeypatch.setattr(check, "CHECK_RESCUES", [])
    monkeypatch.setattr(check, "_require_host", lambda *args: None)
    monkeypatch.setattr(check, "_snapshot", lambda: "the machine\n")
    monkeypatch.setattr(check, "_push_status", lambda text: None)
    return ran, failing, tmp_path


def test_each_phase_runs_after_the_one_before_and_leaves_its_evidence(check, phases):
    ran, _, evidence = phases

    for phase in check.CLIENT_WINDOWS_PHASES:
        check.run_client_windows_phase(Path("client.msi"), phase)

    assert ran == list(check.CLIENT_WINDOWS_PHASES)
    state = json.loads((evidence / "state.json").read_text())
    assert state["passed"] == list(check.CLIENT_WINDOWS_PHASES)
    for phase in check.CLIENT_WINDOWS_PHASES:
        assert (evidence / f"{phase}.snapshot.txt").read_text() == "the machine\n"
    progress = (evidence / "progress.txt").read_text()
    assert "repair: starting" in progress and "repair: passed" in progress


def test_a_phase_whose_phase_before_did_not_pass_is_refused(check, phases):
    ran, failing, evidence = phases
    failing.add("installed")
    check.run_client_windows_phase(Path("client.msi"), "upgrade")
    check.run_client_windows_phase(Path("client.msi"), "install")
    with pytest.raises(SystemExit, match="installed failed"):
        check.run_client_windows_phase(Path("client.msi"), "installed")

    with pytest.raises(SystemExit, match="needs installed to have passed"):
        check.run_client_windows_phase(Path("client.msi"), "repair")

    assert ran == ["upgrade", "install", "installed"]
    assert (evidence / "installed.snapshot.txt").is_file()


def test_a_phase_after_the_install_can_take_the_client_away(check, phases):
    check.run_client_windows_phase(Path("client.msi"), "upgrade")
    check.run_client_windows_phase(Path("client.msi"), "install")
    check.CHECK_RESCUES.clear()

    check.run_client_windows_phase(Path("client.msi"), "installed")

    assert len(check.CHECK_RESCUES) == 1


def test_a_status_line_goes_to_this_runs_commit(check, monkeypatch):
    sent = []

    class Answer:
        def close(self):
            pass

    def urlopen(request, timeout):
        sent.append((request.full_url, json.loads(request.data), timeout))
        return Answer()

    monkeypatch.setenv("GITHUB_TOKEN", "t0ken")
    monkeypatch.setenv("GITHUB_REPOSITORY", "iffiX/neutrino")
    monkeypatch.setenv("GITHUB_SHA", "abc123")
    monkeypatch.setattr(check.urllib.request, "urlopen", urlopen)

    check._push_status("repair: msiexec /fa starting")

    ((url, body, timeout),) = sent
    assert url == "https://api.github.com/repos/iffiX/neutrino/statuses/abc123"
    assert body == {
        "state": "pending",
        "context": "client_windows check",
        "description": "repair: msiexec /fa starting",
    }
    assert timeout == check.CHECK_STATUS_TIMEOUT_S


def test_a_status_that_cannot_be_sent_never_fails_the_step(check, monkeypatch):
    def refuse(request, timeout):
        raise OSError("network is down")

    monkeypatch.setenv("GITHUB_TOKEN", "t0ken")
    monkeypatch.setenv("GITHUB_REPOSITORY", "iffiX/neutrino")
    monkeypatch.setenv("GITHUB_SHA", "abc123")
    monkeypatch.setattr(check.urllib.request, "urlopen", refuse)

    check._push_status("repair: planting the relaunch task")


def test_no_token_sends_no_status(check, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    def unexpected(request, timeout):
        raise AssertionError("nothing is sent")

    monkeypatch.setattr(check.urllib.request, "urlopen", unexpected)

    check._push_status("install: starting")


@pytest.mark.parametrize(
    "machine, declared, is_passing",
    [
        ("arm64", ["arm64", "x86_64"], True),
        ("x86_64", ["x86_64"], True),
        ("arm64", ["x86_64"], False),
        ("arm64", None, False),
    ],
)
def test_the_hub_entry_must_declare_the_runners_architecture_first(
    check, monkeypatch, tmp_path, machine, declared, is_passing
):
    import plistlib

    information = {"CFBundleExecutable": "Neutrino Hub"}
    if declared is not None:
        information["LSArchitecturePriority"] = declared
    plist = tmp_path / "Info.plist"
    plist.write_bytes(plistlib.dumps(information))
    monkeypatch.setattr(check, "HUB_MACOS_APP_INFO", plist)
    monkeypatch.setattr(check.platform, "machine", lambda: machine)

    if is_passing:
        check._check_hub_macos_entry()
    else:
        with pytest.raises(SystemExit):
            check._check_hub_macos_entry()


def test_an_msiexec_that_hangs_ends_the_check_with_a_snapshot(
    check, monkeypatch, tmp_path
):
    snapshots = []

    def hang(command, **kwargs):
        assert kwargs["timeout"] == check.CHECK_MSIEXEC_TIMEOUT_S
        raise check.subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(check.subprocess, "run", hang)
    monkeypatch.setattr(check, "_snapshot", lambda: snapshots.append(1))

    with pytest.raises(SystemExit, match="msiexec /fa ran past"):
        check._msiexec("/fa", tmp_path / "client.msi", tmp_path / "repair.log")

    assert snapshots == [1]


@pytest.mark.parametrize("helper", ["_answer", "_powershell"])
def test_a_command_that_hangs_ends_the_check_with_a_snapshot(
    check, monkeypatch, helper
):
    snapshots = []

    def hang(command, **kwargs):
        assert kwargs["timeout"] == check.CHECK_COMMAND_TIMEOUT_S
        raise check.subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(check.subprocess, "run", hang)
    monkeypatch.setattr(check, "_snapshot", lambda: snapshots.append(1))

    with pytest.raises(SystemExit, match="ran past"):
        getattr(check, helper)(["schtasks", "/query"] if helper == "_answer" else "x")

    assert snapshots == [1]


def test_a_snapshot_that_cannot_run_does_not_fail_the_check(check, monkeypatch, capsys):
    def refuse(command, **kwargs):
        raise OSError("no such program")

    monkeypatch.setattr(check.subprocess, "run", refuse)

    check._snapshot()

    assert "no snapshot: no such program" in capsys.readouterr().out


@pytest.fixture
def watched(check, monkeypatch):
    """The watchdog with time, the network, snapshots and the exit scripted."""
    events = []
    monkeypatch.setattr(check, "CHECK_NETWORK_EVERY_S", 0)
    monkeypatch.setattr(check, "_snapshot", lambda: events.append("snapshot"))
    monkeypatch.setattr(check.os, "_exit", lambda status: events.append(status))
    monkeypatch.setattr(check, "CHECK_RESCUES", [lambda: events.append("rescue")])
    return events


def test_the_watchdog_ends_a_check_past_its_limit_after_its_rescues(
    check, monkeypatch, watched
):
    monkeypatch.setattr(check, "CHECK_LIMIT_S", 0)
    monkeypatch.setattr(check, "_is_network_up", lambda: True)

    check._watchdog()

    assert watched == ["snapshot", "rescue", "snapshot", 1]


def test_a_network_gone_three_probes_in_a_row_ends_the_check(
    check, monkeypatch, watched, capsys
):
    answers = iter([True, False, True, False, False, False, True])
    monkeypatch.setattr(check, "CHECK_LIMIT_S", 3600)
    monkeypatch.setattr(check, "_is_network_up", lambda: next(answers))

    check._watchdog()

    assert watched == ["snapshot", "rescue", "snapshot", 1]
    out = capsys.readouterr().out
    assert "did not answer (3 in a row)" in out
    assert "the network is gone" in out
    assert "network after the rescues: up" in out


def test_a_rescue_stops_the_clients_services_before_it_removes_the_package(
    check, monkeypatch, tmp_path
):
    commands = []

    def run(command, **kwargs):
        commands.append(command[:3])
        assert kwargs["timeout"]
        return check.subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(check.subprocess, "run", run)

    check._remove_windows_package(
        tmp_path / "client.msi", services=check.CLIENT_WINDOWS_SERVICES
    )

    assert commands == [
        ["sc.exe", "stop", "NeutrinoClientNetbird"],
        ["sc.exe", "stop", "NeutrinoClientEasytier"],
        ["sc.exe", "stop", "NeutrinoClientFiles"],
        ["msiexec", "/x", str(tmp_path / "client.msi")],
    ]


def test_a_check_with_no_rescue_is_not_ended_by_the_network(
    check, monkeypatch, watched
):
    monkeypatch.setattr(check, "CHECK_RESCUES", [])
    monkeypatch.setattr(check, "CHECK_LIMIT_S", 0.05)
    monkeypatch.setattr(check, "CHECK_NETWORK_EVERY_S", 0.01)
    probes = []
    monkeypatch.setattr(check, "_is_network_up", lambda: probes.append(1) or False)
    monkeypatch.setattr(check, "CHECK_STARTED", check.time.monotonic())

    check._watchdog()

    assert probes == [1]
    assert watched[-1] == 1


# --- RustDesk in the agent's own folder, registered by nothing ---


def test_the_linux_agent_check_looks_for_the_copy_and_no_registration(
    check, monkeypatch, tmp_path
):
    calls = []
    monkeypatch.setattr(
        check.shutil,
        "which",
        lambda name: "/usr/bin/docker" if name == "docker" else None,
    )
    monkeypatch.setattr(
        check.subprocess, "run", _fake_container_run("nagent 0.5.0\n", calls)
    )
    package = tmp_path / "neutrino-agent_0.5.0_amd64.deb"
    package.write_bytes(b"deb")

    check.check_linux(package)

    script = calls[0][-1]
    assert check.AGENT_LINUX_RUSTDESK_CHECK in script
    assert script.index(check.AGENT_LINUX_RUSTDESK_CHECK) < script.index(
        "nagent --version"
    )


@pytest.mark.parametrize(
    "present, said",
    [
        (("copy",), ""),
        ((), "the agent's package laid down no "),
        (("copy", "unit"), "the agent's package installed "),
        (("copy", "link"), "the agent's package installed "),
    ],
)
def test_the_linux_rustdesk_check_says_what_is_wrong(check, tmp_path, present, said):
    copy = tmp_path / "usr/lib/neutrino/agent/rustdesk/rustdesk"
    unit = tmp_path / "lib/systemd/system/rustdesk.service"
    link = tmp_path / "usr/bin/rustdesk"
    if "copy" in present:
        copy.parent.mkdir(parents=True)
        copy.write_text("")
        copy.chmod(0o755)
    for name, path in (("unit", unit), ("link", link)):
        if name in present:
            path.parent.mkdir(parents=True)
            path.write_text("")
    snippet = check.AGENT_LINUX_RUSTDESK_CHECK
    for absolute in (check.AGENT_LINUX_RUSTDESK, *check.AGENT_LINUX_RUSTDESK_ABSENT):
        snippet = snippet.replace(absolute, str(tmp_path) + absolute)

    result = subprocess.run(["sh", "-c", snippet], capture_output=True, text=True)

    assert (result.returncode == 0) is (not said)
    assert result.stderr.startswith(said)


@pytest.mark.parametrize(
    "options, said",
    [
        ({}, ""),
        ({"is_copy_there": False}, "the agent's .msi laid down no "),
        ({"answer": "NotSigned False False"}, "signature is NotSigned"),
        ({"is_service_there": True}, "registered RustDesk's service"),
        ({"answer": "Valid True False"}, "left RustDesk's uninstall entry"),
        ({"is_standard_folder_there": True}, "installed "),
        ({"answer": "Valid False True"}, "a RustDesk process runs"),
    ],
)
def test_the_windows_rustdesk_check_says_what_is_wrong(check, options, said):
    given = {
        "is_copy_there": True,
        "answer": "Valid False False",
        "is_service_there": False,
        "is_standard_folder_there": False,
        **options,
    }

    problem = check.windows_rustdesk_problem(**given)

    assert (said in problem) if said else problem == ""
    assert bool(problem) == bool(said)


def test_the_windows_agent_has_one_service_of_its_own(check):
    assert check.AGENT_WINDOWS_SERVICES == ("neutrino_agent",)
    assert str(check.AGENT_WINDOWS_RUSTDESK).endswith("agent/rustdesk/rustdesk.exe")


def test_the_macos_check_finds_no_copy_where_none_was_laid(
    check, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        check, "AGENT_MACOS_RUSTDESK_APP", str(tmp_path / "RustDesk.app")
    )

    assert check._macos_rustdesk_problem().startswith("the agent's .pkg laid down no ")


def test_every_msiexec_of_a_check_suppresses_the_restart_by_its_property_too(
    check, monkeypatch, tmp_path
):
    """``/norestart`` is not applied to every form of the command; the
    property is, and a restart takes the runner away."""
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        return check.subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(check.subprocess, "run", run)

    check._msiexec(
        "/i",
        tmp_path / "client.msi",
        tmp_path / "repair.log",
        properties=check.CLIENT_WINDOWS_REPAIR_PROPERTIES,
    )
    check._remove_windows_package(tmp_path / "client.msi")

    repair, removal = commands
    assert repair[:5] == [
        "msiexec",
        "/i",
        str(tmp_path / "client.msi"),
        "REINSTALL=ALL",
        "REINSTALLMODE=vomus",
    ]
    for command in (repair, removal):
        assert "REBOOT=ReallySuppress" in command and "/norestart" in command
        assert not any(word.startswith("/f") for word in command)


@pytest.mark.parametrize("code", [3010, 1641])
def test_an_msiexec_that_wants_a_restart_fails_with_what_held_a_file(
    check, monkeypatch, tmp_path, capsys, code
):
    log = tmp_path / "repair.log"
    log.write_text(
        "Info 1603. The file C:\\Program Files\\Neutrino\\client\\bin\\netbird.exe "
        "is being held in use.  Close that application and retry.\n"
        "an unrelated line\n"
    )
    monkeypatch.setattr(
        check.subprocess,
        "run",
        lambda command, **kwargs: check.subprocess.CompletedProcess(command, code),
    )

    with pytest.raises(SystemExit, match=f"wants a restart \\(exit {code}\\)"):
        check._msiexec("/i", tmp_path / "client.msi", log)

    out = capsys.readouterr().out
    assert "netbird.exe is being held in use" in out
    assert "an unrelated line" not in out


def test_a_file_of_ours_left_for_the_next_restart_fails_the_check(check, monkeypatch):
    monkeypatch.setattr(
        check,
        "_pending_renames",
        lambda: [
            "\\??\\C:\\Windows\\Temp\\other.tmp",
            "",
            "\\??\\C:\\Program Files\\Neutrino\\client\\bin\\netbird.exe",
        ],
    )

    with pytest.raises(SystemExit, match="netbird.exe"):
        check._check_no_pending_rename()


def test_someone_elses_pending_rename_does_not_fail_the_check(check, monkeypatch):
    monkeypatch.setattr(
        check, "_pending_renames", lambda: ["\\??\\C:\\Windows\\Temp\\other.tmp"]
    )

    check._check_no_pending_rename()


def test_each_earlier_package_is_a_released_msi_of_a_windows_target(check):
    """The hub has no Windows package before 0.5.0, so it has no earlier one."""
    assert set(check.PACKAGING_EARLIER_PACKAGES) == {"agent_windows", "client_windows"}
    for asset, digest in check.PACKAGING_EARLIER_PACKAGES.values():
        assert asset.endswith(f"-{check.PACKAGING_EARLIER_VERSION}-windows-amd64.msi")
        assert len(digest) == 64


def test_an_earlier_package_is_fetched_from_its_release_and_its_hash_checked(
    check, monkeypatch, tmp_path
):
    body = b"the earlier msi"
    asked = []

    def urlopen(url, timeout):
        asked.append(url)
        return io.BytesIO(body)

    monkeypatch.setattr(check.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(
        check,
        "PACKAGING_EARLIER_PACKAGES",
        {"agent_windows": ("old.msi", hashlib.sha256(body).hexdigest())},
    )

    found = check.fetch_earlier("agent_windows", tmp_path)

    assert found.read_bytes() == body
    assert asked == [
        "https://github.com/iffiX/neutrino/releases/download/"
        f"v{check.PACKAGING_EARLIER_VERSION}/old.msi"
    ]


def test_an_earlier_package_whose_hash_differs_is_refused_and_deleted(
    check, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        check.urllib.request, "urlopen", lambda url, timeout: io.BytesIO(b"other")
    )
    monkeypatch.setattr(
        check, "PACKAGING_EARLIER_PACKAGES", {"agent_windows": ("old.msi", "0" * 64)}
    )

    with pytest.raises(SystemExit, match="not the pinned"):
        check.fetch_earlier("agent_windows", tmp_path)

    assert not (tmp_path / "old.msi").exists()


def test_an_agent_that_cannot_install_over_the_earlier_one_fails_the_check(
    check, monkeypatch, tmp_path
):
    """A fault in the upgrade's sequence ends msiexec with 1603, and the
    check ends before its fresh install."""
    done = []
    monkeypatch.setattr(check, "_require_host", lambda *_: None)
    monkeypatch.setattr(check, "_install_earlier", done.append)
    monkeypatch.setattr(check, "RUSTDESK_WINDOWS_FOLDER", tmp_path)
    monkeypatch.setattr(check, "_print_log", lambda *_: None)

    def msiexec(action, msi, log, is_restart_accepted=False):
        done.append((action, msi.name))
        return 1603

    monkeypatch.setattr(check, "_msiexec", msiexec)

    with pytest.raises(SystemExit, match="did not install over its 0.4.0"):
        check.check_agent_windows(tmp_path / "agent.msi")

    assert done == ["agent_windows", ("/i", "agent.msi")]


def test_an_earlier_agent_that_left_no_rustdesk_fails_the_check(
    check, monkeypatch, tmp_path
):
    monkeypatch.setattr(check, "_require_host", lambda *_: None)
    monkeypatch.setattr(check, "_install_earlier", lambda target: None)
    monkeypatch.setattr(check, "RUSTDESK_WINDOWS_FOLDER", tmp_path / "RustDesk")

    with pytest.raises(SystemExit, match="left no"):
        check.check_agent_windows(tmp_path / "agent.msi")


def test_an_install_over_an_earlier_package_may_want_a_restart_and_says_why(
    check, monkeypatch, tmp_path, capsys
):
    monkeypatch.setattr(
        check.subprocess,
        "run",
        lambda command, **kwargs: check.subprocess.CompletedProcess(command, 3010),
    )

    code = check._msiexec(
        "/i", tmp_path / "client.msi", tmp_path / "log", is_restart_accepted=True
    )

    assert code == 3010
    assert (
        "the earlier package's removal does not wait for its services"
        in capsys.readouterr().out
    )


def test_an_install_over_an_earlier_package_still_fails_a_forced_restart(
    check, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        check.subprocess,
        "run",
        lambda command, **kwargs: check.subprocess.CompletedProcess(command, 1641),
    )

    with pytest.raises(SystemExit, match="wants a restart \\(exit 1641\\)"):
        check._msiexec(
            "/i", tmp_path / "client.msi", tmp_path / "log", is_restart_accepted=True
        )


def test_only_our_pending_renames_are_dropped_pair_by_pair(check):
    entries = [
        "\\??\\C:\\Windows\\Temp\\a.tmp",
        "",
        "\\??\\C:\\Program Files\\Neutrino\\client\\bin\\~netbird.tmp",
        "!\\??\\C:\\Program Files\\Neutrino\\client\\bin\\netbird.exe",
        "\\??\\C:\\Program Files\\Neutrino\\agent\\old.dll",
        "",
        "\\??\\C:\\Other\\b.tmp",
        "\\??\\C:\\Other\\b.dll",
        "",
    ]

    kept, dropped = check.without_ours(entries)

    assert kept == [
        "\\??\\C:\\Windows\\Temp\\a.tmp",
        "",
        "\\??\\C:\\Other\\b.tmp",
        "\\??\\C:\\Other\\b.dll",
    ]
    assert dropped == [
        "!\\??\\C:\\Program Files\\Neutrino\\client\\bin\\netbird.exe",
        "\\??\\C:\\Program Files\\Neutrino\\agent\\old.dll",
    ]


@pytest.fixture
def upgrade_box(check, monkeypatch, tmp_path):
    """msiexec recorded, 3010 for the install over the earlier package, the
    removal taking the folder; then the fresh install fails, ending the check."""
    done = []
    folder = tmp_path / "Neutrino" / "agent"
    monkeypatch.setattr(check, "_require_host", lambda *_: None)
    monkeypatch.setattr(check, "_install_earlier", done.append)
    monkeypatch.setattr(check, "RUSTDESK_WINDOWS_FOLDER", tmp_path)
    monkeypatch.setattr(check, "AGENT_WINDOWS_EARLIER_FOLDER", tmp_path / "none")
    monkeypatch.setattr(check, "AGENT_WINDOWS_FOLDER", folder)
    monkeypatch.setattr(check, "_wait_for_earlier_rustdesk_gone", lambda: True)
    monkeypatch.setattr(check, "_print_log", lambda *_: None)
    monkeypatch.setattr(
        check, "_drop_pending_renames_of_ours", lambda: done.append("drop") or []
    )
    codes = {(1, "/i"): 3010, (2, "/x"): 0, (3, "/i"): 1603}

    def msiexec(action, msi, log, is_restart_accepted=False):
        done.append((action, is_restart_accepted))
        if action == "/i":
            folder.mkdir(parents=True, exist_ok=True)
        else:
            folder.rmdir()
        return codes[(sum(isinstance(item, tuple) for item in done), action)]

    monkeypatch.setattr(check, "_msiexec", msiexec)
    return done


def test_the_agent_upgrade_may_owe_a_restart_and_the_fresh_install_starts_clean(
    check, upgrade_box, tmp_path
):
    with pytest.raises(SystemExit, match="the agent did not install \\(exit 1603\\)"):
        check.check_agent_windows(tmp_path / "agent.msi")

    assert upgrade_box == [
        "agent_windows",
        ("/i", True),
        ("/x", True),
        "drop",
        ("/i", False),
    ]
