"""Staging the payload every client package carries.

All three packagers ship the same thing — the client compiled, with the
interpreter it runs on and the window's Python side inside the binary, the
page and icon beside it, and the binaries the client drives — and differ only
in how their format wants that described. What they have in common lives
here so it cannot drift three ways.

Compiled rather than carried as an interpreter, for two reasons that hold on
every platform: a tree of bytecode beside an interpreter is what heuristic
scanners flag and a binary is not, and the interpreter is the pinned one on
every machine either way. The interpreter is still fetched, into the build
directory alone: the shells embed a web view through Python bindings that
are compiled against it in the packaging container, and Nuitka compiles the
client against the same one. A platform's C libraries — WebKitGTK,
WebView2 — are the only thing a package still names as a dependency.

The client's own code stays pure standard library. Nothing here is imported
by it; the bindings are imported by the shells alone, at the moment a window
opens.

Not pure: downloads interpreters and wheels, compiles, writes package trees.
"""

import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gui_assets import stage_gui  # noqa: E402

CLIENT_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = CLIENT_ROOT.parent
PACKAGE_NAME = "neutrino-client"

# Where the compiled client and everything beside it live. Its own root
# rather than a directory under the hub's or the agent's: a machine may run
# all three.
INSTALL_PREFIX = Path("/opt/neutrino_client")

# What the compiled client and the root helper are called. The helper's
# directory is the path polkit pins, so its binary sits at that path and its
# libraries beside it rather than behind a link pkexec would resolve.
CLIENT_BINARY_NAME = "nclient"
MOUNT_HELPER_BINARY_NAME = "mount_helper"

# The compiler, at a version that built the client on both platforms. A
# build tool rather than something carried, so pinned by version.
NUITKA_VERSION = "4.2.1"

# The interpreter the Linux client is compiled against, pinned by hash. The
# same build the hub's and the agent's packages carry, and the same minor the
# Windows build pins, so every package runs one Python.
#
# What the client's glibc floor is comes from the packaging container: the
# bindings and the compiled client alike are built against its glibc.
PYTHON_VERSION = "3.13.15"
PYTHON_BUILD = "20260825"
#
# The stripped flavor of the same build. The bindings compiled against it
# link the platform's C libraries over their own ABI, so the symbols the
# flavor drops are read by nothing the compile links.
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

# The Python side of the Linux window, built in the packaging container for
# the interpreter above and compiled into the client. PyGObject links
# libgirepository over the C ABI, so the C libraries the package depends on
# serve the copy built here; the distribution's own python3-gi is never
# involved, because the client never runs the distribution's Python.
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

# The licences of what the client packages carry, by the file name they have
# in the repository's own ``licenses/``.
CARRIED_LICENSES = ("cc_switch.txt", "rustdesk.txt")

# What both maintainer scripts run before the files a resident is running
# from are replaced or taken away. The client's services exist only while it
# runs, so a resident that is asked to quit releases them itself.
STOP_RESIDENTS = r"""# Every resident on this machine, asked to quit; ended when it does not.
stop_residents() {
    if ! command -v pkill >/dev/null 2>&1 || ! command -v pgrep >/dev/null 2>&1; then
        return 0
    fi
    # The whole command line of a resident, however the binary was named,
    # so a shell whose own line mentions it is never matched.
    resident='(^|/)nclient gui( --hidden)?$'
    pkill -TERM -f "$resident" >/dev/null 2>&1 || return 0
    waited=0
    while [ "$waited" -lt 10 ]; do
        pgrep -f "$resident" >/dev/null 2>&1 || return 0
        sleep 1
        waited=$((waited + 1))
    done
    echo "a Neutrino client did not quit in 10 s; ending it" >&2
    pkill -KILL -f "$resident" >/dev/null 2>&1 || true
}
"""

# What both maintainer scripts run once the package's own files are gone.
# Uninstalling the client takes every person's configuration with it, and the
# socket their resident answered on.
WIPE_PERSONAL_STATE = """# Every person's own client directory on this machine, and their socket.
wipe_personal_state() {
    getent passwd | while IFS=: read -r account password uid gid gecos home shell; do
        [ "$uid" -ge 1000 ] 2>/dev/null || continue
        [ -n "$home" ] || continue
        rm -rf "$home/.config/neutrino_client"
    done
    rm -rf /root/.config/neutrino_client
    rm -f /run/user/*/neutrino_client.sock
}
"""


def version() -> str:
    """The version declared in the client's pyproject.

    Returns:
        The version string.

    Raises:
        SystemExit: When the pyproject declares none.
    """
    for line in (
        (CLIENT_ROOT / "pyproject.toml").read_text(encoding="utf-8").splitlines()
    ):
        if line.startswith("version = "):
            return line.split('"')[1]
    raise SystemExit("no version in client/pyproject.toml")


def machine_name(architecture: str) -> str:
    """What the interpreter releases call a machine.

    Args:
        architecture: The architecture, named however a packaging format
            names it.

    Returns:
        The interpreter release's own name for it.

    Raises:
        SystemExit: When it is not a machine the client is published for.
    """
    name = MACHINE_NAMES.get(architecture)
    if name is None:
        raise SystemExit(
            f"the client is published for {', '.join(sorted(set(MACHINE_NAMES)))}, "
            f"not {architecture}"
        )
    return name


def stage_client_tree(parent: Path, package_version: str) -> Path:
    """Copy the client package into a tree and stamp its version into it.

    No packaging format installs a ``.dist-info`` for the client, so
    ``importlib.metadata`` cannot answer for a packaged one; the hub compares
    the stamped value against its own.

    Args:
        parent: The directory the ``neutrino_client`` package belongs in.
        package_version: The version being packaged.

    Returns:
        The copied package directory.
    """
    package_dir = parent / "neutrino_client"
    parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        CLIENT_ROOT / "neutrino_client",
        package_dir,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    (package_dir / "_version.py").write_text(
        '"""Written by the packaging build. Do not edit."""\n\n'
        f'CLIENT_VERSION = "{package_version}"\n',
        encoding="utf-8",
    )
    stage_gui(package_dir)

    # Whatever umask the build ran under does not belong in a package.
    for path in package_dir.rglob("*"):
        path.chmod(0o755 if path.is_dir() else 0o644)
    return package_dir


def stage_linux_interpreter(staged_python: Path, architecture: str) -> None:
    """Unpack the pinned interpreter into the build directory.

    Args:
        staged_python: Where the interpreter belongs.
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
    downloaded = fetch(url, PYTHON_SHA256[name], "the interpreter")

    staged_python.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as workdir:
        archive = Path(workdir) / "python.tar.gz"
        archive.write_bytes(downloaded)
        with tarfile.open(archive) as bundle:
            # `filter` arrived in 3.12 and the build container may be older;
            # this archive is pinned by hash, so its members are known.
            if hasattr(tarfile, "data_filter"):
                bundle.extractall(workdir, filter="data")
            else:
                bundle.extractall(workdir)
        (Path(workdir) / "python").rename(staged_python)


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
    # A wheel's console scripts: the client runs none, and their launcher
    # stubs are what antivirus heuristics flag.
    for scripts in ("bin", "Scripts"):
        shutil.rmtree(target / scripts, ignore_errors=True)


def stage_licenses(tree: Path) -> None:
    """Copy the licences of what the package carries into the tree.

    Args:
        tree: The staging directory standing in for the filesystem root.

    Raises:
        SystemExit: When a licence the package owes is not in the checkout.
    """
    destination = tree / "usr/share/doc" / PACKAGE_NAME / "licenses"
    destination.mkdir(parents=True, exist_ok=True)
    for name in CARRIED_LICENSES:
        source = REPO_ROOT / "licenses" / name
        if not source.is_file():
            raise SystemExit(
                f"the package carries {name} and there is none at {source}"
            )
        shutil.copyfile(source, destination / name)
        (destination / name).chmod(0o644)


def compile_linux(build: Path, architecture: str, package_version: str) -> dict:
    """Compile the client and the root helper for a Linux package.

    The pinned interpreter is unpacked into the build directory, the window's
    bindings are built into it, the compiler is installed beside them, and
    two standalone programs come out: the client with the bindings inside
    it, and the mount helper, which is standard library alone and small.

    Args:
        build: The directory to work under.
        architecture: The architecture, named however the format names it.
        package_version: The version stamped into the client tree.

    Returns:
        ``{"client": dir, "helper": dir, "package": dir}``: the two
        standalone directories, each holding its binary and what it loads,
        and the staged package whose ``data`` the client reads at runtime.

    Raises:
        SystemExit: When a download is not what was pinned, the container
            lacks what the bindings need, or a compile writes no binary.
    """
    python_dir = build / "python"
    stage_linux_interpreter(python_dir, architecture)
    stage_linux_gui_bindings(python_dir)
    python = python_dir / "bin" / "python3"
    run([str(python), "-m", "pip", "install", "--quiet", f"nuitka=={NUITKA_VERSION}"])

    tree = build / "tree"
    package = stage_client_tree(tree, package_version)
    client = _compile_standalone(
        python,
        tree,
        package / "cli" / "entry.py",
        build / "client",
        CLIENT_BINARY_NAME,
        (
            "--include-package=neutrino_client",
            "--include-module=gi",
            "--include-module=cairo",
        ),
    )
    helper = _compile_standalone(
        python,
        tree,
        package / "cli" / "mount_helper.py",
        build / "helper",
        MOUNT_HELPER_BINARY_NAME,
        (),
    )
    return {"client": client, "helper": helper, "package": package}


def _compile_standalone(
    python: Path, tree: Path, entry: Path, build: Path, name: str, includes: tuple
) -> Path:
    """One Nuitka standalone build.

    Args:
        python: The interpreter the program is compiled against.
        tree: The directory the staged package is in, which the compiler
            resolves the package from.
        entry: The module that becomes the program.
        build: Where the compiler works.
        name: What the binary is called.
        includes: What to include beyond what the entry imports itself.

    Returns:
        The standalone directory: the binary and everything it loads.

    Raises:
        SystemExit: When the compiler refuses or writes no binary.
    """
    command = [
        str(python),
        "-m",
        "nuitka",
        "--standalone",
        "--assume-yes-for-downloads",
        *includes,
        f"--output-filename={name}",
        f"--output-dir={build}",
        str(entry),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(tree)},
    )
    if result.returncode != 0:
        raise SystemExit(
            f"compiling {entry.name} failed:\n{(result.stderr or result.stdout).strip()}"
        )
    dist = build / f"{entry.stem}.dist"
    if not (dist / name).is_file():
        raise SystemExit(f"nuitka wrote no {name} under {dist}")
    return dist


def lay_out_compiled(tree: Path, compiled: dict, helper_path: Path) -> None:
    """Put the compiled programs where the package installs them.

    Args:
        tree: The package tree being staged.
        compiled: What :func:`compile_linux` returned.
        helper_path: The absolute path polkit pins the helper at; its
            directory takes the helper's whole standalone directory.
    """
    prefix = tree / str(INSTALL_PREFIX).lstrip("/")
    shutil.copytree(compiled["client"], prefix, dirs_exist_ok=True)
    # Compiled modules keep a __file__ under the prefix, so the package's
    # own data goes beside where that points.
    shutil.copytree(
        compiled["package"] / "data", prefix / compiled["package"].name / "data"
    )
    helper_dir = tree / str(helper_path.parent).lstrip("/")
    shutil.copytree(compiled["helper"], helper_dir, dirs_exist_ok=True)
    launcher = tree / "usr/bin" / CLIENT_BINARY_NAME
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.symlink_to(INSTALL_PREFIX / CLIENT_BINARY_NAME)


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
        downloaded = response.read()
    arrived = hashlib.sha256(downloaded).hexdigest()
    if arrived != digest:
        raise SystemExit(
            f"{what} at {url} hashes to {arrived}, not the pinned {digest}"
        )
    return downloaded


def run(command: list, *, cwd=None) -> None:
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
            f"{' '.join(command[:3])} failed:\n"
            f"{(result.stderr or result.stdout).strip()}"
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
