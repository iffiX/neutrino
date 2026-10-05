"""What the hub's macOS installer carries, with every tool stood in for.

Neither the compiler nor Apple's tools run here, so what is asserted is the
package root the build lays out and the scripts it writes: the standalone
hub under the hub's directory of the one Neutrino tree with its data beside
it, the programs it drives under ``bin``, the geodata and the agent's own
package in the state directory with the manifest naming every agent
package, the link on the path, the LaunchDaemon running ``nhub run``, the
postinstall making the roots and starting the job, the ``Neutrino Hub``
application entry, and the name the release publishes it under.
"""

import json
import plistlib
import subprocess
from pathlib import Path

import pytest

import build_hub_macos
import compiled_tree

AGENT_PACKAGES = (
    "neutrino-agent-9.9.9-macos-arm64.pkg",
    "neutrino-agent-9.9.9-macos-amd64.pkg",
    "neutrino-agent-9.9.9-windows-amd64.msi",
    "neutrino-agent_9.9.9_amd64.deb",
)


@pytest.fixture
def agent_packages(tmp_path):
    directory = tmp_path / "agents"
    directory.mkdir()
    for name in AGENT_PACKAGES:
        (directory / name).write_bytes(name.encode())
    return directory


def _laid_out(tmp_path, monkeypatch, agent_packages, machine):
    signed = []
    staged_programs = []

    def compile_standalone(python, entry, output_dir, binary_name, **kwargs):
        staged_programs.append(("compile", kwargs["options"]))
        dist = output_dir / "entry.dist"
        dist.mkdir(parents=True)
        (dist / binary_name).write_bytes(b"\xcf\xfa\xed\xfe" + b"\0" * 12)
        (dist / "libpython3.13.dylib").write_bytes(b"\xcf\xfa\xed\xfe" + b"\0" * 12)
        return dist

    def stage_programs(binaries, os_name, arch):
        staged_programs.append((os_name, arch))
        binaries.mkdir(parents=True)
        for name in ("xray", "cli-proxy-api", "netbird", "easytier-core"):
            (binaries / name).write_bytes(b"\xcf\xfa\xed\xfe" + b"\0" * 12)

    def stage_geodata(geodata):
        geodata.mkdir(parents=True)
        (geodata / "geoip.dat").write_bytes(b"db")

    monkeypatch.setattr(build_hub_macos, "_check_build_machine", lambda machine: None)
    monkeypatch.setattr(compiled_tree.venv_tree, "require_built_frontend", lambda: None)
    monkeypatch.setattr(
        compiled_tree, "make_build_environment", lambda venv: Path("python3")
    )
    monkeypatch.setattr(
        compiled_tree.nuitka_build, "compile_standalone", compile_standalone
    )
    monkeypatch.setattr(build_hub_macos.hub_assets, "stage_programs", stage_programs)
    monkeypatch.setattr(build_hub_macos.hub_assets, "stage_geodata", stage_geodata)
    monkeypatch.setattr(build_hub_macos.pkg_build, "sign_ad_hoc", signed.append)
    monkeypatch.setattr(
        build_hub_macos.pkg_build,
        "require_system_links",
        lambda directory: staged_programs.append(("links", directory, len(signed))),
    )

    staged = build_hub_macos._lay_out(
        tmp_path / "work",
        "9.9.9",
        machine,
        agent_packages=agent_packages,
        url_base="https://example.invalid/v9.9.9",
    )
    return staged, signed, staged_programs


@pytest.fixture
def laid_out(tmp_path, monkeypatch, agent_packages):
    return _laid_out(tmp_path, monkeypatch, agent_packages, "arm64")


def read_plist(root: Path, label: str) -> dict:
    return plistlib.loads(
        (root / "Library/LaunchDaemons" / f"{label}.plist").read_bytes()
    )


APP = "Library/Application Support/Neutrino/hub/app"
STATE = "Library/Application Support/Neutrino/hub/state"


def test_the_hub_lands_in_its_directory_of_the_tree_linked_on_the_path(laid_out):
    staged, _signed, _calls = laid_out
    root = staged["root"]

    app = root / APP
    assert (app / "nhub").is_file()
    assert (app / "neutrino_hub" / "data" / "manifests" / "vscode.json").is_file()
    assert (app / "neutrino_hub" / "data" / "resources").is_dir()
    assert (app / "licenses").is_dir()
    link = root / "usr/local/bin/nhub"
    assert link.is_symlink()
    assert str(link.readlink()) == f"/{APP}/nhub"


def test_the_compile_names_the_packages_imported_by_string(laid_out):
    _staged, _signed, calls = laid_out

    (options,) = [call[1] for call in calls if call[0] == "compile"]
    assert "--include-package=neutrino_hub" in options
    assert "--include-package=uvicorn" in options


def test_the_stamp_names_the_macos_package_with_the_version_open(tmp_path, laid_out):
    staged, _signed, _calls = laid_out

    stamp = (tmp_path / "work" / "tree" / "neutrino_hub" / "_version.py").read_text()
    assert 'HUB_VERSION = "9.9.9"' in stamp
    assert 'HUB_PACKAGE_ASSET = "neutrino-hub-{version}-macos-arm64.pkg"' in stamp


def test_the_programs_are_the_macs_own_under_bin(laid_out):
    staged, _signed, calls = laid_out

    assert ("darwin", "arm64") in calls
    assert (staged["root"] / APP / "bin" / "xray").is_file()


def test_an_intel_package_takes_the_intel_programs_and_agent(
    tmp_path, monkeypatch, agent_packages
):
    staged, _signed, calls = _laid_out(tmp_path, monkeypatch, agent_packages, "amd64")

    assert ("darwin", "amd64") in calls
    cache = staged["root"] / STATE / "agent_cache"
    assert sorted(path.name for path in cache.iterdir()) == [
        "neutrino-agent-9.9.9-macos-amd64.pkg"
    ]


def test_the_state_carries_the_geodata_and_the_agent_of_this_machine(laid_out):
    staged, _signed, _calls = laid_out
    state = staged["root"] / STATE

    assert (state / "geodata" / "geoip.dat").is_file()
    assert sorted(path.name for path in (state / "agent_cache").iterdir()) == [
        "neutrino-agent-9.9.9-macos-arm64.pkg"
    ]


def test_the_manifest_names_every_agent_package_with_its_release_url(laid_out):
    staged, _signed, _calls = laid_out

    manifest = json.loads(
        (staged["root"] / APP / "neutrino_hub/data/agent_packages.json").read_text()
    )
    assert sorted(manifest) == ["deb-amd64", "msi-amd64", "pkg-amd64", "pkg-arm64"]
    assert manifest["pkg-arm64"]["url"] == (
        "https://example.invalid/v9.9.9/neutrino-agent-9.9.9-macos-arm64.pkg"
    )
    assert len(manifest["pkg-arm64"]["sha256"]) == 64


def test_no_agent_for_this_machine_stops_the_build(tmp_path, monkeypatch):
    agents = tmp_path / "agents"
    agents.mkdir()
    (agents / "neutrino-agent-9.9.9-macos-amd64.pkg").write_bytes(b"x")

    with pytest.raises(SystemExit) as refused:
        _laid_out(tmp_path, monkeypatch, agents, "arm64")

    assert "no agent pkg for arm64" in str(refused.value)


def test_every_mach_o_file_is_signed_and_nothing_else(laid_out):
    staged, signed, _calls = laid_out
    app = staged["root"] / APP
    entry = staged["root"] / "Applications" / "Neutrino Hub.app"

    assert signed[-1] == entry
    signed = signed[:-1]
    assert sorted(path.name for path in signed) == [
        "cli-proxy-api",
        "easytier-core",
        "libpython3.13.dylib",
        "netbird",
        "nhub",
        "xray",
    ]
    assert all(str(path).startswith(str(app)) for path in signed)


def test_the_whole_app_tree_is_read_back_for_its_links_before_signing(laid_out):
    staged, _signed, calls = laid_out

    assert [call for call in calls if call[0] == "links"] == [
        ("links", staged["root"] / APP, 0)
    ]


def test_the_daemon_runs_nhub_run_into_the_hubs_log(laid_out):
    staged, _signed, _calls = laid_out

    job = read_plist(staged["root"], "com.neutrino.hub")

    assert job["ProgramArguments"] == [f"/{APP}/nhub", "run"]
    assert job["StandardOutPath"] == "/Library/Logs/Neutrino/hub/hub.log"
    assert job["RunAtLoad"] is True
    assert job["KeepAlive"] is True
    assert job["EnvironmentVariables"] == {"LANG": "en_US.UTF-8"}


def test_the_postinstall_makes_the_roots_and_starts_the_service(
    laid_out,
):
    staged, _signed, _calls = laid_out
    postinstall = (staged["scripts"] / "postinstall").read_text()

    for directory in ("config", "state"):
        assert f'"/Library/Application Support/Neutrino/hub/{directory}"' in (
            postinstall
        )
    assert "chown root:wheel" in postinstall
    assert "chmod 700" in postinstall
    assert 'mkdir -p "/Library/Logs/Neutrino/hub"' in postinstall
    marker = str(build_hub_macos.RELOAD_MARKER)
    upgrade = postinstall.index(f'if [ -f "{marker}" ]')
    upgrade_end = postinstall.index("fi\n", upgrade)
    fresh = postinstall[upgrade_end:]
    assert (
        "start_daemon com.neutrino.hub /Library/LaunchDaemons/com.neutrino.hub.plist"
        in (fresh)
    )
    assert "launchctl kickstart system/com.neutrino.hub" in fresh
    assert '"/usr/local/bin/nhub" open --print' in fresh
    assert "kickstart" not in postinstall[:upgrade_end]
    for script in ("preinstall", "postinstall"):
        assert (staged["scripts"] / script).stat().st_mode & 0o111


def test_the_entry_is_a_bundle_whose_script_opens_the_panel(laid_out):
    staged, _signed, _calls = laid_out
    contents = staged["root"] / "Applications" / "Neutrino Hub.app" / "Contents"

    information = plistlib.loads((contents / "Info.plist").read_bytes())
    script = contents / "MacOS" / "Neutrino Hub"

    assert information["CFBundleExecutable"] == "Neutrino Hub"
    assert information["CFBundleName"] == "Neutrino Hub"
    assert information["CFBundlePackageType"] == "APPL"
    assert information["CFBundleShortVersionString"] == "9.9.9"
    assert information["CFBundleIconFile"] == "neutrino_hub"
    # The executable is a script: without the key Apple silicon asks for
    # Rosetta to open it.
    assert information["LSArchitecturePriority"] == ["arm64", "x86_64"]
    assert script.read_text() == '#!/bin/sh\nexec "/usr/local/bin/nhub" open\n'
    assert script.stat().st_mode & 0o111
    assert (contents / "Resources" / "neutrino_hub.icns").read_bytes()[:4] == b"icns"


def test_the_preinstall_marks_a_loaded_service_for_loading_again(tmp_path):
    """An upgrade over a set-up hub leaves it running; a fresh install does
    not start it."""
    marker = tmp_path / "state" / ".reload"
    marker.parent.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    launchctl = bin_dir / "launchctl"
    launchctl.write_text('#!/bin/sh\n[ "$1" = print ] && exit "$LOADED"\nexit 0\n')
    launchctl.chmod(0o755)
    script = build_hub_macos.PREINSTALL.replace(
        str(build_hub_macos.RELOAD_MARKER), str(marker)
    )

    for loaded, expected in (("0", True), ("113", False)):
        subprocess.run(
            ["sh", "-c", script],
            check=True,
            env={"PATH": f"{bin_dir}:/usr/bin:/bin", "LOADED": loaded},
        )
        assert marker.exists() is expected


def test_the_package_is_named_the_way_the_release_publishes_it():
    assert build_hub_macos.pkg_name("0.5.0", "arm64") == (
        "neutrino-hub-0.5.0-macos-arm64.pkg"
    )
    assert build_hub_macos.pkg_name("0.5.0", "amd64") == (
        "neutrino-hub-0.5.0-macos-amd64.pkg"
    )
    assert build_hub_macos.macos_machine("x86_64") == "amd64"
    assert build_hub_macos.macos_machine("aarch64") == "arm64"
    with pytest.raises(SystemExit):
        build_hub_macos.macos_machine("armhf")


def test_the_build_refuses_anything_but_a_mac(monkeypatch):
    monkeypatch.setattr(build_hub_macos.sys, "platform", "linux")

    with pytest.raises(SystemExit) as refused:
        build_hub_macos._check_build_machine("arm64")
    assert "Mac" in str(refused.value)

    with pytest.raises(SystemExit) as refused:
        build_hub_macos._check_tools(False)
    assert "runs on macOS" in str(refused.value)


def test_the_build_refuses_a_machine_this_is_not(monkeypatch):
    monkeypatch.setattr(build_hub_macos.sys, "platform", "darwin")
    monkeypatch.setattr(compiled_tree.sys, "version_info", (3, 13, 7, "final", 0))
    monkeypatch.setattr(build_hub_macos.platform, "machine", lambda: "x86_64")

    with pytest.raises(SystemExit) as refused:
        build_hub_macos._check_build_machine("arm64")
    assert "arm64" in str(refused.value)

    build_hub_macos._check_build_machine("amd64")


def test_an_upgrade_starts_the_hub_again_or_fails_the_install(tmp_path):
    """The preinstall's bootout leaves launchd holding the label for a moment,
    and a bootstrap then answers "5: Input/output error"; the postinstall
    waits and tries again, and an install that cannot start the hub fails."""
    script = build_hub_macos.POSTINSTALL
    assert "|| true" not in script.split("launchctl kickstart")[0]
    reload_branch = script.split(str(build_hub_macos.RELOAD_MARKER))[2]
    assert reload_branch.index("start_daemon com.neutrino.hub ") < (
        reload_branch.index("exit 1")
    )
    assert script.index("start_daemon() {") < script.index(
        "start_daemon com.neutrino.hub "
    )


def test_an_intel_package_declares_its_entry_intel(tmp_path):
    bundle = build_hub_macos.write_app_entry(tmp_path, "9.9.9", "amd64")

    information = plistlib.loads((bundle / "Contents" / "Info.plist").read_bytes())
    assert information["LSArchitecturePriority"] == ["x86_64"]
