"""What the agent's macOS installer carries, with every tool stood in for.

Neither the compiler nor Apple's tools run here, so what is asserted is the
package root the build lays out and the scripts it writes: the standalone
agent under Application Support, linked on the path and signed file by
file; RustDesk's app under Applications; the agent's LaunchDaemon running
``nagent run`` into its log; RustDesk's daemon and session agent; the
preinstall unloading and the postinstall loading all three; and the name the
release publishes it under.
"""

import os
import plistlib
import subprocess
from pathlib import Path

import pytest

import build_agent_macos
from neutrino_agent.constants import AGENT_DARWIN_LOG_PATH


@pytest.fixture
def laid_out(tmp_path, monkeypatch):
    """The package root with the compile, the download, otool and codesign
    faked."""
    signed = []
    checked = []

    def compile_standalone(python, entry, output_dir, binary_name, **kwargs):
        dist = output_dir / "entry.dist"
        dist.mkdir(parents=True)
        (dist / binary_name).write_bytes(b"\xcf\xfa\xed\xfe" + b"\0" * 12)
        (dist / "libpython3.13.dylib").write_bytes(b"\xcf\xfa\xed\xfe" + b"\0" * 12)
        (dist / "neutrino_agent").mkdir()
        (dist / "neutrino_agent" / "notes.txt").write_text("not code")
        return dist

    def stage_darwin_app(dest_dir, *, machine="aarch64"):
        app = dest_dir / "RustDesk.app" / "Contents" / "MacOS"
        app.mkdir(parents=True)
        (app / "RustDesk").write_bytes(b"\xcf\xfa\xed\xfe" + b"\0" * 12)
        return dest_dir / "RustDesk.app"

    monkeypatch.setattr(build_agent_macos, "_check_build_machine", lambda machine: None)
    monkeypatch.setattr(
        build_agent_macos, "_make_build_environment", lambda venv: Path("python3")
    )
    monkeypatch.setattr(
        build_agent_macos.nuitka_build, "compile_standalone", compile_standalone
    )
    monkeypatch.setattr(
        build_agent_macos.rustdesk_assets, "stage_darwin_app", stage_darwin_app
    )
    monkeypatch.setattr(build_agent_macos.pkg_build, "sign_ad_hoc", signed.append)
    monkeypatch.setattr(
        build_agent_macos.pkg_build,
        "require_system_links",
        lambda directory: checked.append((directory, len(signed))),
    )

    staged = build_agent_macos._lay_out(tmp_path, "9.9.9", "arm64")
    return staged, signed, checked


def read_plist(root: Path, directory: str, label: str) -> dict:
    return plistlib.loads((root / directory / f"{label}.plist").read_bytes())


def test_the_agent_lands_under_application_support_linked_on_the_path(laid_out):
    staged, _signed, _checked = laid_out
    root = staged["root"]

    installed = root / "Library/Application Support/Neutrino/agent/app"
    assert (installed / "nagent").is_file()
    assert (installed / "licenses" / "rustdesk.txt").is_file()
    link = root / "usr/local/bin/nagent"
    assert link.is_symlink()
    assert (
        str(link.readlink()) == "/Library/Application Support/Neutrino/agent/app/nagent"
    )


def test_every_mach_o_file_is_signed_and_nothing_else(laid_out):
    staged, signed, _checked = laid_out
    installed = staged["root"] / "Library/Application Support/Neutrino/agent/app"

    assert sorted(path.name for path in signed) == ["libpython3.13.dylib", "nagent"]
    assert all(str(path).startswith(str(installed)) for path in signed)


def test_the_installed_tree_is_read_back_for_its_links_before_signing(laid_out):
    staged, _signed, checked = laid_out
    installed = staged["root"] / "Library/Application Support/Neutrino/agent/app"

    assert checked == [(installed, 0)]


def test_rustdesk_is_the_app_in_the_agents_own_folder_with_upstreams_signature(
    laid_out,
):
    """It is copied in after the ad hoc signing, which never touches it."""
    staged, signed, _checked = laid_out
    app = (
        staged["root"]
        / "Library/Application Support/Neutrino/agent/app/rustdesk/RustDesk.app"
    )

    assert (app / "Contents/MacOS/RustDesk").is_file()
    assert not any("RustDesk.app" in str(path) for path in signed)
    assert not (staged["root"] / "Applications").exists()


def test_the_agents_daemon_runs_nagent_run_into_its_log(laid_out):
    staged, _signed, _checked = laid_out

    job = read_plist(staged["root"], "Library/LaunchDaemons", "com.neutrino.agent")

    assert job["ProgramArguments"] == [
        "/Library/Application Support/Neutrino/agent/app/nagent",
        "run",
    ]
    assert job["StandardOutPath"] == "/Library/Logs/Neutrino/agent/agent.log"
    assert job["StandardErrorPath"] == "/Library/Logs/Neutrino/agent/agent.log"
    assert job["StandardOutPath"] == AGENT_DARWIN_LOG_PATH
    assert job["RunAtLoad"] is True
    assert job["KeepAlive"] is True
    assert job["EnvironmentVariables"] == {"LANG": "en_US.UTF-8"}


def test_the_package_installs_the_agents_job_and_no_job_of_rustdesks(laid_out):
    """The agent registers RustDesk's jobs when the hub's switch is on."""
    staged, _signed, _checked = laid_out
    root = staged["root"]

    assert sorted(path.name for path in (root / "Library/LaunchDaemons").iterdir()) == [
        "com.neutrino.agent.plist"
    ]
    assert not (root / "Library/LaunchAgents").exists()


def test_the_scripts_unload_the_agent_before_and_start_it_alone_after(laid_out):
    staged, _signed, _checked = laid_out
    scripts = staged["scripts"]

    preinstall = (scripts / "preinstall").read_text()
    postinstall = (scripts / "postinstall").read_text()

    assert "launchctl bootout system/com.neutrino.agent" in preinstall
    assert postinstall.startswith("#!/bin/sh\nstart_daemon() {")
    assert (
        "start_daemon com.neutrino.agent "
        "/Library/LaunchDaemons/com.neutrino.agent.plist || {\n" in postinstall
    )
    agent_start = postinstall.split("start_daemon com.neutrino.agent ")[1]
    assert agent_start.split("}")[0].rstrip().endswith("exit 1")
    assert "RustDesk" not in postinstall
    assert postinstall.index('mkdir -p "/Library/Logs/Neutrino/agent"') < (
        postinstall.index("start_daemon com.")
    )
    support = "/Library/Application Support/Neutrino/agent"
    assert f'chmod 700 "{support}/config"' in postinstall
    assert f'chmod 755 "{support}/state"' in postinstall
    for script in ("preinstall", "postinstall"):
        assert (scripts / script).stat().st_mode & 0o111


def test_the_package_is_named_the_way_the_release_publishes_it():
    assert build_agent_macos.pkg_name("0.4.0", "arm64") == (
        "neutrino-agent-0.4.0-macos-arm64.pkg"
    )
    assert build_agent_macos.pkg_name("0.4.0", "amd64") == (
        "neutrino-agent-0.4.0-macos-amd64.pkg"
    )
    assert build_agent_macos.macos_machine("arm64") == "arm64"
    assert build_agent_macos.macos_machine("x86_64") == "amd64"
    with pytest.raises(SystemExit):
        build_agent_macos.macos_machine("armhf")


def test_an_intel_package_carries_the_intel_rustdesk(tmp_path, monkeypatch):
    asked = []

    def compile_standalone(python, entry, output_dir, binary_name, **kwargs):
        dist = output_dir / "entry.dist"
        dist.mkdir(parents=True)
        (dist / binary_name).write_bytes(b"")
        return dist

    def stage_darwin_app(dest_dir, *, machine="aarch64"):
        asked.append(machine)
        return dest_dir / "RustDesk.app"

    monkeypatch.setattr(build_agent_macos, "_check_build_machine", lambda machine: None)
    monkeypatch.setattr(
        build_agent_macos, "_make_build_environment", lambda venv: Path("python3")
    )
    monkeypatch.setattr(
        build_agent_macos.nuitka_build, "compile_standalone", compile_standalone
    )
    monkeypatch.setattr(
        build_agent_macos.rustdesk_assets, "stage_darwin_app", stage_darwin_app
    )
    monkeypatch.setattr(build_agent_macos.pkg_build, "sign_ad_hoc", lambda path: None)

    build_agent_macos._lay_out(tmp_path, "9.9.9", "amd64")

    assert asked == ["x86_64"]


def test_the_build_refuses_anything_but_a_mac(monkeypatch):
    monkeypatch.setattr(build_agent_macos.sys, "platform", "linux")

    with pytest.raises(SystemExit) as refused:
        build_agent_macos._check_build_machine("arm64")

    assert "Mac" in str(refused.value)


# --- an upgrade from the layout that installed RustDesk under /Applications ---

OLD_RECEIPT = """Applications/RustDesk.app
Applications/RustDesk.app/Contents
Applications/RustDesk.app/Contents/MacOS/RustDesk
Applications/RustDesk.app/Contents/MacOS/service
Library/Application Support/Neutrino/agent/app/nagent
Library/LaunchAgents/com.carriez.RustDesk_server.plist
Library/LaunchDaemons/com.carriez.RustDesk_service.plist
Library/LaunchDaemons/com.neutrino.agent.plist
"""

PROCESSES = """  101 /Applications/RustDesk.app/Contents/MacOS/RustDesk --server
  102 /bin/sh -c /Applications/RustDesk.app/Contents/MacOS/service
  103 /Applications/RustDesk.app/Contents/MacOS/RustDesk --connect 123456789
  104 /Library/Application Support/Neutrino/agent/app/rustdesk/RustDesk.app/Contents/MacOS/RustDesk --server
"""


def _run_preinstall(tmp_path, laid_out, receipt):
    """Run the preinstall script with every command it touches the Mac with
    replaced by one that records what it was asked."""
    staged, _signed, _checked = laid_out
    fakes = tmp_path / "fakes"
    fakes.mkdir()
    record = tmp_path / "calls"
    (tmp_path / "receipt").write_text(receipt)
    (tmp_path / "processes").write_text(PROCESSES)
    scripts = {
        "pkgutil": f'[ -s "{tmp_path}/receipt" ] || exit 1\ncat "{tmp_path}/receipt"',
        "ps": f'case "$*" in *comm=*) echo "  501 /System/Library/CoreServices/'
        f'loginwindow.app/Contents/MacOS/loginwindow";; *) cat "{tmp_path}/processes";; esac',
        "launchctl": f'echo "launchctl $*" >>"{record}"',
        "kill": f'echo "kill $*" >>"{record}"',
        "rm": f'echo "rm $*" >>"{record}"',
    }
    for name, body in scripts.items():
        fake = fakes / name
        fake.write_text(f"#!/bin/sh\n{body}\n")
        fake.chmod(0o755)
    text = (
        (staged["scripts"] / "preinstall")
        .read_text()
        .replace('kill "$pid"', '"$KILL" "$pid"')
    )
    script = tmp_path / "preinstall"
    script.write_text(text)
    subprocess.run(
        ["sh", str(script)],
        env=dict(os.environ, PATH=f"{fakes}:/usr/bin:/bin", KILL=str(fakes / "kill")),
        check=True,
    )
    return record.read_text().splitlines() if record.exists() else []


def test_an_upgrade_takes_away_what_the_old_package_put_under_applications(
    tmp_path, laid_out
):
    calls = _run_preinstall(tmp_path, laid_out, OLD_RECEIPT)

    assert "launchctl bootout system/com.carriez.RustDesk_service" in calls
    assert "launchctl bootout gui/501/com.carriez.RustDesk_server" in calls
    assert "rm -f /Library/LaunchDaemons/com.carriez.RustDesk_service.plist" in calls
    assert "rm -f /Library/LaunchAgents/com.carriez.RustDesk_server.plist" in calls
    assert "rm -rf /Applications/RustDesk.app" in calls
    assert "kill 101" in calls
    assert "kill 102" in calls
    assert "kill 103" not in calls
    assert "kill 104" not in calls


@pytest.mark.parametrize(
    "receipt",
    [
        "",
        "Library/Application Support/Neutrino/agent/app/nagent\n"
        "Library/Application Support/Neutrino/agent/app/rustdesk/RustDesk.app/"
        "Contents/MacOS/RustDesk\n",
    ],
    ids=["fresh", "already_new"],
)
def test_a_rustdesk_the_receipt_does_not_list_is_left_alone(
    tmp_path, laid_out, receipt
):
    """A person's own RustDesk, and the jobs the agent registered itself
    under RustDesk's names, are no package's files."""
    calls = _run_preinstall(tmp_path, laid_out, receipt)

    assert calls == ["launchctl bootout system/com.neutrino.agent"]
