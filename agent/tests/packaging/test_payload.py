"""What both agent packages carry, staged into a temporary tree.

The parts that reach the network are not exercised here; what is, is the
shape they produce — where the agent package lands, what is stamped into it,
what is taken out of a carried interpreter, and which machines the packages
are published for.
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
    staged_python = root / "opt" / "neutrino_agent" / "python"
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
        "set -e\n"
        + payload.PRUNE_UNTRACKED
        + f'prune_untracked "{prefix}" <"{listing}"\n'
    )
    result = subprocess.run(["sh", "-c", script], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr


def test_the_machines_the_packages_are_published_for():
    """One machine, spelled several ways, and nothing else: the interpreter
    is published for these two and 32-bit ARM is not one."""
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
        for line in (payload.AGENT_ROOT / "pyproject.toml")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.startswith("version = ")
    ]

    assert payload.version() == declared[0].split('"')[1]


def test_the_agent_tree_is_staged_with_its_version_stamped_in(tmp_path):
    """No format installs a .dist-info, so the version is stamped in."""
    staged = payload.stage_agent_tree(tmp_path / "site-packages", "9.9.9")

    assert staged.name == "neutrino_agent"
    assert 'AGENT_VERSION = "9.9.9"' in (staged / "_version.py").read_text()
    assert (staged / "cli" / "entry.py").is_file()
    assert (staged / "data" / "systemd" / "neutrino_agent.service").is_file()
    assert not list(staged.rglob("__pycache__"))


def test_the_staged_tree_carries_no_build_machine_modes(tmp_path):
    """Whatever umask the build ran under does not belong in a package."""
    staged = payload.stage_agent_tree(tmp_path / "site-packages", "9.9.9")

    for path in staged.rglob("*"):
        expected = 0o755 if path.is_dir() else 0o644
        assert path.stat().st_mode & 0o777 == expected, path


def test_site_packages_is_found_in_a_carried_interpreter(tmp_path):
    site_packages = tmp_path / "lib" / "python3.13" / "site-packages"
    site_packages.mkdir(parents=True)

    assert payload.site_packages_of(tmp_path) == site_packages


def test_a_tree_with_no_interpreter_in_it_is_refused(tmp_path):
    with pytest.raises(SystemExit):
        payload.site_packages_of(tmp_path)


def test_the_carried_interpreter_loses_what_draws_no_window(tmp_path):
    """Tcl/Tk carries the rpath of the machine it was built on, which
    rpmbuild rejects outright."""
    library = tmp_path / "lib"
    (library / "python3.13" / "tkinter").mkdir(parents=True)
    (library / "python3.13" / "idlelib").mkdir(parents=True)
    (library / "python3.13" / "lib-dynload").mkdir(parents=True)
    (library / "tcl8.6").mkdir()
    (library / "libtcl8.6.so").write_bytes(b"")
    (library / "python3.13" / "lib-dynload" / "_tkinter.so").write_bytes(b"")
    (library / "python3.13" / "asyncio").mkdir()
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "idle3").write_text("")
    (tmp_path / "bin" / "python3").write_text("")

    payload.trim_interpreter(tmp_path)

    assert not (library / "python3.13" / "tkinter").exists()
    assert not (library / "python3.13" / "idlelib").exists()
    assert not (library / "tcl8.6").exists()
    assert not (library / "libtcl8.6.so").exists()
    assert not (library / "python3.13" / "lib-dynload" / "_tkinter.so").exists()
    assert not (tmp_path / "bin" / "idle3").exists()
    assert (library / "python3.13" / "asyncio").is_dir()
    assert (tmp_path / "bin" / "python3").is_file()


def test_the_staging_path_is_taken_out_of_everything_it_was_written_into(tmp_path):
    """pip writes the staging path into what it generates; left alone every
    one of those names a directory that exists only on the build machine."""
    staged_python = tmp_path / "opt" / "neutrino_agent" / "python"
    (staged_python / "bin").mkdir(parents=True)
    script = staged_python / "bin" / "something"
    script.write_text(f"#!{tmp_path}/opt/neutrino_agent/python/bin/python3\n")
    binary = staged_python / "bin" / "python3"
    binary.write_bytes(b"\x7fELF\x00\x01")

    payload.strip_build_paths(staged_python, tmp_path)

    assert script.read_text() == "#!/opt/neutrino_agent/python/bin/python3\n"
    assert binary.read_bytes() == b"\x7fELF\x00\x01"


def test_the_prefix_is_the_agent_s_own(tmp_path):
    """Not a directory under the hub's: a machine may run both, and removing
    the hub deletes /opt/neutrino whole."""
    assert str(payload.INSTALL_PREFIX) == "/opt/neutrino_agent"
    assert str(payload.PYTHON_DIR).startswith(str(payload.INSTALL_PREFIX))


def test_the_staged_tree_carries_bytecode_for_every_module(tmp_path):
    """A .pyc written after the install is in no package's file list, and a
    directory a later version drops cannot be removed over one."""
    staged_python = _carried_interpreter(tmp_path)
    package = staged_python / "lib" / "python3.13" / "site-packages" / "neutrino_agent"
    (package / "services").mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "entry.py").write_text("VALUE = 1\n")
    (package / "services" / "file.py").write_text("VALUE = 2\n")

    payload.compile_bytecode(staged_python, payload.PYTHON_DIR)

    for source in sorted(package.rglob("*.py")):
        assert list((source.parent / "__pycache__").glob(f"{source.stem}.*.pyc"))


def test_the_bytecode_records_the_path_the_package_installs_it_at(tmp_path):
    """The build machine's staging path is nowhere a traceback can name it."""
    staged_python = _carried_interpreter(tmp_path)
    site_packages = staged_python / "lib" / "python3.13" / "site-packages"
    site_packages.mkdir(parents=True)
    (site_packages / "entry.py").write_text("VALUE = 1\n")

    payload.compile_bytecode(staged_python, payload.PYTHON_DIR)

    compiled = next((site_packages / "__pycache__").glob("entry.*.pyc")).read_bytes()
    assert (
        b"/opt/neutrino_agent/python/lib/python3.13/site-packages/entry.py" in compiled
    )
    assert str(tmp_path).encode() not in compiled


def test_the_prune_takes_out_what_the_package_did_not_install(tmp_path):
    """The prefix is the package's own territory: bytecode an older version
    wrote, and the directory it kept alive, go together."""
    prefix = tmp_path / "opt" / "neutrino_agent"
    kept = prefix / "python" / "lib" / "kept"
    kept.mkdir(parents=True)
    (kept / "module.py").write_text("")
    (kept / "module.pyc").write_bytes(b"")
    dropped = prefix / "python" / "lib" / "dropped"
    dropped.mkdir()
    (dropped / "gone.pyc").write_bytes(b"")
    listing = tmp_path / "listing"
    listing.write_text(f"{kept}\n{kept}/module.py\n")

    _prune(prefix, listing)

    assert (kept / "module.py").is_file()
    assert not (kept / "module.pyc").exists()
    assert not dropped.exists()
    assert kept.is_dir()


def test_the_prune_never_leaves_the_prefix_through_a_symlink(tmp_path):
    """What a link points at is another root's, and no package's to delete."""
    prefix = tmp_path / "opt" / "neutrino_agent"
    prefix.mkdir(parents=True)
    elsewhere = tmp_path / "var" / "lib" / "neutrino"
    elsewhere.mkdir(parents=True)
    (elsewhere / "vault.json").write_text("decided")
    (prefix / "state").symlink_to(elsewhere)
    listing = tmp_path / "listing"
    listing.write_text(f"{prefix}\n")

    _prune(prefix, listing)

    assert (elsewhere / "vault.json").read_text() == "decided"
    assert not (prefix / "state").exists()


def test_the_prune_is_a_no_op_on_a_fresh_install(tmp_path):
    """Everything under the prefix is the package's own, so nothing goes."""
    prefix = tmp_path / "opt" / "neutrino_agent"
    (prefix / "python" / "bin").mkdir(parents=True)
    (prefix / "python" / "bin" / "python3").write_text("")
    listing = tmp_path / "listing"
    listing.write_text(
        f"{prefix}\n{prefix}/python\n{prefix}/python/bin\n"
        f"{prefix}/python/bin/python3\n"
    )

    _prune(prefix, listing)

    assert (prefix / "python" / "bin" / "python3").is_file()


def test_the_prune_removes_nothing_when_the_file_list_is_empty(tmp_path):
    """A package manager that answers nothing is not a package that installed
    nothing."""
    prefix = tmp_path / "opt" / "neutrino_agent"
    prefix.mkdir(parents=True)
    (prefix / "carried").write_text("")
    listing = tmp_path / "listing"
    listing.write_text("")

    _prune(prefix, listing)

    assert (prefix / "carried").is_file()
