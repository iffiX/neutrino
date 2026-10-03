"""What the agent's macOS installer carries, with every tool stood in for.

Neither the compiler nor Apple's tools run here, so what is asserted is the
package root the build lays out and the scripts it writes: the standalone
agent under Application Support, linked on the path and signed file by
file; RustDesk's app under Applications; the agent's LaunchDaemon running
``nagent run`` into its log; RustDesk's daemon and session agent; the
preinstall unloading and the postinstall loading all three; and the name the
release publishes it under.
"""

import plistlib
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
        (app / "RustDesk").write_bytes(b"")
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


def test_rustdesk_is_the_app_under_applications(laid_out):
    staged, _signed, _checked = laid_out

    assert (
        staged["root"] / "Applications/RustDesk.app/Contents/MacOS/RustDesk"
    ).is_file()


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


def test_rustdesks_daemon_and_session_agent_are_its_own(laid_out):
    staged, _signed, _checked = laid_out
    root = staged["root"]

    service = read_plist(root, "Library/LaunchDaemons", "com.carriez.RustDesk_service")
    server = read_plist(root, "Library/LaunchAgents", "com.carriez.RustDesk_server")

    assert service["ProgramArguments"] == [
        "/bin/sh",
        "-c",
        "/Applications/RustDesk.app/Contents/MacOS/service",
    ]
    assert server["ProgramArguments"] == [
        "/Applications/RustDesk.app/Contents/MacOS/RustDesk",
        "--server",
    ]
    assert server["LimitLoadToSessionType"] == ["LoginWindow", "Aqua"]
    assert server["AssociatedBundleIdentifiers"] == "com.carriez.rustdesk"


def test_the_scripts_unload_before_and_load_all_three_after(laid_out):
    staged, _signed, _checked = laid_out
    scripts = staged["scripts"]

    preinstall = (scripts / "preinstall").read_text()
    postinstall = (scripts / "postinstall").read_text()

    assert "launchctl bootout system/com.neutrino.agent" in preinstall
    assert "launchctl bootout system/com.carriez.RustDesk_service" in preinstall
    assert (
        "launchctl bootstrap system /Library/LaunchDaemons/com.neutrino.agent.plist"
        in postinstall
    )
    assert (
        "launchctl bootstrap system "
        "/Library/LaunchDaemons/com.carriez.RustDesk_service.plist" in postinstall
    )
    assert (
        'launchctl bootstrap gui/"$seat" '
        "/Library/LaunchAgents/com.carriez.RustDesk_server.plist" in postinstall
    )
    assert "stat -f %u /dev/console" in postinstall
    assert postinstall.index('mkdir -p "/Library/Logs/Neutrino/agent"') < (
        postinstall.index("launchctl bootstrap")
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
