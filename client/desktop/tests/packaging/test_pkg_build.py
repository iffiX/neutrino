"""The launchd jobs and install scripts a package root carries, the
pkgbuild command that takes them, and the read back of every Mach-O file's
load references; Apple's tools are stood in for."""

import plistlib
import subprocess
from pathlib import Path

import pytest

from shared import pkg_build

MACH_O = b"\xcf\xfa\xed\xfe" + b"\0" * 12

# otool -L of cryptography's extension as the broken macOS hub carried it.
HOMEBREW_LISTING = """\
/build/app/cryptography/hazmat/bindings/_rust.abi3.so:
\t/usr/local/opt/openssl@3/lib/libssl.3.dylib (compatibility version 3.0.0, current version 3.0.0)
\t/usr/local/opt/openssl@3/lib/libcrypto.3.dylib (compatibility version 3.0.0, current version 3.0.0)
\t/System/Library/Frameworks/Security.framework/Versions/A/Security (compatibility version 1.0.0, current version 61123.1.1)
\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0, current version 1351.0.0)
"""

# A library whose own name, which otool -L lists first, is outside the
# system, and which loads only the system and the tree.
FRAMEWORK_LISTING = """\
/build/app/Python:
\t/Library/Frameworks/Python.framework/Versions/3.13/Python (compatibility version 3.13.0, current version 3.13.0)
\t@loader_path/libintl.8.dylib (compatibility version 13.0.0, current version 13.0.0)
\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0, current version 1351.0.0)
"""
FRAMEWORK_INSTALL_NAMES = """\
/build/app/Python:
/Library/Frameworks/Python.framework/Versions/3.13/Python
"""

# A universal file: one header per architecture, the same references under
# each.
UNIVERSAL_LISTING = """\
/build/app/Contents/MacOS/lib dir/_objc.so (architecture x86_64):
\t@rpath/libffi.8.dylib (compatibility version 9.0.0, current version 9.2.0)
\tlibz.1.dylib (compatibility version 1.0.0, current version 1.2.12)
\t/opt/homebrew/opt/libffi/lib/libffi.8.dylib (compatibility version 9.0.0, current version 9.2.0, weak)
/build/app/Contents/MacOS/lib dir/_objc.so (architecture arm64):
\t@rpath/libffi.8.dylib (compatibility version 9.0.0, current version 9.2.0)
\tlibz.1.dylib (compatibility version 1.0.0, current version 1.2.12)
\t/opt/homebrew/opt/libffi/lib/libffi.8.dylib (compatibility version 9.0.0, current version 9.2.0, weak)
"""


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
        "EnvironmentVariables": {"LANG": "en_US.UTF-8"},
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


@pytest.mark.parametrize(
    "min_os_version, expected",
    [("", []), ("12.3", ["--compression", "latest", "--min-os-version", "12.3"])],
)
def test_a_floor_given_takes_the_strongest_compression_it_reads(
    monkeypatch, tmp_path, min_os_version, expected
):
    commands = []

    def run(command):
        commands.append(list(command))
        Path(command[-1]).write_bytes(b"xar!")

    monkeypatch.setattr(pkg_build, "_run", run)
    monkeypatch.setattr(pkg_build.shutil, "which", lambda name: f"/usr/bin/{name}")

    pkg_build.build(
        tmp_path / "root",
        tmp_path / "out.pkg",
        identifier="com.neutrino.hub",
        version="9.9.9",
        min_os_version=min_os_version,
    )

    pkgbuild = commands[0]
    found = pkgbuild[
        pkgbuild.index("--version") + 2 : pkgbuild.index("--install-location")
    ]
    assert found == expected


def test_a_homebrew_library_is_a_foreign_link():
    assert pkg_build.foreign_links(HOMEBREW_LISTING) == [
        "/usr/local/opt/openssl@3/lib/libssl.3.dylib",
        "/usr/local/opt/openssl@3/lib/libcrypto.3.dylib",
    ]


def test_the_system_and_the_tree_are_no_foreign_link_and_nor_is_the_own_name():
    assert pkg_build.foreign_links(FRAMEWORK_LISTING, FRAMEWORK_INSTALL_NAMES) == []


def test_the_line_naming_the_file_is_no_reference():
    listing = (
        "/usr/local/bin/nhub:\n"
        "\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0)\n"
    )

    assert pkg_build.foreign_links(listing) == []


def test_a_universal_files_bare_and_homebrew_names_are_named_once():
    assert pkg_build.foreign_links(UNIVERSAL_LISTING) == [
        "libz.1.dylib",
        "/opt/homebrew/opt/libffi/lib/libffi.8.dylib",
    ]


def test_a_macports_library_is_a_foreign_link():
    listing = (
        "/build/app/x.so:\n"
        "\t/opt/local/lib/libssl.3.dylib (compatibility version 3.0.0)\n"
    )

    assert pkg_build.foreign_links(listing) == ["/opt/local/lib/libssl.3.dylib"]


def _otool(listings: dict, install_names: dict, read: list):
    """A stand-in for subprocess.run answering otool -L and -D by file name."""

    def run(command, **kwargs):
        name = Path(command[-1]).name
        read.append([command[0], command[1], name])
        answers = listings if command[1] == "-L" else install_names
        return subprocess.CompletedProcess(
            command, 0, stdout=answers.get(name, ""), stderr=""
        )

    return run


def test_a_tree_loading_homebrew_is_refused_naming_the_file_and_reference(
    monkeypatch, tmp_path
):
    bindings = tmp_path / "cryptography" / "hazmat" / "bindings"
    bindings.mkdir(parents=True)
    (bindings / "_rust.abi3.so").write_bytes(MACH_O)
    (tmp_path / "nhub").write_bytes(MACH_O)
    (tmp_path / "notes.txt").write_text("not code")
    read = []
    monkeypatch.setattr(
        pkg_build.subprocess,
        "run",
        _otool({"_rust.abi3.so": HOMEBREW_LISTING}, {}, read),
    )

    with pytest.raises(SystemExit) as refused:
        pkg_build.require_system_links(tmp_path)

    message = str(refused.value)
    assert (
        "cryptography/hazmat/bindings/_rust.abi3.so: "
        "/usr/local/opt/openssl@3/lib/libssl.3.dylib"
    ) in message
    assert "libcrypto.3.dylib" in message
    assert "nhub:" not in message
    assert sorted(name for _tool, flag, name in read if flag == "-L") == [
        "_rust.abi3.so",
        "nhub",
    ]


def test_a_tree_loading_only_the_system_and_itself_passes(monkeypatch, tmp_path):
    (tmp_path / "Python").write_bytes(MACH_O)
    read = []
    monkeypatch.setattr(
        pkg_build.subprocess,
        "run",
        _otool(
            {"Python": FRAMEWORK_LISTING}, {"Python": FRAMEWORK_INSTALL_NAMES}, read
        ),
    )

    pkg_build.require_system_links(tmp_path)

    assert read == [["otool", "-L", "Python"], ["otool", "-D", "Python"]]


def test_otool_refusing_a_file_stops_the_build(monkeypatch, tmp_path):
    (tmp_path / "nhub").write_bytes(MACH_O)
    monkeypatch.setattr(
        pkg_build.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 1, stdout="", stderr="not an object file"
        ),
    )

    with pytest.raises(SystemExit) as refused:
        pkg_build.require_system_links(tmp_path)

    assert "not an object file" in str(refused.value)
