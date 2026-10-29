"""The one-command installer for Windows, run where PowerShell is.

``install.ps1`` is dot-sourced without its last line, the administrator
check and ``msiexec`` replaced by functions that record what they were
asked, and its downloads made for real from stand-in release sites on
127.0.0.1, so what is asserted is the package each machine takes, the site
and the release it comes from, the move to the next site on a stall, an
error or other bytes, the checksum that stops a wrong file, and the one
sentence each refusal says. Skipped where ``pwsh`` is not on the path.
"""

import hashlib
import json
import os
import re
import shutil
import sys
import subprocess
from pathlib import Path

import pytest

from shared import install_script_stamp
from shared.constants import PACKAGING_RELEASE_SITES

SCRIPT = Path(__file__).resolve().parents[3] / "packaging" / "install" / "install.ps1"
RELATIVE = "packaging/install/install.ps1"
LAST_LINE = "Install-Neutrino @args"
TAG = "v9.9.9"
# The edition of the tree the suite runs in. The mainland tree is written
# from the intl checkout, whose scripts hold the committed lines a build
# stamps, and from nothing else.
TREE_EDITION = (SCRIPT.parents[2] / "EDITION").read_text().strip()
from_intl_tree = pytest.mark.skipif(
    TREE_EDITION != "intl",
    reason="the mainland tree is written from the intl checkout",
)
MSI = "neutrino-hub-9.9.9-windows-amd64.msi"

PACKAGES = (
    MSI,
    "neutrino-agent-9.9.9-windows-amd64.msi",
    "neutrino-hub-9.9.9-windows-amd64-cn.msi",
    "neutrino-hub_9.9.9_amd64.deb",
    "install.ps1",
)

# Stand-ins defined after the script's own functions, so they win.
STAND_INS = """
$global:Asked = @()
function Test-NeutrinoAdministrator { return [bool]$env:FAKE_ADMIN }
function Start-Process {
    param(
        [string]$FilePath, [switch]$Wait, [switch]$PassThru, [string]$Verb,
        [string[]]$ArgumentList
    )
    if ($Verb) {
        if ($env:FAKE_UAC_REFUSED) { throw 'The operation was canceled by the user.' }
        $global:Asked += "$Verb $FilePath"
        $global:Asked += $ArgumentList
        return
    }
    $global:Asked += "$FilePath $($ArgumentList -join ' ')"
    return [pscustomobject]@{ ExitCode = [int]$env:FAKE_EXIT }
}
"""

pwsh = shutil.which("pwsh")
pytestmark = pytest.mark.skipif(pwsh is None, reason="PowerShell is not installed")


def _write_sums(served):
    """SHA256SUMS over every file the release holds."""
    lines = []
    for path in sorted(served.iterdir()):
        if path.name in ("SHA256SUMS", "latest.json"):
            continue
        lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}")
    (served / "SHA256SUMS").write_text("\n".join(lines) + "\n")


def _publish(served, name, data):
    """One more file in the release, with SHA256SUMS written again."""
    (served / name).write_bytes(data)
    _write_sums(served)


def _sites_text(sites):
    """The release sites as the script spells them."""
    return ", ".join(
        (
            f"@{{ Files = '{site.files}'; Latest = '{site.latest}' }}"
            if hasattr(site, "files")
            else f"@{{ Files = '{site[0]}'; Latest = '{site[1]}' }}"
        )
        for site in sites
    )


@pytest.fixture
def run(tmp_path, release_sites):
    served = release_sites.served
    for name in PACKAGES:
        (served / name).write_bytes(name.encode())
    _write_sums(served)
    (served / "latest.json").write_text(json.dumps({"tag": TAG, "version": "9.9.9"}))
    first = release_sites()
    second = release_sites()

    def invoke(
        *arguments,
        architecture="AMD64",
        is_admin=True,
        exit_code=0,
        env=None,
        edition="intl",
        sites=None,
        script=SCRIPT,
    ):
        text = re.sub(
            r"^\$script:NeutrinoEdition = '[a-z]+'$",
            f"$script:NeutrinoEdition = '{edition}'" if edition else r"\g<0>",
            script.read_text(),
            count=1,
            flags=re.MULTILINE,
        )
        assert text.rstrip().endswith(LAST_LINE)
        functions = tmp_path / "functions.ps1"
        functions.write_text(text.rstrip()[: -len(LAST_LINE)])
        driver = tmp_path / "driver.ps1"
        quoted = ", ".join(f"'{argument}'" for argument in arguments)
        given = (first, second) if sites is None else sites
        driver.write_text(
            f". '{functions}'\n"
            + STAND_INS
            + f"$script:NeutrinoReleaseSites = @({_sites_text(given)})\n"
            + "$script:NeutrinoProbeWaitSeconds = 1\n"
            + "$script:NeutrinoStallSeconds = 1\n"
            + "$outcome = 'ok'\n"
            + f"$given = @({quoted})\n"
            + "$said = @()\n"
            + "try { $said = @(Install-Neutrino @given) }"
            + " catch { $outcome = $_.Exception.Message }\n"
            + "@{ outcome = $outcome; asked = @($global:Asked);"
            + " said = @($said | ForEach-Object { [string]$_ }) }"
            + " | ConvertTo-Json -Compress\n"
        )
        environment = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp_path),
            "FAKE_ADMIN": "1" if is_admin else "",
            "FAKE_EXIT": str(exit_code),
            "PROCESSOR_ARCHITECTURE": architecture,
            "ProgramFiles": str(tmp_path / "Program Files"),
            "ProgramData": str(tmp_path / "ProgramData"),
            **(env or {}),
        }
        result = subprocess.run(
            [pwsh, "-NoProfile", "-NonInteractive", "-File", str(driver)],
            capture_output=True,
            text=True,
            env=environment,
            stdin=subprocess.DEVNULL,
            timeout=120,
        )
        assert result.returncode == 0, result.stderr
        answer = json.loads(result.stdout.strip().splitlines()[-1])
        invoke.said = answer["said"]
        return answer["outcome"], answer["asked"]

    invoke.served = served
    invoke.first = first
    invoke.second = second
    invoke.dead = release_sites.dead
    invoke.dead_host = release_sites.dead_host
    return invoke


def _paths(run):
    return [path for site in (run.first, run.second) for path, _ in site.requests]


def test_the_hub_msi_comes_from_the_latest_release_and_installs_quietly(run):
    outcome, asked = run()

    assert outcome == "ok"
    assert asked[0].startswith("msiexec.exe /i ")
    assert asked[0].endswith(f'{MSI}" /qn /norestart')
    assert "/latest.json" in _paths(run)
    assert f"/download/{TAG}/SHA256SUMS" in _paths(run)
    assert f"/download/{TAG}/{MSI}" in _paths(run)


def test_a_pinned_version_and_another_component(run):
    outcome, _asked = run("agent", env={"NEUTRINO_VERSION": "v9.9.8"})

    assert outcome == "ok"
    assert "/download/v9.9.8/neutrino-agent-9.9.9-windows-amd64.msi" in _paths(run)
    assert "/latest.json" not in _paths(run)


def test_local_files_install_with_nothing_downloaded(run):
    outcome, asked = run(env={"NEUTRINO_ASSET_DIR": str(run.served)})

    assert outcome == "ok"
    assert len(asked) == 1
    assert str(run.served / MSI) in asked[0]
    assert _paths(run) == []


def test_local_files_need_no_release_site(run):
    outcome, _asked = run(sites=(), env={"NEUTRINO_ASSET_DIR": str(run.served)})

    assert outcome == "ok"


def test_a_download_names_its_site_its_checksum_and_the_install(run):
    outcome, _asked = run()

    assert outcome == "ok"
    assert re.fullmatch(r"Downloaded SHA256SUMS from 127\.0\.0\.1:\d+", run.said[0])
    assert re.fullmatch(
        rf"Downloaded {re.escape(MSI)} from 127\.0\.0\.1:\d+", run.said[1]
    )
    assert run.said[2:5] == [
        f"{MSI} matches its SHA256SUMS line",
        f"Installing {MSI}",
        f"Installed {MSI}",
    ]


def test_local_files_name_the_directory_they_came_from(run):
    outcome, _asked = run(env={"NEUTRINO_ASSET_DIR": str(run.served)})

    assert outcome == "ok"
    assert run.said[0] == f"Found {MSI} in {run.served}"
    assert run.said[1] == f"{MSI} matches its SHA256SUMS line"


def test_a_local_package_that_does_not_match_its_checksum_is_never_installed(run):
    (run.served / MSI).write_bytes(b"tampered")

    outcome, asked = run(env={"NEUTRINO_ASSET_DIR": str(run.served)})

    assert outcome == (
        f"{MSI} does not match its SHA256SUMS line; nothing was installed."
    )
    assert not any(line.startswith("msiexec") for line in asked)


@pytest.mark.parametrize(
    "arguments, options, said",
    [
        (
            (),
            {"architecture": "ARM64"},
            "No Neutrino package is published for Windows on ARM64.",
        ),
        (("router",), {}, "Name hub, agent or client to install, not router."),
        (
            ("client",),
            {},
            "The release publishes no Neutrino client package for Windows on amd64.",
        ),
        ((), {"exit_code": 1603}, "msiexec exited 1603 installing "),
    ],
)
def test_a_refusal_is_one_sentence(run, arguments, options, said):
    outcome, asked = run(*arguments, **options)

    assert outcome.startswith(said)


def test_a_reboot_owed_is_still_an_install_and_is_said_in_one_line(run):
    outcome, _asked = run(exit_code=3010)

    assert outcome == "ok"
    assert f"Windows needs a restart to finish installing {MSI}." in run.said


def test_an_install_that_owes_no_restart_says_nothing_of_one(run):
    run()

    assert not any("restart" in line for line in run.said)


# --- the release sites ---


def test_a_checkout_names_no_site_and_stops_with_one_sentence(run):
    outcome, asked = run(sites=())

    assert outcome == (
        "This script names no release site; take it from a release, or set "
        "NEUTRINO_ASSET_DIR."
    )
    assert asked == []


def test_the_tree_s_script_names_the_sites_of_its_edition():
    """The GitHub checkout's script names none; the mainland tree's, which
    CNB serves, names every release site."""
    sites = (
        install_script_stamp.sites_text(RELATIVE, PACKAGING_RELEASE_SITES)
        if TREE_EDITION == "cn"
        else ""
    )

    assert f"\n$script:NeutrinoReleaseSites = @({sites})\n" in SCRIPT.read_text()


def test_the_fastest_site_serves_the_package(run):
    _publish(run.served, MSI, os.urandom(1536 * 1024))
    run.first.chunk_delay_s = 0.05

    outcome, _asked = run()

    assert outcome == "ok"
    assert run.first.downloads(MSI) == []
    assert run.second.downloads(MSI) == [""]
    assert f"Downloaded {MSI} from {run.second.host}" in run.said


def test_a_stalled_download_resumes_on_the_next_site_where_it_stopped(run):
    _publish(run.served, MSI, os.urandom(3 * 1024 * 1024))
    run.first.stall_at = 2 * 1024 * 1024
    run.second.chunk_delay_s = 0.05

    outcome, asked = run(env={"NEUTRINO_VERSION": TAG})

    assert outcome == "ok"
    assert run.first.downloads(MSI) == [""]
    (resumed,) = run.second.downloads(MSI)
    assert int(re.fullmatch(r"bytes=(\d+)-", resumed).group(1)) >= 2 * 1024 * 1024
    assert f"Downloaded {MSI} from {run.second.host}" in run.said
    assert asked[0].startswith("msiexec.exe /i ")


def test_a_site_serving_other_bytes_is_dropped_and_the_next_serves(run):
    _publish(run.served, MSI, os.urandom(1536 * 1024))
    run.first.is_wrong = True
    run.second.chunk_delay_s = 0.05

    outcome, _asked = run(env={"NEUTRINO_VERSION": TAG})

    assert outcome == "ok"
    assert run.first.downloads(MSI) == [""]
    assert run.second.downloads(MSI) == [""]
    assert f"Downloaded {MSI} from {run.second.host}" in run.said


def test_no_site_serving_the_package_stops_naming_each_site_and_why(run):
    (run.served / MSI).unlink()

    outcome, asked = run(sites=(run.first, run.dead), env={"NEUTRINO_VERSION": TAG})

    assert outcome == (
        f"No release site served {MSI}: {run.first.host} (http_404), "
        f"{run.dead_host} (unreachable)."
    )
    assert asked == []


@pytest.mark.parametrize("fast_tag", ["v9.9.9", "v9.9.8"])
def test_the_latest_release_is_the_fastest_answer_that_names_a_tag(run, fast_tag):
    slow_tag = "v9.9.8" if fast_tag == "v9.9.9" else "v9.9.9"
    run.first.latest_text = json.dumps({"tag": slow_tag})
    run.first.latest_delay_s = 0.5
    run.second.latest_text = json.dumps({"tag": fast_tag})

    outcome, _asked = run()

    assert outcome == "ok"
    assert f"/download/{fast_tag}/SHA256SUMS" in _paths(run)
    assert not any(path.startswith(f"/download/{slow_tag}/") for path in _paths(run))


def test_no_site_naming_the_latest_release_stops_naming_each_site(run):
    (run.served / "latest.json").write_text('{"version": "9.9.9"}')

    outcome, asked = run(sites=(run.first, run.dead))

    assert outcome == (
        "No release site named the latest release: "
        f"{run.first.host} (no_tag), {run.dead_host} (unreachable)."
    )
    assert asked == []


# --- the edition ---


def test_the_script_names_the_edition_of_its_tree():
    edition = (SCRIPT.parents[2] / "EDITION").read_text().strip()

    assert f"\n$script:NeutrinoEdition = '{edition}'\n" in SCRIPT.read_text()


def test_a_cn_script_takes_the_cn_msi_of_the_same_release(run):
    outcome, asked = run(edition="cn")

    assert outcome == "ok"
    assert asked[0].endswith('neutrino-hub-9.9.9-windows-amd64-cn.msi" /qn /norestart')


def test_an_intl_script_never_takes_a_cn_msi(run):
    (run.served / MSI).unlink()
    _write_sums(run.served)

    outcome, asked = run()

    assert outcome == (
        "The release publishes no Neutrino hub package for Windows on amd64."
    )
    assert asked == []


@from_intl_tree
@pytest.mark.parametrize("edition", ["intl", "cn"])
def test_a_release_build_stamps_sites_the_script_reads(tmp_path, edition):
    text = install_script_stamp.stamped_text(
        SCRIPT.read_text(), RELATIVE, edition=edition, sites=PACKAGING_RELEASE_SITES
    )
    functions = tmp_path / "functions.ps1"
    functions.write_text(text.rstrip()[: -len(LAST_LINE)])
    driver = tmp_path / "driver.ps1"
    driver.write_text(
        f". '{functions}'\n"
        "@{ edition = $script:NeutrinoEdition;"
        " sites = @($script:NeutrinoReleaseSites | ForEach-Object"
        " { @{ files = $_.Files; latest = $_.Latest } }) }"
        " | ConvertTo-Json -Compress -Depth 4\n"
    )

    result = subprocess.run(
        [pwsh, "-NoProfile", "-NonInteractive", "-File", str(driver)],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
        stdin=subprocess.DEVNULL,
    )

    assert result.returncode == 0, result.stderr
    stamped = json.loads(result.stdout.strip().splitlines()[-1])
    assert stamped["edition"] == edition
    assert stamped["sites"] == [dict(site) for site in PACKAGING_RELEASE_SITES]


@from_intl_tree
def test_the_mainland_script_installs_the_cn_msi(run, tmp_path):
    target = tmp_path / "mainland"
    subprocess.run(
        [
            sys.executable,
            str(SCRIPT.parents[1] / "build" / "build_sources.py"),
            "--edition",
            "cn",
            "--tree",
            str(target),
        ],
        check=True,
        capture_output=True,
    )

    outcome, asked = run(
        edition=None, script=target / "packaging" / "install" / "install.ps1"
    )

    assert outcome == "ok"
    assert asked[0].endswith('neutrino-hub-9.9.9-windows-amd64-cn.msi" /qn /norestart')


# --- one request for administrator rights ---


def test_without_administrator_rights_the_script_asks_windows_once_and_goes_on(
    run, tmp_path
):
    outcome, asked = run(
        "agent", is_admin=False, env={"NEUTRINO_ASSET_DIR": str(run.served)}
    )

    assert outcome == "ok"
    verb, *arguments = asked
    assert verb == f"RunAs {os.path.realpath(pwsh)}"
    assert arguments[:5] == [
        "-NoProfile",
        "-NoExit",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
    ]
    command = arguments[5]
    assert command.startswith(f"$env:NEUTRINO_ASSET_DIR = '{run.served}'; & '")
    assert command.endswith("' agent")
    copy = Path(command.split("& '")[1].split("'")[0])
    assert "function Install-Neutrino" in copy.read_text(encoding="utf-8-sig")
    assert _paths(run) == []
    assert run.said == [
        "Neutrino asks Windows for administrator rights once, and goes on in the "
        "window it opens."
    ]


def test_a_refused_elevation_installs_nothing(run):
    outcome, asked = run(is_admin=False, env={"FAKE_UAC_REFUSED": "1"})

    assert (
        outcome == "Windows did not grant administrator rights; nothing was installed."
    )
    assert asked == []


def test_a_script_run_from_invoke_expression_copies_itself_whole(tmp_path):
    """irm | iex has no file: the copy is the text the functions came from,
    the release sites the build stamped among it."""
    driver = tmp_path / "driver.ps1"
    released = SCRIPT.read_text()
    if TREE_EDITION == "intl":
        released = install_script_stamp.stamped_text(
            released, RELATIVE, edition="intl", sites=PACKAGING_RELEASE_SITES
        )
    text = released.rstrip()[: -len(LAST_LINE)]
    whole = text + STAND_INS + LAST_LINE + "\n"
    (tmp_path / "whole.ps1").write_text(whole)
    driver.write_text(
        f"Get-Content -Raw -LiteralPath '{tmp_path / 'whole.ps1'}' | Invoke-Expression\n"
        "$global:Asked | ConvertTo-Json -Compress\n"
    )
    result = subprocess.run(
        [pwsh, "-NoProfile", "-NonInteractive", "-File", str(driver)],
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp_path),
            "FAKE_ADMIN": "",
            "PROCESSOR_ARCHITECTURE": "AMD64",
        },
        stdin=subprocess.DEVNULL,
    )

    assert result.returncode == 0, result.stderr
    asked = json.loads(result.stdout.strip().splitlines()[-1])
    command = asked[-1]
    copy = Path(command.split("& '")[1].split("'")[0])
    copied = copy.read_text(encoding="utf-8-sig")
    assert copied.rstrip().endswith(LAST_LINE)
    assert "function Get-NeutrinoScriptText" in copied
    assert (
        "\n$script:NeutrinoReleaseSites = @(@{ Files = 'https://github.com/" in copied
    )
    assert command.endswith("' hub")


def test_an_administrator_s_run_asks_windows_for_nothing(run):
    outcome, asked = run("agent")

    assert outcome == "ok"
    assert not any(line.startswith("RunAs") for line in asked)
    assert any(line.startswith("msiexec.exe /i ") for line in asked)


def test_the_agent_names_its_next_command_in_this_window(run):
    run("agent")

    assert run.said[-1] == (
        "Next, in this window: nagent join '<enrollment link from the hub's "
        "Agents page>'"
    )


def test_the_hub_without_a_terminal_names_its_next_step(run):
    run()

    assert run.said[-1].startswith("Next, in this window: & '")
    assert run.said[-1].endswith("nhub.exe' open")


def test_a_joined_machine_is_given_no_join_line(run, tmp_path):
    config = tmp_path / "ProgramData" / "Neutrino" / "agent" / "config"
    config.mkdir(parents=True)
    (config / "agent.json").write_text('{\n  "id": "d1",\n  "token": "t0k"\n}\n')

    outcome, _asked = run("agent")

    assert outcome == "ok"
    assert not any("nagent join" in line for line in run.said)
    assert run.said[-1] == "Installed neutrino-agent-9.9.9-windows-amd64.msi"


# What a set-up hub's panel settings hold, and what a fresh one's do.
SET_UP_SETTINGS = (
    '{\n  "admin_password_hash": "scrypt$73616c74$6b6579"\n}\n'  # scan: allow
)
FRESH_SETTINGS = (
    '{\n  "admin_password_hash": "PLACEHOLDER_ARGON2ID_HASH"\n}\n'  # scan: allow
)


def _hub_settings(tmp_path, text):
    web = tmp_path / "ProgramData" / "Neutrino" / "hub" / "config" / "web"
    web.mkdir(parents=True)
    (web / "settings.json").write_text(text)


def test_a_hub_already_set_up_is_upgraded_and_names_its_panel(run, tmp_path):
    _hub_settings(tmp_path, SET_UP_SETTINGS)
    nhub = tmp_path / "Program Files" / "Neutrino" / "hub" / "nhub.exe"
    nhub.parent.mkdir(parents=True)
    nhub.write_text("#!/bin/sh\necho http://192.0.2.1:8080/\n")
    nhub.chmod(0o755)

    outcome, _asked = run()

    assert outcome == "ok"
    assert (
        run.said[-1] == "The hub was upgraded; its panel is at: http://192.0.2.1:8080/"
    )


def test_a_hub_already_set_up_with_no_address_says_how_to_open_it(run, tmp_path):
    _hub_settings(tmp_path, SET_UP_SETTINGS)

    outcome, _asked = run()

    assert outcome == "ok"
    assert run.said[-1].startswith("The hub was upgraded; in this window, & '")
    assert run.said[-1].endswith("nhub.exe' open opens its panel.")


def test_a_hub_with_the_example_settings_is_not_set_up(run, tmp_path):
    _hub_settings(tmp_path, FRESH_SETTINGS)

    run()

    assert run.said[-1].startswith("Next, in this window: & '")


def test_the_script_reads_the_hubs_settings_where_the_hub_keeps_them():
    from neutrino_hub.cli.password import PASSWORD_SETTINGS_FILE
    from neutrino_hub.platforms.constants import (
        PLATFORM_OS_WINDOWS,
        PLATFORM_ROOT_CONFIG,
        PLATFORM_ROOTS,
    )

    root = PLATFORM_ROOTS[PLATFORM_OS_WINDOWS][PLATFORM_ROOT_CONFIG]
    relative = (
        root.removeprefix("C:\\ProgramData\\")
        + "\\"
        + PASSWORD_SETTINGS_FILE.replace("/", "\\")
    )
    assert f"'{relative}'" in SCRIPT.read_text()


# --- a person who has joined is not told to join ---

CLIENT_JOIN_LINE = (
    "Next, in a PowerShell of your own: nclient hub join "
    "'<client link from the hub's Clients page>'"
)
CLIENT_BINDINGS = '{\n  "bindings": [{"id": "c1", "token": "t0k"}]\n}\n'


def _publish_client(served):
    name = "neutrino-client-9.9.9-windows-amd64.msi"
    (served / name).write_bytes(name.encode())
    with (served / "SHA256SUMS").open("a") as sums:
        sums.write(f"{hashlib.sha256(name.encode()).hexdigest()}  {name}\n")


def _roaming(root, text=None):
    roaming = root / "AppData" / "Roaming"
    if text is not None:
        (roaming / "Neutrino" / "client").mkdir(parents=True)
        (roaming / "Neutrino" / "client" / "client.json").write_text(text)
    return roaming


def test_a_person_with_no_client_binding_is_told_to_join(run, tmp_path):
    _publish_client(run.served)

    outcome, _asked = run("client", env={"APPDATA": str(_roaming(tmp_path))})

    assert outcome == "ok"
    assert run.said[-1] == CLIENT_JOIN_LINE


def test_a_person_who_has_joined_is_given_no_join_line(run, tmp_path):
    _publish_client(run.served)

    outcome, _asked = run(
        "client", env={"APPDATA": str(_roaming(tmp_path, CLIENT_BINDINGS))}
    )

    assert outcome == "ok"
    assert not any("nclient hub join" in line for line in run.said)


def test_the_elevated_window_reads_the_bindings_of_the_account_that_ran_it(
    run, tmp_path
):
    """Another administrator's window has its own roaming folder; the one
    carried in is the person's."""
    _publish_client(run.served)
    person = _roaming(tmp_path / "person", CLIENT_BINDINGS)

    outcome, _asked = run(
        "client",
        env={
            "APPDATA": str(_roaming(tmp_path / "admin")),
            "NEUTRINO_PERSON_APPDATA": str(person),
        },
    )

    assert outcome == "ok"
    assert not any("nclient hub join" in line for line in run.said)


def test_the_elevation_carries_the_persons_roaming_folder(run, tmp_path):
    roaming = _roaming(tmp_path)

    outcome, asked = run("client", is_admin=False, env={"APPDATA": str(roaming)})

    assert outcome == "ok"
    command = asked[6]
    assert f"$env:NEUTRINO_PERSON_APPDATA = '{roaming}'; " in command
