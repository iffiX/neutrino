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
