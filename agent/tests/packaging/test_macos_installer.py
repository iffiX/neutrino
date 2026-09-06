"""What the macOS package carries, and where it says the framework lives.

Assembling the .pkg needs macOS: pkgutil expands the interpreter,
install_name_tool moves it and codesign signs what was moved. The parts that
decide where things point are pure, and are what is asserted here.
"""

import struct

import build_pkg
from neutrino_agent.platforms.darwin import DARWIN_AGENT_LABEL, DARWIN_AGENT_PLIST


def test_the_daemon_is_the_one_the_platform_reads_and_starts():
    """The package writes the plist the platform already boots by label; a
    second spelling would be a service nothing can start."""
    assert build_pkg.DARWIN_AGENT_LABEL == DARWIN_AGENT_LABEL
    assert build_pkg.DARWIN_AGENT_PLIST == DARWIN_AGENT_PLIST
    written = build_pkg.POSTINSTALL.format(
        plist=DARWIN_AGENT_PLIST, label=DARWIN_AGENT_LABEL
    )
    assert f"launchctl bootstrap system {DARWIN_AGENT_PLIST}" in written
    assert f"launchctl kickstart -k system/{DARWIN_AGENT_LABEL}" in written


def test_the_framework_is_carried_under_the_agent_s_own_prefix():
    """A machine's /Library/Frameworks is not a place this may install into,
    which is the whole reason the install names are rewritten."""
    assert str(build_pkg.DARWIN_FRAMEWORK_DIR).startswith("/opt/neutrino_agent")
    assert build_pkg.DARWIN_FRAMEWORK_ORIGIN.startswith("/Library/Frameworks")
    assert str(build_pkg.DARWIN_PYTHON).startswith(str(build_pkg.DARWIN_FRAMEWORK_HOME))


def test_every_name_under_the_origin_moves_to_the_carried_framework():
    moved = build_pkg._relocated(f"{build_pkg.DARWIN_FRAMEWORK_ORIGIN}/Python")

    assert moved == f"{build_pkg.DARWIN_FRAMEWORK_HOME}/Python"
    assert (
        build_pkg._relocated(f"{build_pkg.DARWIN_FRAMEWORK_ORIGIN}/lib/libssl.3.dylib")
        == f"{build_pkg.DARWIN_FRAMEWORK_HOME}/lib/libssl.3.dylib"
    )


def test_the_entry_point_runs_the_carried_interpreter():
    wrapper = build_pkg.WRAPPER.format(python=build_pkg.DARWIN_PYTHON)

    assert "/opt/neutrino_agent" in wrapper
    assert "-m neutrino_agent.cli.entry" in wrapper
    assert "/usr/bin/python3" not in wrapper


def test_only_mach_o_files_are_rewritten(tmp_path):
    """Walking the framework means opening scripts, data and text too."""
    mach_o = tmp_path / "Python"
    mach_o.write_bytes(struct.pack(">I", 0xCAFEBABE) + b"\x00" * 32)
    text = tmp_path / "README.txt"
    text.write_text("not a binary")
    empty = tmp_path / "empty"
    empty.write_bytes(b"")

    assert build_pkg._is_macho(mach_o)
    assert not build_pkg._is_macho(text)
    assert not build_pkg._is_macho(empty)


def test_the_shell_chain_is_carried_whole():
    """pywebview reaches WKWebView through pyobjc; a missing framework
    binding is an import error in a window nobody can open."""
    carried = {name for name, _, _, _ in build_pkg.DARWIN_WHEELS}

    assert carried == {
        "pywebview",
        "pyobjc-core",
        "pyobjc-framework-Cocoa",
        "pyobjc-framework-Quartz",
        "pyobjc-framework-WebKit",
        "pyobjc-framework-Security",
        "pyobjc-framework-UniformTypeIdentifiers",
        "bottle",
        "typing_extensions",
        "proxy_tools",
    }


def test_everything_carried_is_pinned_to_a_file():
    assert len(build_pkg.DARWIN_PYTHON_SHA256) == 64
    for _, _, url, digest in build_pkg.DARWIN_WHEELS:
        assert url.startswith("https://files.pythonhosted.org/")
        assert len(digest) == 64


def test_the_wheels_are_the_universal_ones():
    """One package for Intel and Apple Silicon means every compiled wheel in
    it carries both."""
    for name, _, url, _ in build_pkg.DARWIN_WHEELS:
        file_name = url.rsplit("/", 1)[-1]
        assert (
            file_name.endswith("universal2.whl")
            or "-any" in file_name
            or (file_name.endswith(".tar.gz"))
        ), name
