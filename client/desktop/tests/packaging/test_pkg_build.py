"""The launchd jobs and install scripts a package root carries, and the
pkgbuild command that takes them; Apple's tools are stood in for."""

import plistlib
from pathlib import Path

from shared import pkg_build


def test_a_daemon_lands_under_launch_daemons_started_and_kept_alive(tmp_path):
    written = pkg_build.write_launchd_plist(
        tmp_path,
        label="com.neutrino.agent",
        program_arguments=["/usr/local/bin/nagent", "run"],
        log_path="/Library/Logs/neutrino_agent.log",
    )

    assert written == tmp_path / "Library/LaunchDaemons/com.neutrino.agent.plist"
    assert written.stat().st_mode & 0o777 == 0o644
    job = plistlib.loads(written.read_bytes())
    assert job == {
        "Label": "com.neutrino.agent",
        "ProgramArguments": ["/usr/local/bin/nagent", "run"],
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": "/Library/Logs/neutrino_agent.log",
        "StandardErrorPath": "/Library/Logs/neutrino_agent.log",
    }


def test_an_agent_lands_under_launch_agents_with_its_own_keys(tmp_path):
    written = pkg_build.write_launchd_plist(
        tmp_path,
        label="com.carriez.RustDesk_server",
        program_arguments=["/Applications/RustDesk.app/Contents/MacOS/RustDesk"],
        is_agent=True,
        extra={"LimitLoadToSessionType": "Aqua", "KeepAlive": False},
    )

    assert written.parent == tmp_path / "Library/LaunchAgents"
    job = plistlib.loads(written.read_bytes())
    assert job["LimitLoadToSessionType"] == "Aqua"
    assert job["KeepAlive"] is False
    assert "StandardOutPath" not in job


def test_only_the_scripts_given_are_written_and_executable(tmp_path):
    scripts = pkg_build.write_scripts(tmp_path / "scripts", postinstall="#!/bin/sh\n")

    assert [path.name for path in scripts.iterdir()] == ["postinstall"]
    assert (scripts / "postinstall").stat().st_mode & 0o111


def test_scripts_are_handed_to_pkgbuild(monkeypatch, tmp_path):
    commands = []

    def run(command):
        commands.append(list(command))
        Path(command[-1]).write_bytes(b"xar!")

    monkeypatch.setattr(pkg_build, "_run", run)
    monkeypatch.setattr(pkg_build.shutil, "which", lambda name: f"/usr/bin/{name}")

    pkg_build.build(
        tmp_path / "root",
        tmp_path / "out.pkg",
        identifier="com.neutrino.agent",
        version="9.9.9",
        scripts_dir=tmp_path / "scripts",
    )

    pkgbuild = commands[0]
    assert pkgbuild[pkgbuild.index("--scripts") + 1] == str(tmp_path / "scripts")
    assert pkgbuild[-3:] == [
        "--install-location",
        "/",
        str(tmp_path / "com.neutrino.agent.component.pkg"),
    ]
