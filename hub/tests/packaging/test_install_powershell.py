"""The one-command installer for Windows, run where PowerShell is.

``install.ps1`` is dot-sourced without its last line, the administrator
check, the download and ``msiexec`` replaced by functions that record what
they were asked, so what is asserted is the package each machine takes,
where it comes from, the checksum that stops a wrong file, and the one
sentence each refusal says. Skipped where ``pwsh`` is not on the path.
"""

import hashlib
import json
import re
import shutil
import sys
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "packaging" / "install" / "install.ps1"
LAST_LINE = "Install-Neutrino @args"
RELEASE = "https://github.com/iffiX/neutrino/releases"
CN_RELEASE = "https://gitee.com/iffiX/neutrino/releases"
CN_LATEST = "https://gitee.com/api/v5/repos/iffiX/neutrino/releases/latest"

PACKAGES = (
    "neutrino-hub-9.9.9-windows-amd64.msi",
    "neutrino-agent-9.9.9-windows-amd64.msi",
    "neutrino-hub_9.9.9_amd64.deb",
)

# Stand-ins defined after the script's own functions, so they win.
STAND_INS = """
$global:Asked = @()
function Test-NeutrinoAdministrator { return [bool]$env:FAKE_ADMIN }
function Invoke-WebRequest {
    param([switch]$UseBasicParsing, [string]$Uri, [string]$OutFile)
    $global:Asked += "fetch $Uri"
    Copy-Item -LiteralPath (Join-Path $env:FAKE_SERVED (Split-Path -Leaf $Uri)) $OutFile
}
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


@pytest.fixture
def run(tmp_path):
    served = tmp_path / "release"
    served.mkdir()
    lines = []
    for name in PACKAGES:
        (served / name).write_bytes(name.encode())
        lines.append(f"{hashlib.sha256(name.encode()).hexdigest()}  {name}")
    (served / "SHA256SUMS").write_text("\n".join(lines) + "\n")

    def invoke(
        *arguments,
        architecture="AMD64",
        is_admin=True,
        exit_code=0,
        env=None,
        edition="intl",
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
        driver.write_text(
            f". '{functions}'\n"
            + STAND_INS
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
            "FAKE_SERVED": str(served),
            "FAKE_ADMIN": "1" if is_admin else "",
            "FAKE_EXIT": str(exit_code),
            "PROCESSOR_ARCHITECTURE": architecture,
            "ProgramFiles": str(tmp_path / "Program Files"),
            **(env or {}),
        }
        result = subprocess.run(
            [pwsh, "-NoProfile", "-NonInteractive", "-File", str(driver)],
            capture_output=True,
            text=True,
            env=environment,
            stdin=subprocess.DEVNULL,
        )
        assert result.returncode == 0, result.stderr
        answer = json.loads(result.stdout.strip().splitlines()[-1])
        invoke.said = answer["said"]
        return answer["outcome"], answer["asked"]

    invoke.served = served
    return invoke


def test_the_hub_msi_comes_from_the_latest_release_and_installs_quietly(run):
    outcome, asked = run()

    assert outcome == "ok"
    assert asked[:2] == [
        f"fetch {RELEASE}/latest/download/SHA256SUMS",
        f"fetch {RELEASE}/latest/download/neutrino-hub-9.9.9-windows-amd64.msi",
    ]
    assert asked[2].startswith("msiexec.exe /i ")
    assert asked[2].endswith('neutrino-hub-9.9.9-windows-amd64.msi" /qn /norestart')


def test_a_pinned_version_and_another_component(run):
    outcome, asked = run("agent", env={"NEUTRINO_VERSION": "v9.9.9"})

    assert outcome == "ok"
    assert asked[1] == (
        f"fetch {RELEASE}/download/v9.9.9/neutrino-agent-9.9.9-windows-amd64.msi"
    )


def test_local_files_install_with_nothing_downloaded(run):
    outcome, asked = run(env={"NEUTRINO_ASSET_DIR": str(run.served)})

    assert outcome == "ok"
    assert len(asked) == 1
    assert str(run.served / "neutrino-hub-9.9.9-windows-amd64.msi") in asked[0]


def test_a_package_that_does_not_match_its_checksum_is_never_installed(run):
    (run.served / "neutrino-hub-9.9.9-windows-amd64.msi").write_bytes(b"tampered")

    outcome, asked = run()

    assert outcome == (
        "neutrino-hub-9.9.9-windows-amd64.msi does not match its SHA256SUMS line; "
        "nothing was installed."
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


def test_a_reboot_owed_is_still_an_install(run):
    outcome, _asked = run(exit_code=3010)

    assert outcome == "ok"


def test_the_script_names_the_edition_of_its_tree():
    edition = (SCRIPT.parents[2] / "EDITION").read_text().strip()

    assert f"\n$script:NeutrinoEdition = '{edition}'\n" in SCRIPT.read_text()


def test_a_cn_script_reads_the_latest_tag_from_gitee_then_its_files(run):
    (run.served / "latest").write_text('{"id": 7, "tag_name": "v9.9.9"}')

    outcome, asked = run(edition="cn")

    assert outcome == "ok"
    assert asked[:3] == [
        f"fetch {CN_LATEST}",
        f"fetch {CN_RELEASE}/download/v9.9.9/SHA256SUMS",
        f"fetch {CN_RELEASE}/download/v9.9.9/neutrino-hub-9.9.9-windows-amd64.msi",
    ]


def test_a_cn_script_given_a_version_asks_the_api_nothing(run):
    outcome, asked = run(edition="cn", env={"NEUTRINO_VERSION": "v9.9.9"})

    assert outcome == "ok"
    assert asked[0] == f"fetch {CN_RELEASE}/download/v9.9.9/SHA256SUMS"


def test_a_cn_latest_release_with_no_tag_is_one_sentence(run):
    (run.served / "latest").write_text("{}")

    outcome, _asked = run(edition="cn")

    assert outcome == f"The latest release at {CN_LATEST} names no tag."


# The mainland tree is written from the intl checkout, and from nothing else.
from_intl_tree = pytest.mark.skipif(
    (Path(__file__).resolve().parents[3] / "EDITION").read_text().strip() != "intl",
    reason="the mainland tree is written from the intl checkout",
)


@from_intl_tree
def test_the_mainland_script_installs_from_gitee(run, tmp_path):
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
    (run.served / "latest").write_text('{"tag_name": "v9.9.9"}')

    outcome, asked = run(
        edition=None, script=target / "packaging" / "install" / "install.ps1"
    )

    assert outcome == "ok"
    assert asked[:2] == [
        f"fetch {CN_LATEST}",
        f"fetch {CN_RELEASE}/download/v9.9.9/SHA256SUMS",
    ]


# --- one request for administrator rights ---


def test_without_administrator_rights_the_script_asks_windows_once_and_goes_on(
    run, tmp_path
):
    outcome, asked = run(
        "agent", is_admin=False, env={"NEUTRINO_ASSET_DIR": str(run.served)}
    )

    assert outcome == "ok"
    verb, *arguments = asked
    assert verb == f"RunAs {pwsh}"
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
    assert not any(line.startswith("fetch") for line in asked)
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
    """irm | iex has no file: the copy is the text the functions came from."""
    driver = tmp_path / "driver.ps1"
    text = SCRIPT.read_text().rstrip()[: -len(LAST_LINE)]
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
        "Devices page>'"
    )


def test_the_hub_without_a_terminal_names_its_next_step(run):
    run()

    assert run.said[-1].startswith("Next, in this window: & '")
    assert run.said[-1].endswith("nhub.exe' open")
