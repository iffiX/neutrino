"""What every client package carries, staged into a temporary tree.

The parts that reach the network are not exercised here; what is, is the
shape they produce — where the client package lands, what is stamped into
it, what the page and icon are copied to, what is taken out of a carried
interpreter, which machines the packages are published for, and which
licences the package owes.
"""

import io
import pathlib
import subprocess
import sys
import zipfile

import pytest

import payload


def test_the_machines_the_packages_are_published_for():
    """One machine, spelled several ways, and nothing else."""
    assert payload.machine_name("amd64") == "x86_64"
    assert payload.machine_name("x64") == "x86_64"
    assert payload.machine_name("arm64") == "aarch64"
    assert payload.machine_name("aarch64") == "aarch64"


@pytest.mark.parametrize("machine", ["armhf", "armv7l", "i386", "riscv64"])
def test_a_machine_with_no_interpreter_is_refused_by_name(machine):
    with pytest.raises(SystemExit) as refused:
        payload.machine_name(machine)

    assert machine in str(refused.value)


def test_the_version_is_the_one_the_pyproject_declares():
    declared = [
        line
        for line in (payload.CLIENT_ROOT / "pyproject.toml")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.startswith("version = ")
    ]

    assert payload.version() == declared[0].split('"')[1]


def test_the_client_tree_is_staged_with_its_version_stamped_in(tmp_path):
    """No format installs a .dist-info, so the version is stamped in."""
    staged = payload.stage_client_tree(tmp_path / "site-packages", "9.9.9")

    assert (staged / "cli" / "entry.py").is_file()
    assert (staged / "core" / "ws_client.py").is_file()
    assert 'CLIENT_VERSION = "9.9.9"' in (staged / "_version.py").read_text()


def test_the_staged_tree_carries_the_page_and_the_window_icon(tmp_path):
    staged = payload.stage_client_tree(tmp_path / "site-packages", "9.9.9")

    gui = staged / "data" / "gui"
    assert (gui / "index.html").is_file()
    assert (gui / "app.js").is_file()
    assert (gui / "style.css").is_file()
    assert (gui / "neutrino_client.png").is_file()


def test_the_staged_tree_carries_both_word_catalogs(tmp_path):
    """Package data, or the window opens with nothing to say."""
    staged = payload.stage_client_tree(tmp_path / "site-packages", "9.9.9")

    locales = staged / "data" / "gui" / "locales"
    assert sorted(path.name for path in locales.glob("*.json")) == [
        "en.json",
        "zh-CN.json",
    ]
    assert '"ui.tray.open"' in (locales / "en.json").read_text(encoding="utf-8")


def test_the_staged_tree_carries_an_icon_windows_can_load(tmp_path):
    """A .png is not an icon to Win32; without the .ico the tray goes grey."""
    staged = payload.stage_client_tree(tmp_path, "9.9.9")

    icon = staged / "data" / "gui" / "neutrino_client.ico"
    assert icon.is_file()
    assert icon.read_bytes()[:4] == b"\x00\x00\x01\x00"


def test_the_staged_tree_carries_the_desktop_entries_and_the_policy(tmp_path):
    staged = payload.stage_client_tree(tmp_path / "site-packages", "9.9.9")

    desktop = staged / "data" / "desktop"
    assert (desktop / "neutrino_client.desktop").is_file()
    assert not (desktop / "neutrino_client_autostart.desktop").exists()
    assert (staged / "data" / "polkit" / "com.neutrino.client.mount.policy").is_file()


def test_the_staged_tree_takes_the_builds_own_umask_off(tmp_path):
    staged = payload.stage_client_tree(tmp_path / "site-packages", "9.9.9")

    assert (staged / "cli" / "entry.py").stat().st_mode & 0o777 == 0o644
    assert (staged / "cli").stat().st_mode & 0o777 == 0o755


def test_no_bytecode_of_the_build_machines_own_is_carried(tmp_path):
    staged = payload.stage_client_tree(tmp_path / "site-packages", "9.9.9")

    assert list(staged.rglob("__pycache__")) == []
    assert list(staged.rglob("*.pyc")) == []


def test_the_compile_is_two_standalone_programs_against_the_pinned_interpreter(
    tmp_path, monkeypatch
):
    """The client with the window's bindings inside it, and the helper on
    its own; both from the staged tree, both against the build's Python."""
    commands = []
    python = tmp_path / "build" / "python" / "bin" / "python3"

    def stage_interpreter(staged_python, architecture):
        (staged_python / "bin").mkdir(parents=True)
        (staged_python / "bin" / "python3").write_text("")

    def run(command, *, cwd=None):
        commands.append(("pip", command))

    def fake_run(command, capture_output, text, env):
        commands.append(("nuitka", command, env))
        build = pathlib.Path(command[-2].split("=", 1)[1])
        name = command[-3].split("=", 1)[1]
        dist = build / (pathlib.Path(command[-1]).stem + ".dist")
        dist.mkdir(parents=True, exist_ok=True)
        (dist / name).write_text("")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(payload, "stage_linux_interpreter", stage_interpreter)
    monkeypatch.setattr(payload, "stage_linux_gui_bindings", lambda staged: None)
    monkeypatch.setattr(payload, "run", run)
    monkeypatch.setattr(payload.subprocess, "run", fake_run)

    compiled = payload.compile_linux(tmp_path / "build", "amd64", "9.9.9")

    assert commands[0] == (
        "pip",
        [str(python), "-m", "pip", "install", "--quiet", "nuitka==4.2.1"],
    )
    client, helper = commands[1], commands[2]
    assert client[1][:4] == [str(python), "-m", "nuitka", "--standalone"]
    assert "--include-package=neutrino_client" in client[1]
    assert "--include-module=gi" in client[1]
    assert client[1][-1].endswith("neutrino_client/cli/entry.py")
    assert client[2]["PYTHONPATH"] == str(tmp_path / "build" / "tree")
    assert "--include-package=neutrino_client" not in helper[1]
    assert helper[1][-1].endswith("neutrino_client/cli/mount_helper.py")
    assert (compiled["client"] / "nclient").is_file()
    assert (compiled["helper"] / "mount_helper").is_file()
    assert (compiled["package"] / "data" / "gui" / "index.html").is_file()


def test_a_compile_that_writes_no_binary_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(
        payload.subprocess,
        "run",
        lambda command, capture_output, text, env: subprocess.CompletedProcess(
            command, 0, "", ""
        ),
    )
    entry = tmp_path / "tree" / "neutrino_client" / "cli" / "entry.py"
    entry.parent.mkdir(parents=True)
    entry.write_text("")

    with pytest.raises(SystemExit) as refused:
        payload._compile_standalone(
            tmp_path / "python3",
            tmp_path / "tree",
            entry,
            tmp_path / "out",
            "nclient",
            (),
        )

    assert "nclient" in str(refused.value)


def test_the_compiled_programs_land_where_the_package_installs_them(tmp_path):
    """The client under the prefix with its data beside where a compiled
    module's __file__ points, a link on the path, and the helper's whole
    directory at the path polkit pins."""
    client = tmp_path / "client.dist"
    (client / "gi").mkdir(parents=True)
    (client / "nclient").write_text("")
    helper = tmp_path / "helper.dist"
    helper.mkdir()
    (helper / "mount_helper").write_text("")
    (helper / "libpython3.13.so.1.0").write_text("")
    package = payload.stage_client_tree(tmp_path / "tree", "9.9.9")
    tree = tmp_path / "pkg"

    payload.lay_out_compiled(
        tree,
        {"client": client, "helper": helper, "package": package},
        pathlib.Path("/usr/libexec/neutrino_client/mount_helper"),
    )

    prefix = tree / "opt" / "neutrino_client"
    assert (prefix / "nclient").is_file()
    assert (prefix / "gi").is_dir()
    assert (prefix / "neutrino_client" / "data" / "gui" / "index.html").is_file()
    assert (tree / "usr/libexec/neutrino_client/mount_helper").is_file()
    assert (tree / "usr/libexec/neutrino_client/libpython3.13.so.1.0").is_file()
    launcher = tree / "usr/bin/nclient"
    assert launcher.is_symlink()
    assert pathlib.Path(launcher.readlink()) == pathlib.Path(
        "/opt/neutrino_client/nclient"
    )


def test_the_licences_the_package_owes_are_staged(tmp_path):
    payload.stage_licenses(tmp_path)

    carried = tmp_path / "usr/share/doc/neutrino-client/licenses"
    assert sorted(path.name for path in carried.iterdir()) == [
        "cc_switch.txt",
        "rustdesk.txt",
    ]
    assert "MIT License" in (carried / "cc_switch.txt").read_text()
    assert "AFFERO" in (carried / "rustdesk.txt").read_text()


def test_a_licence_the_checkout_does_not_have_is_refused_by_name(tmp_path, monkeypatch):
    monkeypatch.setattr(payload, "CARRIED_LICENSES", ("nothing.txt",))

    with pytest.raises(SystemExit) as refused:
        payload.stage_licenses(tmp_path)

    assert "nothing.txt" in str(refused.value)


def test_a_wheels_console_scripts_are_not_carried(tmp_path, monkeypatch):
    """pip writes launcher stubs beside the packages; none ship."""
    wheel = io.BytesIO()
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("demo/__init__.py", "")
        archive.writestr(
            "demo-1.0.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: demo\nVersion: 1.0\n",
        )
        archive.writestr(
            "demo-1.0.dist-info/WHEEL",
            "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\n"
            "Tag: py3-none-any\n",
        )
        archive.writestr(
            "demo-1.0.dist-info/entry_points.txt",
            "[console_scripts]\ndemo = demo:main\n",
        )
        archive.writestr("demo-1.0.dist-info/RECORD", "")
    monkeypatch.setattr(payload, "fetch", lambda url, digest, what: wheel.getvalue())
    target = tmp_path / "lib"

    payload.stage_wheels(
        pathlib.Path(sys.executable),
        target,
        (("demo", "1.0", "https://example.invalid/demo-1.0-py3-none-any.whl", "0"),),
    )

    assert (target / "demo" / "__init__.py").is_file()
    assert not (target / "bin").exists()
    assert not (target / "Scripts").exists()
