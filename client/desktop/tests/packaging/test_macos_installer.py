"""What the macOS installer carries, with every tool stood in for.

Neither the compiler nor Apple's tools run here — they need a Mac — so what
is asserted is the command each step is given: the compile into an app
bundle with the window's bindings named, the ad hoc signature, pkgbuild
over the package root and productbuild around it; the package root's own
shape, with the bundle under Applications, the data beside the compiled
package and the link on the path; the refusals for a machine that is not
a Mac of the pinned Python and machine; and the pins being well formed.
"""

import plistlib
import subprocess
from pathlib import Path

import pytest

import build_client_macos
import bundled
from shared import nuitka_build
import payload
from shared import pkg_build

# The licences the parts the tree holds add.
PARTS_LICENSES = [name for part in payload.parts() for name in part.CARRIED_LICENSES]


def darwin_build_machine(monkeypatch, *, machine="arm64", version=(3, 13, 7)):
    """Make this look like the Mac the build runs on."""
    monkeypatch.setattr(build_client_macos.sys, "platform", "darwin")
    monkeypatch.setattr(build_client_macos.sys, "version_info", version + ("final", 0))
    monkeypatch.setattr(build_client_macos.platform, "machine", lambda: machine)


def test_the_package_is_named_for_apple_silicon_and_intel():
    assert build_client_macos.MACOS_MACHINES == {"aarch64": "arm64", "x86_64": "amd64"}
    assert build_client_macos.macos_machine("arm64") == "arm64"
    assert build_client_macos.macos_machine("aarch64") == "arm64"
    assert build_client_macos.macos_machine("x86_64") == "amd64"
    assert payload.PACKAGE_NAME == "neutrino-client"

    with pytest.raises(SystemExit) as refused:
        build_client_macos.macos_machine("armhf")
    assert "armhf" in str(refused.value)


def test_an_intel_mac_of_the_pinned_python_builds_the_intel_package(monkeypatch):
    darwin_build_machine(monkeypatch, machine="x86_64")

    build_client_macos._check_build_machine("amd64")


def test_the_build_refuses_anything_but_a_mac(monkeypatch):
    darwin_build_machine(monkeypatch)
    monkeypatch.setattr(build_client_macos.sys, "platform", "linux")

    with pytest.raises(SystemExit) as refused:
        build_client_macos._check_build_machine("arm64")

    assert "Mac" in str(refused.value)


def test_the_build_refuses_another_interpreter_than_the_pinned_one(monkeypatch):
    """What runs the script is what the client is compiled against."""
    darwin_build_machine(monkeypatch, version=(3, 12, 4))

    with pytest.raises(SystemExit) as refused:
        build_client_macos._check_build_machine("arm64")

    assert "3.13" in str(refused.value)


def test_the_build_refuses_a_machine_this_is_not(monkeypatch):
    """The compile is native: an arm64 installer comes off an arm64 Mac."""
    darwin_build_machine(monkeypatch, machine="x86_64")

    with pytest.raises(SystemExit) as refused:
        build_client_macos._check_build_machine("arm64")

    assert "arm64" in str(refused.value)


def test_an_apple_silicon_mac_of_the_pinned_python_is_accepted(monkeypatch):
    darwin_build_machine(monkeypatch)

    build_client_macos._check_build_machine("arm64")


def test_the_compile_is_an_app_bundle_with_the_bindings_named(monkeypatch, tmp_path):
    """Standalone into a bundle, the package and every pyobjc wrapper the
    shell imports at window time included, the name, icon and version in
    the bundle, the binary called nclient."""
    commands = []

    def fake_run(command, env=None, **kwargs):
        commands.append((command, env))
        binary = tmp_path / "build" / "entry.app" / "Contents" / "MacOS" / "nclient"
        binary.parent.mkdir(parents=True, exist_ok=True)
        binary.write_bytes(b"\xcf\xfa\xed\xfe")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(nuitka_build.subprocess, "run", fake_run)
    monkeypatch.setattr(build_client_macos.icons, "write_icns", lambda path: path)
    tree = tmp_path / "tree"
    (tree / "neutrino_client" / "cli").mkdir(parents=True)

    app = build_client_macos._compile(
        Path("python3"), tree, tmp_path / "build", "9.9.9"
    )

    command, environment = commands[0]
    assert app == tmp_path / "build" / "entry.app"
    assert command[:3] == ["python3", "-m", "nuitka"]
    assert "--standalone" in command
    assert "--macos-create-app-bundle" in command
    assert "--include-package=neutrino_client" in command
    for name in ("objc", "Foundation", "AppKit", "WebKit"):
        assert f"--include-package={name}" in command
    assert "--macos-app-name=Neutrino Client" in command
    assert f"--macos-app-icon={tmp_path / 'bundle.icns'}" in command
    assert "--macos-app-version=9.9.9" in command
    assert "--macos-signed-app-name=com.neutrino.client" in command
    assert any(
        word.startswith(
            "--macos-app-protected-resource=NSLocalNetworkUsageDescription:"
        )
        for word in command
    )
    assert "--output-filename=nclient" in command
    assert command[-1] == str(tree / "neutrino_client" / "cli" / "entry.py")
    assert environment["PYTHONPATH"] == str(tree)


def test_a_compile_that_writes_no_bundle_is_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(
        nuitka_build.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0),
    )
    monkeypatch.setattr(build_client_macos.icons, "write_icns", lambda path: path)
    (tmp_path / "build").mkdir()

    with pytest.raises(SystemExit) as refused:
        build_client_macos._compile(Path("python3"), tmp_path, tmp_path / "build", "1")

    assert "app bundle" in str(refused.value)


def test_a_bundle_without_the_binary_is_refused(monkeypatch, tmp_path):
    def fake_run(command, env=None, **kwargs):
        (tmp_path / "build" / "entry.app" / "Contents" / "MacOS").mkdir(parents=True)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(nuitka_build.subprocess, "run", fake_run)
    monkeypatch.setattr(build_client_macos.icons, "write_icns", lambda path: path)

    with pytest.raises(SystemExit) as refused:
        build_client_macos._compile(Path("python3"), tmp_path, tmp_path / "build", "1")

    assert "nclient" in str(refused.value)


def test_the_build_environment_holds_the_compiler_and_the_pinned_wheels(
    monkeypatch, tmp_path
):
    commands = []
    staged = []

    def run(command, *, cwd=None):
        commands.append(list(command))

    def stage_wheels(python, target, wheels, **kwargs):
        staged.append((python, target, wheels))

    monkeypatch.setattr(build_client_macos.payload, "run", run)
    monkeypatch.setattr(build_client_macos.payload, "stage_wheels", stage_wheels)
    monkeypatch.setattr(
        build_client_macos.sys, "executable", "/opt/python3.13/bin/python3"
    )

    python = build_client_macos._make_build_environment(tmp_path / "venv")

    assert python == tmp_path / "venv" / "bin" / "python3"
    assert commands == [
        ["/opt/python3.13/bin/python3", "-m", "venv", str(tmp_path / "venv")],
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--quiet",
            "--only-binary=:all:",
            "--no-binary=nuitka",
            "nuitka==4.2.1",
        ],
    ]
    assert staged == [
        (
            python,
            tmp_path / "venv" / "lib" / "python3.13" / "site-packages",
            build_client_macos.MACOS_WHEELS,
        )
    ]


def test_the_package_root_carries_the_signed_bundle_and_the_link(monkeypatch, tmp_path):
    """The bundle under Applications with the data beside the compiled
    package and both carried binaries under Resources, signed after
    everything is in it, and nclient linked from /usr/local/bin."""
    darwin_build_machine(monkeypatch)
    order = []

    def make_environment(venv):
        order.append("venv")
        return venv / "bin" / "python3"

    def compile_app(python, tree, build, version):
        order.append("compile")
        app = build / "entry.app"
        (app / "Contents" / "MacOS").mkdir(parents=True)
        (app / "Contents" / "MacOS" / "nclient").write_bytes(b"")
        (app / "Contents" / "Info.plist").write_text("")
        return app

    def stage_binaries(contents, architecture):
        order.append(("binaries", architecture))
        (contents / "Resources" / "bin").mkdir(parents=True)
        (contents / "Resources" / "bin" / "cc-switch").write_text("")

    def sign(app):
        order.append(("sign", app))

    monkeypatch.setattr(build_client_macos, "_make_build_environment", make_environment)
    monkeypatch.setattr(build_client_macos, "_compile", compile_app)
    monkeypatch.setattr(
        build_client_macos.bundled, "stage_darwin_binaries", stage_binaries
    )
    monkeypatch.setattr(build_client_macos.pkg_build, "sign_ad_hoc", sign)
    monkeypatch.setattr(
        build_client_macos.pkg_build,
        "require_system_links",
        lambda directory: order.append(("links", directory)),
    )

    staged = build_client_macos._lay_out(tmp_path, "9.9.9", "arm64")

    app = tmp_path / "root" / "Applications" / "Neutrino Client.app"
    assert staged == {
        "root": tmp_path / "root",
        "app": app,
        "scripts": tmp_path / "scripts",
    }
    contents = app / "Contents"
    assert (contents / "MacOS" / "nclient").is_file()
    assert (
        contents / "MacOS" / "neutrino_client" / "data" / "gui" / "index.html"
    ).is_file()
    assert (contents / "Resources" / "bin" / "cc-switch").is_file()
    assert sorted(
        path.name for path in (contents / "Resources" / "licenses").iterdir()
    ) == sorted(
        PARTS_LICENSES
        + [
            "cc_switch.txt",
            "easytier.txt",
            "meslolgs_nf.txt",
            "rustdesk.txt",
            "xterm.txt",
        ]
    )
    assert order == [
        "venv",
        "compile",
        ("binaries", "arm64"),
        ("links", app),
        ("sign", app),
    ]
    link = tmp_path / "root" / "usr" / "local" / "bin" / "nclient"
    assert link.is_symlink()
    assert Path(link.readlink()) == Path(
        "/Applications/Neutrino Client.app/Contents/MacOS/nclient"
    )
    assert not list((tmp_path / "root").glob("**/LaunchAgents"))
    daemons = sorted(
        path.name for path in (tmp_path / "root/Library/LaunchDaemons").iterdir()
    )
    assert daemons == sorted(
        [f"{daemon['label']}.plist" for daemon in build_client_macos.PART_DAEMONS]
        + ["com.neutrino.client.easytier.plist"]
    )


def test_the_bundle_is_signed_ad_hoc_and_deep(monkeypatch, tmp_path):
    commands = []
    monkeypatch.setattr(pkg_build, "_run", commands.append)

    pkg_build.sign_ad_hoc(tmp_path / "Neutrino Client.app")

    assert commands == [
        [
            "codesign",
            "--force",
            "--deep",
            "--sign",
            "-",
            str(tmp_path / "Neutrino Client.app"),
        ]
    ]


def test_pkgbuild_wraps_the_root_and_productbuild_wraps_the_component(
    monkeypatch, tmp_path
):
    commands = []

    def run(command):
        commands.append(list(command))
        if "--analyze" in command:
            Path(command[-1]).write_bytes(plistlib.dumps([]))
            return
        Path(command[-1]).write_bytes(b"xar!")

    monkeypatch.setattr(pkg_build, "_run", run)
    monkeypatch.setattr(pkg_build.shutil, "which", lambda name: f"/usr/bin/{name}")
    target = tmp_path / "neutrino-client-9.9.9-macos-arm64.pkg"

    pkg_build.build(
        tmp_path / "root", target, identifier="com.neutrino.client", version="9.9.9"
    )

    component = tmp_path / "com.neutrino.client.component.pkg"
    plist = tmp_path / "com.neutrino.client.component.plist"
    assert commands == [
        ["pkgbuild", "--analyze", "--root", str(tmp_path / "root"), str(plist)],
        [
            "pkgbuild",
            "--root",
            str(tmp_path / "root"),
            "--identifier",
            "com.neutrino.client",
            "--version",
            "9.9.9",
            "--component-plist",
            str(plist),
            "--install-location",
            "/",
            str(component),
        ],
        ["productbuild", "--package", str(component), str(target)],
    ]
    assert target.is_file()
    assert not component.exists()


def test_a_mac_without_the_tools_is_told_what_to_install(monkeypatch, tmp_path):
    monkeypatch.setattr(pkg_build.shutil, "which", lambda name: None)

    with pytest.raises(SystemExit) as refused:
        pkg_build.build(
            tmp_path,
            tmp_path / "out.pkg",
            identifier="com.neutrino.client",
            version="1",
        )

    assert "xcode-select --install" in str(refused.value)


def test_the_installer_registers_no_login_item_and_the_client_no_service():
    """The client runs when the person opens it, not with the session."""
    source = Path(build_client_macos.__file__).read_text(encoding="utf-8")

    assert "LaunchAgents" not in source
    assert "gui --hidden" not in source


def daemon(tmp_path, label) -> dict:
    """One LaunchDaemon the build writes, read back."""
    import plistlib

    build_client_macos.write_daemons(tmp_path)
    path = tmp_path / "Library" / "LaunchDaemons" / f"{label}.plist"
    return plistlib.loads(path.read_bytes())


def test_the_easytier_job_is_the_clients_own_daemon_kept_running(tmp_path):
    """The daemon decides when the core runs; launchd only keeps it up."""
    job = daemon(tmp_path, "com.neutrino.client.easytier")

    assert job["ProgramArguments"] == [
        "/Applications/Neutrino Client.app/Contents/MacOS/nclient",
        "easytier-daemon",
    ]
    assert job["RunAtLoad"] is True
    assert job["KeepAlive"] is True
    assert "easytier-core" not in " ".join(job["ProgramArguments"])


def test_the_install_scripts_unload_then_make_the_directories_and_load(tmp_path):
    assert 'launchctl bootout "system/$label"' in build_client_macos.PREINSTALL
    assert "chmod 700" in build_client_macos.POSTINSTALL
    assert "chown root:wheel" in build_client_macos.POSTINSTALL
    assert (
        'start_daemon "$label" "/Library/LaunchDaemons/$label.plist"'
        in build_client_macos.POSTINSTALL
    )
    assert "|| true" not in build_client_macos.POSTINSTALL
    assert 'echo "  These services did not start:$failed" >&2\n    exit 1' in (
        build_client_macos.POSTINSTALL
    )
    assert (
        '"/Library/Application Support/Neutrino/client/state/easytier"'
        in build_client_macos.POSTINSTALL
    )
    assert 'mkdir -p "/Library/Logs/Neutrino/client"' in build_client_macos.POSTINSTALL
    for script in (build_client_macos.PREINSTALL, build_client_macos.POSTINSTALL):
        assert script.startswith("#!/bin/sh\n") and script.endswith("exit 0\n")


def test_each_daemon_writes_into_the_clients_log_directory(tmp_path):
    easytier = daemon(tmp_path, "com.neutrino.client.easytier")

    for added in build_client_macos.PART_DAEMONS:
        job = daemon(tmp_path, added["label"])
        assert job["StandardOutPath"].startswith("/Library/Logs/Neutrino/client/")
    assert easytier["StandardOutPath"] == "/Library/Logs/Neutrino/client/easytier.log"


def test_the_build_pins_what_the_other_platforms_pin():
    assert build_client_macos.BUILD_PYTHON_VERSION == (3, 13)
    assert not hasattr(build_client_macos, "NUITKA_VERSION")
    assert not hasattr(payload, "NUITKA_VERSION")
    assert nuitka_build.NUITKA_VERSION == "4.2.1"
    assert build_client_macos.CLIENT_BINARY_NAME == payload.CLIENT_BINARY_NAME
    assert build_client_macos.APP_BUNDLE_NAME == "Neutrino Client.app"
    assert build_client_macos.PACKAGE_IDENTIFIER == "com.neutrino.client"


def test_the_macos_wheels_are_pinned_to_the_file_at_one_version():
    names = []
    for name, version, url, digest in build_client_macos.MACOS_WHEELS:
        names.append(name)
        assert version == build_client_macos.PYOBJC_VERSION
        assert url.startswith("https://files.pythonhosted.org/")
        assert "cp313-cp313-macosx" in url
        assert url.endswith("universal2.whl")
        assert version in url
        assert len(digest) == 64
        assert digest == digest.lower()
    assert names == ["pyobjc-core", "pyobjc-framework-Cocoa", "pyobjc-framework-WebKit"]


def test_the_compile_names_every_package_the_shell_imports():
    for name in ("objc", "Foundation", "AppKit", "WebKit"):
        assert name in build_client_macos.PYOBJC_PACKAGES


def test_the_licences_travel_inside_the_bundle(tmp_path):
    build_client_macos._stage_licenses(tmp_path / "licenses")

    assert sorted(path.name for path in (tmp_path / "licenses").iterdir()) == sorted(
        PARTS_LICENSES
        + [
            "cc_switch.txt",
            "easytier.txt",
            "meslolgs_nf.txt",
            "rustdesk.txt",
            "xterm.txt",
        ]
    )


def test_the_carried_binaries_land_where_the_runtime_looks():
    """The bundle's Contents is what the staging is handed, and what the
    runtime resolver walks up to."""
    from neutrino_client.constants import CLIENT_BUNDLED_PATHS_DARWIN

    assert CLIENT_BUNDLED_PATHS_DARWIN["cc-switch"].startswith(
        bundled.DARWIN_RESOURCES_DIR + "/"
    )
    assert CLIENT_BUNDLED_PATHS_DARWIN["rustdesk"].startswith(
        bundled.DARWIN_RESOURCES_DIR + "/"
    )
