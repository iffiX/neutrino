"""What the staging every hub package shares leaves under the prefix.

Fetching an interpreter and installing the hub into it needs a build
container; what is exercised here is what the staging does to a tree that is
already there — the bytecode it compiles, the path that bytecode names, and
the prune the maintainer scripts run afterwards.
"""

import subprocess
import sys

import venv_tree


def _carried_interpreter(root):
    """A staged interpreter whose python3 is the one running the tests.

    Args:
        root: The staging directory.

    Returns:
        The staged interpreter tree.
    """
    staged_python = root / "opt" / "neutrino" / "python"
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
        + venv_tree.PRUNE_UNTRACKED
        + f'prune_untracked "{prefix}" <"{listing}"\n'
    )
    result = subprocess.run(["sh", "-c", script], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr


def test_the_staged_tree_carries_bytecode_for_every_module(tmp_path):
    """A .pyc written after the install is in no package's file list, and a
    directory a later version drops cannot be removed over one."""
    staged_python = _carried_interpreter(tmp_path)
    package = staged_python / "lib" / "python3.13" / "site-packages" / "neutrino_hub"
    (package / "modules").mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "entry.py").write_text("VALUE = 1\n")
    (package / "modules" / "xray.py").write_text("VALUE = 2\n")

    venv_tree.compile_bytecode(staged_python, venv_tree.PYTHON_DIR)

    for source in sorted(package.rglob("*.py")):
        assert list((source.parent / "__pycache__").glob(f"{source.stem}.*.pyc"))


def test_the_bytecode_records_the_path_the_package_installs_it_at(tmp_path):
    """The build machine's staging path is nowhere a traceback can name it."""
    staged_python = _carried_interpreter(tmp_path)
    site_packages = staged_python / "lib" / "python3.13" / "site-packages"
    site_packages.mkdir(parents=True)
    (site_packages / "entry.py").write_text("VALUE = 1\n")

    venv_tree.compile_bytecode(staged_python, venv_tree.PYTHON_DIR)

    compiled = next((site_packages / "__pycache__").glob("entry.*.pyc")).read_bytes()
    assert b"/opt/neutrino/python/lib/python3.13/site-packages/entry.py" in compiled
    assert str(tmp_path).encode() not in compiled


def test_the_prune_takes_out_what_the_package_did_not_install(tmp_path):
    """The prefix is the package's own territory: bytecode an older version
    wrote, and the directory it kept alive, go together."""
    prefix = tmp_path / "opt" / "neutrino"
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
    prefix = tmp_path / "opt" / "neutrino"
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
    prefix = tmp_path / "opt" / "neutrino"
    (prefix / "bin").mkdir(parents=True)
    (prefix / "bin" / "xray").write_text("")
    listing = tmp_path / "listing"
    listing.write_text(f"{prefix}\n{prefix}/bin\n{prefix}/bin/xray\n")

    _prune(prefix, listing)

    assert (prefix / "bin" / "xray").is_file()


def test_the_prune_removes_nothing_when_the_file_list_is_empty(tmp_path):
    """A package manager that answers nothing is not a package that installed
    nothing."""
    prefix = tmp_path / "opt" / "neutrino"
    prefix.mkdir(parents=True)
    (prefix / "carried").write_text("")
    listing = tmp_path / "listing"
    listing.write_text("")

    _prune(prefix, listing)

    assert (prefix / "carried").is_file()
