"""The carried binaries: found under the install prefix, refused typed."""

import os

import neutrino_client.bundled as bundled


def test_a_checkout_carries_no_bundle(monkeypatch, tmp_path):
    monkeypatch.setattr(bundled, "CLIENT_INSTALL_PREFIX_LINUX", str(tmp_path))
    monkeypatch.setattr(bundled.os, "name", "posix")

    assert bundled.cc_switch_path() == ""
    assert bundled.rustdesk_path() == ""


def test_an_installed_bundle_is_found_under_the_prefix(monkeypatch, tmp_path):
    monkeypatch.setattr(bundled, "CLIENT_INSTALL_PREFIX_LINUX", str(tmp_path))
    monkeypatch.setattr(bundled.os, "name", "posix")
    for relative in ("bin/cc-switch", "rustdesk/rustdesk"):
        binary = tmp_path / relative
        binary.parent.mkdir(parents=True, exist_ok=True)
        binary.write_text("#!/bin/sh\n")
        binary.chmod(0o755)

    assert bundled.cc_switch_path() == str(tmp_path / "bin" / "cc-switch")
    assert bundled.rustdesk_path() == str(tmp_path / "rustdesk" / "rustdesk")


def test_a_binary_that_cannot_run_is_not_found(monkeypatch, tmp_path):
    monkeypatch.setattr(bundled, "CLIENT_INSTALL_PREFIX_LINUX", str(tmp_path))
    monkeypatch.setattr(bundled.os, "name", "posix")
    binary = tmp_path / "bin" / "cc-switch"
    binary.parent.mkdir(parents=True)
    binary.write_text("")
    binary.chmod(0o644)

    assert bundled.cc_switch_path() == ""


def test_windows_looks_next_to_the_package(monkeypatch):
    monkeypatch.setattr(bundled.os, "name", "nt")
    seen = []

    class FakePath:
        def __init__(self, *parts):
            self.parts = parts

        @property
        def parent(self):
            return FakePath(*self.parts[:-1])

        def __truediv__(self, other):
            return FakePath(*self.parts, other)

        def is_file(self):
            seen.append(os.path.join(*self.parts))
            return False

    monkeypatch.setattr(bundled, "_PACKAGE_DIR", FakePath("pkg", "neutrino_client"))

    assert bundled.rustdesk_path() == ""
    assert seen == [os.path.join("pkg", "bin\\rustdesk.exe")]


def test_macos_looks_under_the_bundles_resources(monkeypatch, tmp_path):
    """The compiled package runs from Contents/MacOS; the carried binaries
    are one directory up, under Contents/Resources."""
    monkeypatch.setattr(bundled.os, "name", "posix")
    monkeypatch.setattr(bundled.sys, "platform", "darwin")
    contents = tmp_path / "Neutrino Client.app" / "Contents"
    monkeypatch.setattr(bundled, "_PACKAGE_DIR", contents / "MacOS" / "neutrino_client")
    assert bundled.cc_switch_path() == ""

    for relative in (
        "Resources/bin/cc-switch",
        "Resources/rustdesk/RustDesk.app/Contents/MacOS/RustDesk",
    ):
        binary = contents / relative
        binary.parent.mkdir(parents=True, exist_ok=True)
        binary.write_text("#!/bin/sh\n")
        binary.chmod(0o755)

    assert bundled.cc_switch_path() == str(contents / "Resources/bin/cc-switch")
    assert bundled.rustdesk_path() == str(
        contents / "Resources/rustdesk/RustDesk.app/Contents/MacOS/RustDesk"
    )


def test_the_refusal_names_the_binary():
    assert bundled.bundle_missing("rustdesk") == {
        "code": "bundle_missing",
        "params": {"binary": "rustdesk"},
    }


def test_the_overlay_binaries_resolve_under_the_linux_prefix(monkeypatch, tmp_path):
    monkeypatch.setattr(bundled, "CLIENT_INSTALL_PREFIX_LINUX", str(tmp_path))
    monkeypatch.setattr(bundled.os, "name", "posix")
    monkeypatch.setattr(bundled.sys, "platform", "linux")
    for relative in (
        "netbird/netbird",
        "easytier/easytier-core",
        "easytier/easytier-cli",
    ):
        binary = tmp_path / relative
        binary.parent.mkdir(parents=True, exist_ok=True)
        binary.write_text("#!/bin/sh\n")
        binary.chmod(0o755)

    assert bundled.bundled_path("netbird") == str(tmp_path / "netbird" / "netbird")
    assert bundled.bundled_path("easytier-core") == str(
        tmp_path / "easytier" / "easytier-core"
    )
    assert bundled.bundled_path("easytier-cli") == str(
        tmp_path / "easytier" / "easytier-cli"
    )


def test_the_overlay_binaries_have_a_place_on_every_platform():
    from neutrino_client.constants import (
        CLIENT_BUNDLED_PATHS_DARWIN,
        CLIENT_BUNDLED_PATHS_LINUX,
        CLIENT_BUNDLED_PATHS_WINDOWS,
    )

    for table in (
        CLIENT_BUNDLED_PATHS_LINUX,
        CLIENT_BUNDLED_PATHS_WINDOWS,
        CLIENT_BUNDLED_PATHS_DARWIN,
    ):
        assert {"netbird", "easytier-core", "easytier-cli"} <= set(table)
    assert CLIENT_BUNDLED_PATHS_WINDOWS["netbird"] == "bin\\netbird.exe"
    assert CLIENT_BUNDLED_PATHS_DARWIN["easytier-cli"] == (
        "Resources/easytier/easytier-cli"
    )
