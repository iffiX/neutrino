"""What every client package carries, staged into a temporary tree.

The parts that reach the network are not exercised here; what is, is the
shape they produce — where the client package lands, what is stamped into
it, what the page and icon are copied to, what is taken out of a carried
interpreter, which machines the packages are published for, and which
licences the package owes.
"""

import subprocess
import sys

import pytest

import payload


def _carried_interpreter(root):
    """A staged interpreter whose python3 is the one running the tests.

    Args:
        root: The staging directory.

    Returns:
        The staged interpreter tree.
    """
    staged_python = root / "opt" / "neutrino_client" / "python"
    (staged_python / "bin").mkdir(parents=True)
    (staged_python / "bin" / "python3").symlink_to(sys.executable)
    return staged_python


def _prune(prefix, listing):
    """Run the maintainer scripts' own prune over a tree.

    Args:
        prefix: The prefix to prune.
        listing: A file holding the paths the package manager tracks.
    """
    script = (
        "set -e"
        + "\n"
        + payload.PRUNE_UNTRACKED
        + f'prune_untracked "{prefix}" <"{listing}"\n'
    )
    result = subprocess.run(["sh", "-c", script], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr


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


def test_the_staged_tree_carries_the_desktop_entries_and_the_policy(tmp_path):
    staged = payload.stage_client_tree(tmp_path / "site-packages", "9.9.9")

    desktop = staged / "data" / "desktop"
    assert (desktop / "neutrino_client.desktop").is_file()
    assert (desktop / "neutrino_client_autostart.desktop").is_file()
    assert (staged / "data" / "polkit" / "com.neutrino.client.mount.policy").is_file()


def test_the_staged_tree_takes_the_builds_own_umask_off(tmp_path):
    staged = payload.stage_client_tree(tmp_path / "site-packages", "9.9.9")

    assert (staged / "cli" / "entry.py").stat().st_mode & 0o777 == 0o644
    assert (staged / "cli").stat().st_mode & 0o777 == 0o755


def test_no_bytecode_of_the_build_machines_own_is_carried(tmp_path):
    staged = payload.stage_client_tree(tmp_path / "site-packages", "9.9.9")

    assert list(staged.rglob("__pycache__")) == []
    assert list(staged.rglob("*.pyc")) == []


def test_a_carried_interpreter_loses_what_draws_no_window(tmp_path):
    staged_python = _carried_interpreter(tmp_path)
    library = staged_python / "lib" / "python3.13"
    (library / "tkinter").mkdir(parents=True)
    (library / "tkinter" / "__init__.py").write_text("")
    (library / "idlelib").mkdir()
    (staged_python / "lib" / "libtcl8.6.so").write_text("")
    (library / "lib-dynload").mkdir()
    (library / "lib-dynload" / "_tkinter.cpython-313.so").write_text("")
    (staged_python / "bin" / "idle3").write_text("")

    payload.trim_interpreter(staged_python)

    assert not (library / "tkinter").exists()
    assert not (library / "idlelib").exists()
    assert not (staged_python / "lib" / "libtcl8.6.so").exists()
    assert not (library / "lib-dynload" / "_tkinter.cpython-313.so").exists()
    assert not (staged_python / "bin" / "idle3").exists()


def test_the_build_machines_own_paths_are_taken_back_out(tmp_path):
    staged_python = _carried_interpreter(tmp_path)
    script = staged_python / "bin" / "something"
    script.write_text(f"#!{tmp_path}/opt/neutrino_client/python/bin/python3\n")

    payload.strip_build_paths(staged_python, tmp_path)

    assert script.read_text() == "#!/opt/neutrino_client/python/bin/python3\n"


def test_site_packages_is_found_and_a_tree_without_one_is_refused(tmp_path):
    staged_python = _carried_interpreter(tmp_path)
    with pytest.raises(SystemExit):
        payload.site_packages_of(staged_python)

    wanted = staged_python / "lib" / "python3.13" / "site-packages"
    wanted.mkdir(parents=True)

    assert payload.site_packages_of(staged_python) == wanted


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


def test_the_prune_removes_what_the_package_did_not_install(tmp_path):
    prefix = tmp_path / "opt" / "neutrino_client"
    (prefix / "python" / "lib").mkdir(parents=True)
    tracked = prefix / "python" / "lib" / "kept.py"
    tracked.write_text("")
    stray = prefix / "python" / "lib" / "stray.pyc"
    stray.write_text("")
    (prefix / "python" / "empty").mkdir()
    listing = tmp_path / "listing"
    listing.write_text(f"{prefix}\n{prefix / 'python'}\n{tracked}\n")

    _prune(prefix, listing)

    assert tracked.is_file()
    assert not stray.exists()
    assert not (prefix / "python" / "empty").exists()


def test_an_empty_listing_removes_nothing(tmp_path):
    prefix = tmp_path / "opt" / "neutrino_client"
    prefix.mkdir(parents=True)
    kept = prefix / "kept.py"
    kept.write_text("")
    listing = tmp_path / "listing"
    listing.write_text("")

    _prune(prefix, listing)

    assert kept.is_file()


def test_the_bytecode_pass_compiles_the_carried_tree(tmp_path):
    staged_python = _carried_interpreter(tmp_path)
    library = staged_python / "lib" / "python3.13"
    library.mkdir(parents=True)
    (library / "module.py").write_text("VALUE = 1\n")

    payload.compile_bytecode(staged_python, payload.PYTHON_DIR)

    written = list(library.rglob("*.pyc"))
    assert len(written) == 1
    assert written[0].name.startswith("module.cpython-")
