"""Staging the payload both agent packages carry.

The deb and the rpm ship the same thing — an interpreter with the agent
installed beside it — and differ only in how their format wants that
described. What they have in common lives here so it cannot drift two ways.

The interpreter is carried rather than depended on, the hub package's own
precedent: a machine's own interpreter is not a place this project may
install into. Everything Python the agent runs therefore lives under
:data:`INSTALL_PREFIX`, and the package names no Python at all.

The agent's own code stays pure standard library.

Not pure: downloads interpreters, writes package trees.
"""

import hashlib
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = AGENT_ROOT.parent
PACKAGE_NAME = "neutrino-agent"

# Where the package's own environment lives, and the path its interpreter is
# addressed by. It is staged at this path so nothing inside it has to be
# rewritten afterwards. Its own root rather than a directory under the hub's:
# a machine may run both, and removing the hub deletes /opt/neutrino whole.
INSTALL_PREFIX = Path("/opt/neutrino_agent")
PYTHON_DIR = INSTALL_PREFIX / "python"

# The interpreter the Linux packages carry, pinned by hash. The same build the
# hub's packages carry, so one machine running both carries two copies of one
# thing rather than two different interpreters.
#
# The interpreter itself needs no more than GLIBC 2.17.
PYTHON_VERSION = "3.13.15"
PYTHON_BUILD = "20260825"
#
# The stripped flavor of the same build: the symbols it drops are read by
# nothing the package installs.
PYTHON_URL = (
    "https://github.com/astral-sh/python-build-standalone/releases/download/"
    "{build}/cpython-{version}+{build}-{machine}"
    "-unknown-linux-gnu-install_only_stripped.tar.gz"
)
PYTHON_SHA256 = {
    "x86_64": "8af9a8214c71b2dd698005e39fab87aad02a994330508857da4e6d1ba7e6ddb6",  # scan: allow
    "aarch64": "e5d0df1a6070a8614d808496e5ea28c727480e40ffcce1a94697a067f1690aa8",  # scan: allow
}

# What each packaging format calls the machine, mapped to what the interpreter
# release calls it. 32-bit ARM is not on the list: no interpreter is published
# for it here, and it is not a machine this project ships to.
MACHINE_NAMES = {
    "amd64": "x86_64",
    "x86_64": "x86_64",
    "x64": "x86_64",
    "arm64": "aarch64",
    "aarch64": "aarch64",
}
DEBIAN_ARCHITECTURES = {"x86_64": "amd64", "aarch64": "arm64"}
RPM_ARCHITECTURES = {"x86_64": "x86_64", "aarch64": "aarch64"}


def version() -> str:
    """The version declared in the agent's pyproject.

    Returns:
        The version string.

    Raises:
        SystemExit: When the pyproject declares none.
    """
    for line in (
        (AGENT_ROOT / "pyproject.toml").read_text(encoding="utf-8").splitlines()
    ):
        if line.startswith("version = "):
            return line.split('"')[1]
    raise SystemExit("no version in agent/pyproject.toml")


def machine_name(architecture: str) -> str:
    """What the interpreter releases call a machine.

    Args:
        architecture: The architecture, named however a packaging format
            names it.

    Returns:
        The interpreter release's own name for it.

    Raises:
        SystemExit: When it is not a machine the agent is published for.
    """
    name = MACHINE_NAMES.get(architecture)
    if name is None:
        raise SystemExit(
            f"the agent is published for {', '.join(sorted(set(MACHINE_NAMES)))}, "
            f"not {architecture}"
        )
    return name


def stage_agent_tree(parent: Path, package_version: str) -> Path:
    """Copy the agent package into a tree and stamp its version into it.

    No packaging format installs a ``.dist-info`` for the agent, so
    ``importlib.metadata`` cannot answer for a packaged one; the hub compares
    the stamped value against its own.

    Args:
        parent: The directory the ``neutrino_agent`` package belongs in.
        package_version: The version being packaged.

    Returns:
        The copied package directory.
    """
    package_dir = parent / "neutrino_agent"
    parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        AGENT_ROOT / "neutrino_agent",
        package_dir,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    (package_dir / "_version.py").write_text(
        '"""Written by the packaging build. Do not edit."""\n\n'
        f'AGENT_VERSION = "{package_version}"\n',
        encoding="utf-8",
    )

    # Whatever umask the build ran under does not belong in a package.
    for path in package_dir.rglob("*"):
        path.chmod(0o755 if path.is_dir() else 0o644)
    return package_dir


def stage_linux_interpreter(staged_python: Path, architecture: str) -> None:
    """Unpack the pinned interpreter into a Linux package tree.

    Args:
        staged_python: Where the interpreter belongs in the tree.
        architecture: The architecture, named however the format names it.

    Raises:
        SystemExit: When there is no build for the machine, or what arrived is
            not what was pinned.
    """
    name = machine_name(architecture)
    if name not in PYTHON_SHA256:
        raise SystemExit(
            f"no interpreter build pinned for {architecture}; there is one for: "
            f"{', '.join(sorted(PYTHON_SHA256))}"
        )
    url = PYTHON_URL.format(build=PYTHON_BUILD, version=PYTHON_VERSION, machine=name)
    payload = fetch(url, PYTHON_SHA256[name], "the interpreter")

    staged_python.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as workdir:
        archive = Path(workdir) / "python.tar.gz"
        archive.write_bytes(payload)
        with tarfile.open(archive) as bundle:
            # `filter` arrived in 3.12 and the build container may be older;
            # this archive is pinned by hash, so its members are known.
            if hasattr(tarfile, "data_filter"):
                bundle.extractall(workdir, filter="data")
            else:
                bundle.extractall(workdir)
        (Path(workdir) / "python").rename(staged_python)
    trim_interpreter(staged_python)


def trim_interpreter(staged_python: Path) -> None:
    """Take out of a staged interpreter what no package needs.

    Tkinter draws no window here, and its libraries carry the rpath of the
    machine the interpreter was built on, which rpmbuild rejects outright.

    Args:
        staged_python: The interpreter tree as staged.
    """
    library = staged_python / "lib"
    for pattern in ("libtcl*.so*", "libtk*.so*", "tcl*", "tk*", "Tix*", "itcl*"):
        for path in library.glob(pattern):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
    for pattern in ("tkinter", "turtledemo", "idlelib"):
        for path in library.rglob(pattern):
            shutil.rmtree(path, ignore_errors=True)
    for path in library.rglob("_tkinter*.so"):
        path.unlink(missing_ok=True)
    for name in ("idle3", f"idle{PYTHON_VERSION[:4]}", "2to3"):
        (staged_python / "bin" / name).unlink(missing_ok=True)


def strip_build_paths(staged_python: Path, tree: Path) -> None:
    """Point everything inside the staged interpreter at its installed path.

    pip writes the staging path into the console scripts and the pkg-config
    files it generates. Left alone, every one of them would name a directory
    that exists only on the build machine.

    Args:
        staged_python: The interpreter tree as staged.
        tree: The staging root, which is the prefix to remove.
    """
    staged_prefix = str(tree)
    for path in staged_python.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if staged_prefix not in text:
            continue
        path.write_text(text.replace(staged_prefix, ""), encoding="utf-8")


def site_packages_of(staged_python: Path) -> Path:
    """The staged interpreter's site-packages directory.

    Args:
        staged_python: The interpreter tree as staged.

    Returns:
        The directory third-party packages live in.

    Raises:
        SystemExit: When the tree has none, which means it was not unpacked.
    """
    found = sorted((staged_python / "lib").glob("python*/site-packages"))
    if not found:
        raise SystemExit(f"no site-packages under {staged_python}")
    return found[0]


def fetch(url: str, digest: str, what: str) -> bytes:
    """Download one pinned file and check it against its hash.

    Args:
        url: Where it lives.
        digest: The pinned SHA-256.
        what: The component, for the messages.

    Returns:
        The file's bytes.

    Raises:
        SystemExit: When what arrived is not what was pinned.
    """
    print(f"  fetching {url.rsplit('/', 1)[-1]}")
    with urllib.request.urlopen(url, timeout=600) as response:
        payload = response.read()
    arrived = hashlib.sha256(payload).hexdigest()
    if arrived != digest:
        raise SystemExit(
            f"{what} at {url} hashes to {arrived}, not the pinned {digest}"
        )
    return payload


def write(path: Path, text: str, *, is_executable: bool = False) -> None:
    """Write one file into a tree, creating its parents.

    Args:
        path: Where to write.
        text: What to write.
        is_executable: Whether to mark it 0755.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755 if is_executable else 0o644)
