"""What the macOS installer carries, with every tool stood in for.

Neither the compiler nor Apple's tools run here — they need a Mac — so what
is asserted is the command each step is given: the compile into an app
bundle with the window's bindings named, the ad hoc signature, pkgbuild
over the package root and productbuild around it; the package root's own
shape, with the bundle under Applications, the data beside the compiled
package and the link on the path; the refusals for a machine that is not
an Apple Silicon Mac of the pinned Python; and the pins being well formed.
"""

import subprocess
from pathlib import Path

import pytest

import build_pkg
import bundled
import payload


def darwin_build_machine(monkeypatch, *, machine="arm64", version=(3, 13, 7)):
    """Make this look like the Mac the build runs on."""
    monkeypatch.setattr(build_pkg.sys, "platform", "darwin")
    monkeypatch.setattr(build_pkg.sys, "version_info", version + ("final", 0))
    monkeypatch.setattr(build_pkg.platform, "machine", lambda: machine)


def test_the_package_is_named_for_apple_silicon_alone():
    assert build_pkg.MACOS_MACHINES == {"aarch64": "arm64"}
    assert build_pkg.macos_machine("arm64") == "arm64"
    assert build_pkg.macos_machine("aarch64") == "arm64"
    assert payload.PACKAGE_NAME == "neutrino-client"

    with pytest.raises(SystemExit) as refused:
        build_pkg.macos_machine("amd64")
    assert "amd64" in str(refused.value)


def test_the_build_refuses_anything_but_a_mac(monkeypatch):
    darwin_build_machine(monkeypatch)
    monkeypatch.setattr(build_pkg.sys, "platform", "linux")

    with pytest.raises(SystemExit) as refused:
        build_pkg._check_build_machine("arm64")

    assert "Mac" in str(refused.value)


def test_the_build_refuses_another_interpreter_than_the_pinned_one(monkeypatch):
    """What runs the script is what the client is compiled against."""
    darwin_build_machine(monkeypatch, version=(3, 12, 4))

    with pytest.raises(SystemExit) as refused:
        build_pkg._check_build_machine("arm64")

    assert "3.13" in str(refused.value)


def test_the_build_refuses_a_machine_this_is_not(monkeypatch):
    """The compile is native: an arm64 installer comes off an arm64 Mac."""
    darwin_build_machine(monkeypatch, machine="x86_64")

    with pytest.raises(SystemExit) as refused:
        build_pkg._check_build_machine("arm64")

    assert "arm64" in str(refused.value)


def test_an_apple_silicon_mac_of_the_pinned_python_is_accepted(monkeypatch):
    darwin_build_machine(monkeypatch)

    build_pkg._check_build_machine("arm64")


def test_the_compile_is_an_app_bundle_with_the_bindings_named(monkeypatch, tmp_path):
    """Standalone into a bundle, the package and every pyobjc wrapper the
    shell imports at window time included, the name, icon and version in
    the bundle, the binary called nclient."""
    commands = []

    def fake_run(command, env=None):
        commands.append((command, env))
        binary = tmp_path / "build" / "entry.app" / "Contents" / "MacOS" / "nclient"
        binary.parent.mkdir(parents=True, exist_ok=True)
        binary.write_bytes(b"\xcf\xfa\xed\xfe")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(build_pkg.subprocess, "run", fake_run)
    monkeypatch.setattr(build_pkg.icons, "write_icns", lambda path: path)
    tree = tmp_path / "tree"
    (tree / "neutrino_client" / "cli").mkdir(parents=True)

    app = build_pkg._compile(Path("python3"), tree, tmp_path / "build", "9.9.9")

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
    assert "--output-filename=nclient" in command
    assert command[-1] == str(tree / "neutrino_client" / "cli" / "entry.py")
    assert environment["PYTHONPATH"] == str(tree)


def test_a_compile_that_writes_no_bundle_is_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(
        build_pkg.subprocess,
        "run",
        lambda command, env=None: subprocess.CompletedProcess(command, 0),
    )
    monkeypatch.setattr(build_pkg.icons, "write_icns", lambda path: path)
    (tmp_path / "build").mkdir()

    with pytest.raises(SystemExit) as refused:
        build_pkg._compile(Path("python3"), tmp_path, tmp_path / "build", "1")

    assert "app bundle" in str(refused.value)


def test_a_bundle_without_the_binary_is_refused(monkeypatch, tmp_path):
    def fake_run(command, env=None):
        (tmp_path / "build" / "entry.app" / "Contents" / "MacOS").mkdir(parents=True)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(build_pkg.subprocess, "run", fake_run)
    monkeypatch.setattr(build_pkg.icons, "write_icns", lambda path: path)

    with pytest.raises(SystemExit) as refused:
        build_pkg._compile(Path("python3"), tmp_path, tmp_path / "build", "1")

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

    monkeypatch.setattr(build_pkg.payload, "run", run)
    monkeypatch.setattr(build_pkg.payload, "stage_wheels", stage_wheels)
    monkeypatch.setattr(build_pkg.sys, "executable", "/opt/python3.13/bin/python3")

    python = build_pkg._make_build_environment(tmp_path / "venv")

    assert python == tmp_path / "venv" / "bin" / "python3"
    assert commands == [
        ["/opt/python3.13/bin/python3", "-m", "venv", str(tmp_path / "venv")],
        [str(python), "-m", "pip", "install", "--quiet", "nuitka==4.2.1"],
    ]
    assert staged == [
        (
            python,
            tmp_path / "venv" / "lib" / "python3.13" / "site-packages",
            build_pkg.MACOS_WHEELS,
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

    def stage_binaries(contents):
        order.append("binaries")
        (contents / "Resources" / "bin").mkdir(parents=True)
        (contents / "Resources" / "bin" / "cc-switch").write_text("")

    def sign(app):
        order.append(("sign", app))

    monkeypatch.setattr(build_pkg, "_make_build_environment", make_environment)
    monkeypatch.setattr(build_pkg, "_compile", compile_app)
    monkeypatch.setattr(build_pkg.bundled, "stage_darwin_binaries", stage_binaries)
    monkeypatch.setattr(build_pkg, "_sign", sign)

    staged = build_pkg._lay_out(tmp_path, "9.9.9", "arm64")

    app = tmp_path / "root" / "Applications" / "Neutrino Client.app"
    assert staged == {"root": tmp_path / "root", "app": app}
    contents = app / "Contents"
    assert (contents / "MacOS" / "nclient").is_file()
    assert (
        contents / "MacOS" / "neutrino_client" / "data" / "gui" / "index.html"
    ).is_file()
    assert (contents / "Resources" / "bin" / "cc-switch").is_file()
    assert sorted(
        path.name for path in (contents / "Resources" / "licenses").iterdir()
    ) == ["cc_switch.txt", "rustdesk.txt"]
    assert order == ["venv", "compile", "binaries", ("sign", app)]
    link = tmp_path / "root" / "usr" / "local" / "bin" / "nclient"
    assert link.is_symlink()
    assert Path(link.readlink()) == Path(
        "/Applications/Neutrino Client.app/Contents/MacOS/nclient"
    )
    assert not list((tmp_path / "root").glob("**/LaunchAgents"))


def test_the_bundle_is_signed_ad_hoc_and_deep(monkeypatch, tmp_path):
    commands = []
    monkeypatch.setattr(
        build_pkg.payload, "run", lambda command, cwd=None: commands.append(command)
    )

    build_pkg._sign(tmp_path / "Neutrino Client.app")

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

    def run(command, cwd=None):
        commands.append(list(command))
        Path(command[-1]).write_bytes(b"xar!")

    monkeypatch.setattr(build_pkg.payload, "run", run)
    monkeypatch.setattr(build_pkg.shutil, "which", lambda name: f"/usr/bin/{name}")
    target = tmp_path / "neutrino-client-9.9.9-macos-arm64.pkg"

    build_pkg._build(tmp_path / "root", target, "9.9.9")

    component = tmp_path / "com.neutrino.client.component.pkg"
    assert commands == [
        [
            "pkgbuild",
            "--root",
            str(tmp_path / "root"),
            "--identifier",
            "com.neutrino.client",
            "--version",
            "9.9.9",
            "--install-location",
            "/",
            str(component),
        ],
        ["productbuild", "--package", str(component), str(target)],
    ]
    assert target.is_file()
    assert not component.exists()


def test_a_mac_without_the_tools_is_told_what_to_install(monkeypatch, tmp_path):
    monkeypatch.setattr(build_pkg.shutil, "which", lambda name: None)

    with pytest.raises(SystemExit) as refused:
        build_pkg._build(tmp_path, tmp_path / "out.pkg", "1")

    assert "xcode-select --install" in str(refused.value)


def test_the_installer_registers_no_login_item_and_no_service():
    """The client runs when the person opens it, not with the session."""
    source = Path(build_pkg.__file__).read_text(encoding="utf-8")

    assert "LaunchAgents" not in source
    assert "LaunchDaemons" not in source
    assert "gui --hidden" not in source


def test_the_build_pins_what_the_other_platforms_pin():
    assert build_pkg.BUILD_PYTHON_VERSION == (3, 13)
    assert build_pkg.NUITKA_VERSION == payload.NUITKA_VERSION
    assert build_pkg.CLIENT_BINARY_NAME == payload.CLIENT_BINARY_NAME
    assert build_pkg.APP_BUNDLE_NAME == "Neutrino Client.app"
    assert build_pkg.PACKAGE_IDENTIFIER == "com.neutrino.client"


def test_the_macos_wheels_are_pinned_to_the_file_at_one_version():
    names = []
    for name, version, url, digest in build_pkg.MACOS_WHEELS:
        names.append(name)
        assert version == build_pkg.PYOBJC_VERSION
        assert url.startswith("https://files.pythonhosted.org/")
        assert "cp313-cp313-macosx" in url
        assert url.endswith("universal2.whl")
        assert version in url
        assert len(digest) == 64
        assert digest == digest.lower()
    assert names == ["pyobjc-core", "pyobjc-framework-Cocoa", "pyobjc-framework-WebKit"]


def test_the_compile_names_every_package_the_shell_imports():
    for name in ("objc", "Foundation", "AppKit", "WebKit"):
        assert name in build_pkg.PYOBJC_PACKAGES


def test_the_licences_travel_inside_the_bundle(tmp_path):
    build_pkg._stage_licenses(tmp_path / "licenses")

    assert sorted(path.name for path in (tmp_path / "licenses").iterdir()) == [
        "cc_switch.txt",
        "rustdesk.txt",
    ]


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
