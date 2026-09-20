"""What the staging every hub package shares leaves under the prefix.

Fetching an interpreter and installing the hub into it needs a build
container; what is exercised here is what the staging does to a tree that is
already there — the bytecode it compiles, the path that bytecode names, the
prune the maintainer scripts run afterwards, and which vendored software lands
under the prefix, with the pinned downloads answered locally.
"""

import io
import os
import subprocess
import sys
import tarfile
import zipfile

import pytest

import venv_tree

# A readelf whose answer for a file is the version its own name spells, so a
# tree can be staged with the versions the walk is meant to read.
FAKE_READELF = """#!{python}
import sys
from pathlib import Path

version = Path(sys.argv[-1]).stem.replace("_", ".")
print(f"  0x0020:   Name: GLIBC_{{version}}  Flags: none  Version: 3")
"""


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


# --- What the package carries beside the hub ---------------------------------


def _tarball(name, payload):
    """A release tarball holding one file, the way every vendor ships one.

    Args:
        name: The file inside it.
        payload: What that file holds.

    Returns:
        The archive's bytes.
    """
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        info = tarfile.TarInfo(name)
        info.size = len(payload)
        bundle.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


def _zipball_of(names):
    """An archive carrying several members, as a release does.

    Args:
        names: Member name to contents.

    Returns:
        The archive's bytes.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        for name, payload in names.items():
            bundle.writestr(name, payload)
    return buffer.getvalue()


def _zipball(name, payload):
    """A release zip holding one file, the way xray ships one.

    Args:
        name: The file inside it.
        payload: What that file holds.

    Returns:
        The archive's bytes.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr(name, payload)
    return buffer.getvalue()


def _served(monkeypatch):
    """Every pinned download answered locally, and the URLs that were asked for.

    Args:
        monkeypatch: The fixture.

    Returns:
        The list the fetched URLs land in, keyed in order of the fetches.
    """
    asked = []
    bodies = {
        "xray": _zipball("xray", b"xray"),
        "cliproxyapi": _tarball("cli-proxy-api", b"gateway"),
        "netbird": _tarball("netbird", b"client"),
        "easytier": _zipball_of(
            {
                "easytier-linux-x86_64/easytier-core": b"engine",
                "easytier-linux-x86_64/easytier-web": b"console",
                "easytier-linux-x86_64/easytier-cli": b"cli",
            }
        ),
    }

    def fake_fetch(url, hashes, machine, what):
        asked.append((what, url))
        return bodies.get(what, b"database")

    monkeypatch.setattr(venv_tree, "_fetch", fake_fetch)
    return asked


def test_the_package_carries_the_netbird_client_beside_the_others(
    tmp_path, monkeypatch
):
    """Remote access is in the package rather than fetched from a vendor's
    repository by the machine that wants it."""
    asked = _served(monkeypatch)

    venv_tree.stage_vendored(tmp_path, "amd64")

    binary = tmp_path / "opt" / "neutrino" / "bin" / "netbird"
    assert binary.read_bytes() == b"client"
    assert binary.stat().st_mode & 0o777 == 0o755
    assert (tmp_path / "opt" / "neutrino" / "bin" / "xray").is_file()
    assert (tmp_path / "opt" / "neutrino" / "bin" / "cli-proxy-api").is_file()
    url = dict(asked)["netbird"]
    assert f"netbird_{venv_tree.NETBIRD_VERSION}_linux_amd64.tar.gz" in url


def test_the_arm_package_carries_the_arm_client(tmp_path, monkeypatch):
    """The asset table is keyed by this project's own machine names, which is
    what the vendor's release happens to use too."""
    asked = _served(monkeypatch)

    venv_tree.stage_vendored(tmp_path, "arm64")

    assert "linux_arm64.tar.gz" in dict(asked)["netbird"]


def test_the_package_carries_the_easytier_engine_without_its_console(
    tmp_path, monkeypatch
):
    """The web console beside them manages other people's nodes, which is what
    this overlay exists not to need."""
    asked = _served(monkeypatch)

    venv_tree.stage_vendored(tmp_path, "amd64")

    binaries = tmp_path / "opt" / "neutrino" / "bin"
    assert (binaries / "easytier-core").read_bytes() == b"engine"
    assert (binaries / "easytier-cli").read_bytes() == b"cli"
    assert not (binaries / "easytier-web").exists()
    assert (binaries / "easytier-core").stat().st_mode & 0o777 == 0o755
    assert (
        f"easytier-linux-x86_64-v{venv_tree.EASYTIER_VERSION}.zip"
        in dict(asked)["easytier"]
    )


def test_the_arm_package_carries_the_arm_engine(tmp_path, monkeypatch):
    asked = _served(monkeypatch)

    venv_tree.stage_vendored(tmp_path, "arm64")

    assert "easytier-linux-aarch64" in dict(asked)["easytier"]


def test_the_easytier_pins_are_the_modules_own():
    from neutrino_hub.modules.easytier import constants

    assert venv_tree.EASYTIER_VERSION == constants.EASYTIER_VERSION
    assert venv_tree.EASYTIER_URL == constants.EASYTIER_DOWNLOAD_URL
    assert venv_tree.EASYTIER_SHA256 == constants.EASYTIER_SHA256
    assert venv_tree.EASYTIER_MACHINES == constants.EASYTIER_ASSET_ARCHITECTURES
    assert set(venv_tree.EASYTIER_SHA256) == {"amd64", "arm64"}


def test_the_netbird_pins_are_the_modules_own():
    """A version or a hash written twice is a package that carries something
    other than what the panel reports."""
    from neutrino_hub.modules.netbird import constants

    assert venv_tree.NETBIRD_VERSION == constants.NETBIRD_VERSION
    assert venv_tree.NETBIRD_URL == constants.NETBIRD_DOWNLOAD_URL
    assert venv_tree.NETBIRD_SHA256 == constants.NETBIRD_SHA256
    assert venv_tree.NETBIRD_MACHINES == constants.NETBIRD_ASSET_ARCHITECTURES
    assert set(venv_tree.NETBIRD_SHA256) == {"amd64", "arm64"}


def test_a_download_that_is_not_what_was_pinned_stops_the_build(monkeypatch):
    """What a release serves is checked against the hash the hub states, so a
    replaced asset fails the build rather than shipping."""

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *details):
            return False

        def read(self):
            return b"something else"

    monkeypatch.setattr(venv_tree.urllib.request, "urlopen", lambda *a, **k: Response())

    with pytest.raises(SystemExit):
        venv_tree._fetch(
            "https://example.invalid/netbird.tar.gz",
            venv_tree.NETBIRD_SHA256,
            "amd64",
            "netbird",
        )


def test_a_machine_nothing_is_pinned_for_stops_the_build():
    """A package with no client in it is not a package with remote access
    turned off."""
    with pytest.raises(SystemExit):
        venv_tree._machine_name(venv_tree.NETBIRD_MACHINES, "arm-6", "netbird")


def test_the_carried_interpreter_loses_the_installer_and_the_shared_build(tmp_path):
    """The interpreter is linked statically and nothing installs into the
    tree after the build, so both are weight no package reads."""
    staged_python = tmp_path / "opt" / "neutrino" / "python"
    library = staged_python / "lib"
    site_packages = library / "python3.13" / "site-packages"
    site_packages.mkdir(parents=True)
    (library / "libpython3.13.so.1.0").write_bytes(b"")
    (library / "libpython3.so").write_bytes(b"")
    (library / "python3.13" / "ensurepip").mkdir()
    (site_packages / "pip").mkdir()
    (site_packages / "pip-26.2.1.dist-info").mkdir()
    (site_packages / "neutrino_hub").mkdir()
    (library / "python3.13" / "asyncio").mkdir()
    (staged_python / "bin").mkdir(parents=True)
    (staged_python / "bin" / "pip3").write_text("")
    (staged_python / "bin" / "python3").write_text("")

    venv_tree.trim_interpreter(staged_python)

    assert not (library / "libpython3.13.so.1.0").exists()
    assert not (library / "libpython3.so").exists()
    assert not (library / "python3.13" / "ensurepip").exists()
    assert not (site_packages / "pip").exists()
    assert not (site_packages / "pip-26.2.1.dist-info").exists()
    assert not (staged_python / "bin" / "pip3").exists()
    assert (site_packages / "neutrino_hub").is_dir()
    assert (library / "python3.13" / "asyncio").is_dir()
    assert (staged_python / "bin" / "python3").is_file()


def _elf_tree(root, versions):
    """A package tree of ELF files, each named for the glibc it needs.

    Args:
        root: The staging directory.
        versions: The glibc versions to stage, as strings.

    Returns:
        The staging directory.
    """
    prefix = root / "opt/neutrino"
    prefix.mkdir(parents=True)
    for version in versions:
        name = version.replace(".", "_")
        (prefix / f"{name}.so").write_bytes(b"\x7fELF\x02\x01\x01")
    (prefix / "9_9.txt").write_text("not an ELF\n")
    return root


def _readelf_on_the_path(root, monkeypatch):
    """Put the readelf that answers from a file's name first on the path.

    Args:
        root: The directory to write it into.
        monkeypatch: The fixture that sets the path.
    """
    tools = root / "tools"
    tools.mkdir()
    tool = tools / "readelf"
    tool.write_text(FAKE_READELF.format(python=sys.executable))
    tool.chmod(0o755)
    monkeypatch.setenv("PATH", str(tools), prepend=os.pathsep)


def test_a_binary_needing_a_newer_glibc_than_the_floor_stops_the_build(
    tmp_path, monkeypatch
):
    """The refusal names the file and the version it needs, and nothing else."""
    _readelf_on_the_path(tmp_path, monkeypatch)
    tree = _elf_tree(tmp_path / "tree", ("2.17", "2.34", "2.38"))

    with pytest.raises(SystemExit) as refused:
        venv_tree.require_glibc_floor(tree)

    assert "opt/neutrino/2_38.so" in str(refused.value)
    assert "GLIBC_2.38" in str(refused.value)
    assert "2_34.so" not in str(refused.value)


def test_a_tree_at_the_floor_is_a_package_the_build_lets_through(tmp_path, monkeypatch):
    """Nothing above the floor is nothing to refuse, and no file that is not
    an ELF is read for a version at all."""
    _readelf_on_the_path(tmp_path, monkeypatch)
    tree = _elf_tree(tmp_path / "tree", ("2.2.5", "2.17", "2.34"))

    venv_tree.require_glibc_floor(tree)


def test_each_format_names_its_file_the_way_the_release_carries_it():
    """The file a build writes is the name the hub asks a release for, so
    the three formats spell it from one table."""
    assert (
        venv_tree.asset_name("deb", "0.3.1", "amd64") == "neutrino-hub_0.3.1_amd64.deb"
    )
    assert (
        venv_tree.asset_name("rpm", "0.3.1", "aarch64")
        == "neutrino-hub-0.3.1-1.aarch64.rpm"
    )
    assert (
        venv_tree.asset_name("pkg", "0.3.1", "x86_64")
        == "neutrino-hub-0.3.1-1-x86_64.pkg.tar.zst"
    )


def test_the_stamp_carries_the_version_and_the_file_name_with_the_version_open():
    """What the build writes into the tree is what the running hub reads:
    its version, and the name of its own kind of package for any version."""
    stamp = venv_tree.version_stamp(
        "0.3.1", venv_tree.asset_name("deb", "{version}", "amd64")
    )
    namespace = {}
    exec(stamp, namespace)  # noqa: S102 - the stamp is the module under test
    assert namespace["HUB_VERSION"] == "0.3.1"
    assert namespace["HUB_PACKAGE_ASSET"] == "neutrino-hub_{version}_amd64.deb"
    assert namespace["HUB_PACKAGE_ASSET"].format(version="0.4.0") == (
        venv_tree.asset_name("deb", "0.4.0", "amd64")
    )


def test_the_release_build_reads_the_architecture_table_the_packaging_owns():
    """One table names the machine for every family; the release build
    reads it rather than keeping a copy that could drift."""
    import importlib.util
    from pathlib import Path

    import constants

    script = Path(venv_tree.HUB_ROOT).parent / "packaging" / "build_release.py"
    spec = importlib.util.spec_from_file_location("build_release", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.PACKAGING_ARCHITECTURE_NAMES is constants.PACKAGING_ARCHITECTURE_NAMES
    assert set(constants.PACKAGING_ARCHITECTURE_NAMES) == {"amd64", "arm64"}
    assert set(constants.PACKAGING_ASSET_PATTERNS) == {"deb", "rpm", "pkg"}
