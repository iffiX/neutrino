"""Staging the payload every agent package carries.

All four packagers ship the same thing — an interpreter, the agent installed
beside it, the window's page and icon, and whatever the platform's web view
needs on the Python side — and differ only in how their format wants that
described. What they have in common lives here so it cannot drift four ways.

The interpreter is carried rather than depended on, the hub package's own
precedent. It is also what makes the window possible: the shells embed a web
view through Python bindings, and a machine's own interpreter is not a place
this project may install into. Everything Python the agent runs therefore
lives under :data:`INSTALL_PREFIX`, and a platform's C libraries — WebKitGTK,
WebView2, WKWebView — are the only thing a package still names as a
dependency.

The agent's own code stays pure standard library. Nothing here is imported by
it; the bindings are imported by the shells alone, at the moment a window
opens.

Not pure: downloads interpreters and wheels, writes package trees.
"""

import hashlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gui_assets import stage_gui  # noqa: E402

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
# The interpreter itself needs no more than GLIBC 2.17. What the agent's own
# floor is comes from the bindings built beside it, which are compiled in the
# packaging container against that container's glibc.
PYTHON_VERSION = "3.13.15"
PYTHON_BUILD = "20260825"
PYTHON_URL = (
    "https://github.com/astral-sh/python-build-standalone/releases/download/"
    "{build}/cpython-{version}+{build}-{machine}-unknown-linux-gnu-install_only.tar.gz"
)
PYTHON_SHA256 = {
    "x86_64": "8a70011ae25276a9925f89304cdc086466cd269ee6cfe68a9506694ca5ff4f9c",  # scan: allow
    "aarch64": "b298e34164582305be9629a0da50701358195ce30b639f5ed4bbc50c4768f048",  # scan: allow
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

# The Python side of the Linux window, built in the packaging container for
# the interpreter above and vendored into the package. PyGObject links
# libgirepository over the C ABI, so the C libraries the package depends on
# serve the copy built here; the distribution's own python3-gi is never
# involved, because the agent never runs the distribution's Python.
#
# PyGObject 3.50 is the last release built against girepository-1.0. Every
# release after it needs the 2.0 library, which arrived with GLib 2.80 —
# newer than the container this is built in, and newer than the machines the
# package installs on.
LINUX_GUI_SOURCES = (
    (
        "pycairo",
        "1.27.0",
        "https://files.pythonhosted.org/packages/07/4a/"
        "42b26390181a7517718600fa7d98b951da20be982a50cd4afb3d46c2e603/"
        "pycairo-1.27.0.tar.gz",
        "5cb21e7a00a2afcafea7f14390235be33497a2cce53a98a19389492a60628430",  # scan: allow
    ),
    (
        "PyGObject",
        "3.50.0",
        "https://files.pythonhosted.org/packages/2b/58/"
        "d34e67a79631177e3c08e7d02b5165147f590171f2cae6769502af5f7f7e/"
        "pygobject-3.50.0.tar.gz",
        "4500ad3dbf331773d8dedf7212544c999a76fc96b63a91b3dcac1e5925a1d103",  # scan: allow
    ),
)

# What has to be in the container before those two can be compiled, spelled
# the way pkg-config names them. Checked first, so the build fails on the
# missing package rather than inside a compiler.
LINUX_GUI_BUILD_HEADERS = (
    "gobject-introspection-1.0",
    "cairo",
    "cairo-gobject",
    "libffi",
)


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
    stage_gui(package_dir)

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


def stage_linux_gui_bindings(staged_python: Path) -> None:
    """Build the window's Python bindings for the staged interpreter.

    Compiled here, in the container, against the same C libraries the package
    depends on. The distribution's own bindings are built for the
    distribution's interpreter and cannot be imported by this one.

    Args:
        staged_python: The interpreter tree as staged.

    Raises:
        SystemExit: When the container lacks the development headers, or a
            binding does not build.
    """
    missing = [
        name
        for name in LINUX_GUI_BUILD_HEADERS
        if subprocess.run(
            ["pkg-config", "--exists", name], capture_output=True
        ).returncode
        != 0
    ]
    if missing:
        raise SystemExit(
            "the window's bindings need development headers this container "
            f"does not have: {', '.join(missing)}"
        )
    python = staged_python / "bin" / "python3"
    with tempfile.TemporaryDirectory() as workdir:
        for name, pinned, url, digest in LINUX_GUI_SOURCES:
            source = Path(workdir) / url.rsplit("/", 1)[-1]
            source.write_bytes(fetch(url, digest, f"{name} {pinned}"))
            # What ships is pinned; the meson backend pip fetches to compile
            # it is the build's, and reaches no package.
            run(
                [
                    str(python),
                    "-m",
                    "pip",
                    "install",
                    "--quiet",
                    "--no-deps",
                    str(source),
                ]
            )


def stage_wheels(
    python: Path,
    target: Path,
    wheels: tuple,
    *,
    platform_tag: str = "",
    abi_tag: str = "",
) -> None:
    """Put pinned distributions into a staged interpreter's import path.

    Args:
        python: The interpreter that does the unpacking. It is the build
            machine's own, not the one being packaged: the files are read
            here and written into a tree that runs elsewhere.
        target: The directory the packages belong in.
        wheels: ``(name, version, url, sha256)`` for each file.
        platform_tag: The machine the wheels are for, when it is not this
            one; empty installs for the build machine.
        abi_tag: The interpreter ABI those wheels are for.

    Raises:
        SystemExit: When a file is not what was pinned, or pip refuses it.
    """
    target.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as workdir:
        binaries = []
        sources = []
        for name, pinned, url, digest in wheels:
            path = Path(workdir) / url.rsplit("/", 1)[-1]
            path.write_bytes(fetch(url, digest, f"{name} {pinned}"))
            (binaries if path.suffix == ".whl" else sources).append(str(path))

        # No dependency resolution: every dependency is pinned in the list
        # above, so nothing is reached for beyond the files named. What a
        # source distribution's backend needs to build is the build's, and
        # reaches no package.
        base = [str(python), "-m", "pip", "install", "--quiet", "--no-deps"]
        if binaries:
            tags = []
            if platform_tag:
                tags = ["--platform", platform_tag, "--implementation", "cp"]
                if abi_tag:
                    tags += ["--abi", abi_tag, "--python-version", abi_tag[2:]]
            run(base + tags + ["--target", str(target)] + binaries)
        if sources:
            run(base + ["--target", str(target)] + sources)


def trim_interpreter(staged_python: Path) -> None:
    """Take out of a staged interpreter what no package needs.

    Tkinter draws no window here — the shells embed the platform's own web
    view — and its libraries carry the rpath of the machine the interpreter
    was built on, which rpmbuild rejects outright.

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


def run(command: list, *, cwd: "Path | None" = None) -> None:
    """Run a build step, failing loudly.

    Args:
        command: The argument vector.
        cwd: Directory to run in, when it is not the caller's.

    Raises:
        SystemExit: If the command fails.
    """
    result = subprocess.run(command, capture_output=True, text=True, cwd=cwd)
    if result.returncode != 0:
        raise SystemExit(
            f"{' '.join(command[:3])} failed:\n{(result.stderr or result.stdout).strip()}"
        )


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
