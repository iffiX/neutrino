"""The parts of ``packaging/ci/check.py`` the hub targets lean on.

The checks themselves install real packages on a runner; what is asserted
here is what they hand the hub and the install scripts: answers ``nhub
setup`` accepts, and a directory the scripts install from.
"""

import hashlib
import importlib.util
import json
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


def _macos_agent_check(
    check, monkeypatch, tmp_path, *, is_foreign_taken, is_cc_switch_kept=False
):
    """Run the macOS agent check with the Mac stood in for.

    ``nagent service uninstall`` is faked to delete the module's plist, the
    command and, when asked, the hub's plist too.
    """
    added = tmp_path / "com.neutrino.check.plist"
    foreign = tmp_path / "com.neutrino.hub_check.plist"
    command = tmp_path / "nagent"
    command.write_text("")
    switcher = tmp_path / "cc-switch"
    switcher.write_text("")
    ran = []

    def sudo(arguments):
        ran.append(arguments)
        if arguments[0] == "cp":
            Path(arguments[2]).write_text(Path(arguments[1]).read_text())
        if arguments[1:] == ["service", "uninstall", "--yes"]:
            added.unlink()
            command.unlink()
            if not is_cc_switch_kept:
                switcher.unlink()
            if is_foreign_taken:
                foreign.unlink()

    monkeypatch.setattr(check, "AGENT_MACOS_ADDED_PLIST", added)
    monkeypatch.setattr(check, "AGENT_MACOS_FOREIGN_PLIST", foreign)
    monkeypatch.setattr(check, "AGENT_MACOS_COMMAND", str(command))
    monkeypatch.setattr(check, "AGENT_MACOS_CC_SWITCH", str(switcher))
    monkeypatch.setattr(check, "_darwin_cc_switch_problem", lambda path: "")
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


# --- the cc-switch every agent package carries ---


def _agent_linux_output(check, owner="0", mode="755", version=None):
    version = version or check.CC_SWITCH_VERSION_LINE
    return (
        "Setting up neutrino-agent (0.5.0) ...\n"
        f"{check.CC_SWITCH_LINE}{owner} {mode}\n"
        f"{check.CC_SWITCH_LINE}{version}\n"
        "nagent 0.5.0\n"
    )


def test_the_linux_agent_check_reads_cc_switch_before_nagent(
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
        _fake_container_run(_agent_linux_output(check), calls),
    )
    package = tmp_path / "neutrino-agent_0.5.0_arm64.deb"
    package.write_bytes(b"deb")

    check.check_linux(package)

    script = calls[0][-1]
    assert (
        f"stat -c '{check.CC_SWITCH_LINE}%u %a' /opt/neutrino/agent/bin/cc-switch"
        in script
    )
    assert script.index("/opt/neutrino/agent/bin/cc-switch --version") < script.index(
        "nagent --version"
    )
    assert script.endswith(" && nagent --version")


def test_the_linux_hub_and_client_checks_ask_nothing_of_cc_switch_in_bin(
    check, monkeypatch, tmp_path
):
    calls = []
    monkeypatch.setattr(
        check.shutil,
        "which",
        lambda name: "/usr/bin/docker" if name == "docker" else None,
    )
    monkeypatch.setattr(
        check.subprocess, "run", _fake_container_run("nclient 0.5.0\n", calls)
    )
    package = tmp_path / "neutrino-client_0.5.0_amd64.deb"
    package.write_bytes(b"deb")

    check.check_linux(package)

    assert check.AGENT_LINUX_CC_SWITCH not in calls[0][-1]


@pytest.mark.parametrize(
    ("owner", "mode", "version", "said"),
    [
        ("0", "755", None, ""),
        ("1000", "755", None, "cc-switch is not owned by root or the administrators"),
        ("0", "775", None, "cc-switch can be changed by accounts other than its owner"),
        ("0", "757", None, "cc-switch can be changed by accounts other than its owner"),
        ("0", "750", None, "cc-switch cannot be run by every account"),
        (
            "0",
            "755",
            "cc-switch 5.0.0",
            "cc-switch --version printed 'cc-switch 5.0.0'",
        ),
    ],
)
def test_the_linux_agent_s_cc_switch_is_root_s_and_every_account_s_to_run(
    check, owner, mode, version, said
):
    problem = check.linux_cc_switch_problem(
        _agent_linux_output(check, owner, mode, version)
    )

    assert problem.startswith(said)
    assert bool(problem) == bool(said)


def test_a_linux_agent_that_printed_nothing_of_cc_switch_fails(check):
    assert check.linux_cc_switch_problem("nagent 0.5.0\n") == (
        "/opt/neutrino/agent/bin/cc-switch printed no owner, mode and version"
    )


def test_the_pinned_version_is_the_one_the_check_expects(check):
    from shared.constants import PACKAGING_CC_SWITCH_VERSION

    assert check.CC_SWITCH_VERSION_LINE == f"cc-switch {PACKAGING_CC_SWITCH_VERSION}"


@pytest.mark.parametrize(
    ("answer", "said"),
    [
        ("S-1-5-32-544 False True", ""),
        ("S-1-5-18 False True", ""),
        ("S-1-5-21-1-2-3-1001 False True", "cc-switch is not owned"),
        ("S-1-5-32-544 True True", "cc-switch can be changed"),
        ("S-1-5-32-544 False False", "cc-switch cannot be run"),
    ],
)
def test_the_windows_agent_s_cc_switch_is_the_administrators_and_the_users_to_run(
    check, answer, said
):
    problem = check.windows_cc_switch_problem(answer, check.CC_SWITCH_VERSION_LINE)

    assert problem.startswith(said)
    assert bool(problem) == bool(said)


def test_the_windows_acl_script_names_every_account_by_sid(check):
    everyone = ", ".join(f"'{sid}'" for sid in check.WINDOWS_EVERY_ACCOUNT_SIDS)
    script = check.WINDOWS_CC_SWITCH_ACL_SCRIPT.format(
        path=check.AGENT_WINDOWS_CC_SWITCH, everyone=everyone
    )

    assert "'S-1-5-32-545'" in script
    assert "'S-1-1-0'" in script
    assert str(check.AGENT_WINDOWS_CC_SWITCH) in script
    assert "{" not in script.replace("{ $_", "").replace("{ ([int]", "")


def test_the_macos_agent_check_fails_when_cc_switch_outlives_the_removal(
    check, monkeypatch, tmp_path
):
    with pytest.raises(SystemExit) as failed:
        _macos_agent_check(
            check, monkeypatch, tmp_path, is_foreign_taken=False, is_cc_switch_kept=True
        )

    assert "outlived nagent service uninstall" in str(failed.value)
    assert "cc-switch" in str(failed.value)
