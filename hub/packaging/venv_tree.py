"""Staging the environment every hub package carries.

All three packagers ship the same thing — an interpreter and the hub installed
into it under /opt/neutrino, a wrapper on the path, and the panel's unit — and
differ only in how their distribution wants that described. What they have in
common lives here so it cannot drift three ways.

The interpreter is carried rather than depended on. A package that names the
distribution's python is a package for one release of one distribution:
`python3.11` is unsatisfiable on Debian 13, `python3.13` on Fedora only works
because RPM will install a second interpreter alongside, and on a rolling
distribution the name stops matching the day python moves. Carrying it leaves
glibc as the only thing a target has to satisfy, and Ubuntu 22.04's 2.35 is
where that starts.

What still binds a package to its build is the architecture: the compiled
wheels in it, and the interpreter's own build, are for one machine.

Not pure: downloads an interpreter, installs into it.
"""

import hashlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
import urllib.request
from pathlib import Path

HUB_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_NAME = "neutrino-hub"


def _runtime(module_name: str, *names):
    """What the hub itself says about the software it drives.

    Read from the modules rather than repeated here, so a version moves in one
    place. The import needs the package on the path, which it is not when this
    runs as a script from a build directory.

    Args:
        module_name: The runtime module to read.
        *names: The constants to take from it.

    Returns:
        One value, or a tuple of them when more than one was asked for.
    """
    if str(HUB_ROOT) not in sys.path:
        sys.path.insert(0, str(HUB_ROOT))
    module = __import__(module_name, fromlist=list(names))
    values = tuple(getattr(module, name) for name in names)
    return values[0] if len(values) == 1 else values


# Where the package's own environment lives, and the path its interpreter is
# addressed by. It is staged at this path so nothing inside it has to be
# rewritten afterwards.
INSTALL_PREFIX = Path("/opt/neutrino")
PYTHON_DIR = INSTALL_PREFIX / "python"

# The interpreter the packages carry, pinned by hash.
#
# The interpreter itself needs no more than GLIBC 2.17, but it is not what
# sets the floor: cryptography and bcrypt ship Rust extensions built against
# GLIBC 2.34, and nothing older loads them. Ubuntu 22.04 carries 2.35, which
# is where support starts and why Debian 11 is not on the list.
PYTHON_VERSION = "3.13.15"
PYTHON_BUILD = "20260825"
PYTHON_URL = (
    "https://github.com/astral-sh/python-build-standalone/releases/download/"
    "{build}/cpython-{version}+{build}-{machine}-unknown-linux-gnu-install_only.tar.gz"
)
PYTHON_SHA256 = {
    "x86_64": "8a70011ae25276a9925f89304cdc086466cd269ee6cfe68a9506694ca5ff4f9c",  # scan: allow
}

# What the hub's own modules call the machine, keyed by what the interpreter
# release calls it. The pins those modules hold are keyed this way.
NORMALIZED_NAMES = {"x86_64": "amd64", "aarch64": "arm64"}

# What each packaging format calls the machine, mapped to what the interpreter
# release calls it.
MACHINE_NAMES = {
    "amd64": "x86_64",
    "x86_64": "x86_64",
    "arm64": "aarch64",
    "aarch64": "aarch64",
}

# What the hub drives and therefore carries. Downloading these at install time
# meant a machine that needed the network to finish installing, an unverified
# script run as root, and no record of which version landed.
#
# Every one is pinned twice: to a release, and to the hash of the file that
# release serves. A `latest` URL would make two builds of one hub version carry
# different software, which is the thing a version number exists to deny.
VENDOR_DIR = INSTALL_PREFIX / "bin"

# Not beside the binary. The databases are replaced while the machine runs, so
# they are state and live with the rest of it; every path that starts xray says
# where they are. The layout and its reasoning are in
# ../../docs/standard/design/files.md.
GEODATA_DIR = Path("/var/lib/neutrino/geodata")

# The pins are the runtime modules' to state: the panel reports them and a
# checkout fetches the same files. Packaging follows rather than leads, so
# there is one place to change when a version moves.
XRAY_VERSION, XRAY_URL, XRAY_MACHINES, XRAY_SHA256 = _runtime(
    "neutrino_hub.modules.xray.constants",
    "XRAY_VERSION",
    "XRAY_DOWNLOAD_URL",
    "XRAY_ASSET_ARCHITECTURES",
    "XRAY_SHA256",
)
CLIPROXYAPI_VERSION = _runtime(
    "neutrino_hub.modules.cliproxyapi.constants", "CLIPROXYAPI_VERSION"
)
CLIPROXYAPI_URL = (
    "https://github.com/router-for-me/CLIProxyAPI/releases/download/"
    "v{version}/CLIProxyAPI_{version}_linux_{machine}.tar.gz"
)
CLIPROXYAPI_MACHINES = {"x86_64": "amd64", "aarch64": "arm64"}
CLIPROXYAPI_X86_64_SHA256 = (
    "43e112686b4a5b7b818531144cd695eeaacdd54c46dced87be6fb3967c22e149"  # scan: allow
)
CLIPROXYAPI_AARCH64_SHA256 = (
    "0019dfc4b32d63c1392aa264aed2253c1e0c2fb09216f8e2cc269bbfb8bb49b5"  # scan: allow
)
CLIPROXYAPI_SHA256 = {
    "x86_64": CLIPROXYAPI_X86_64_SHA256,
    "aarch64": CLIPROXYAPI_AARCH64_SHA256,
}
# The permissive v2fly databases, which are what these packages may carry. A
# running machine fetches the fuller Loyalsoldier set for its own use; that one
# is GPL-3.0, and a package carrying it would be distributing it.
GEODATA = _runtime("neutrino_hub.modules.xray.constants", "XRAY_GEODATA")

# What every package declares it needs, read from the hub's own constants so a
# dependency field and what a checkout installs cannot say different things.
# `systemd` is added here rather than there: the hub drives it through
# `systemctl`, which is not a package a running machine could be missing.
SYSTEM_PACKAGE_FAMILIES = {"debian": "debian", "rhel": "rhel", "arch": "arch"}


def dependencies(family: str) -> list:
    """The packages this family must install for the hub to run.

    Args:
        family: One of :data:`SYSTEM_PACKAGE_FAMILIES`.

    Returns:
        Package names, spelled the way that family spells them.
    """
    packages, resolve = _package_lists()
    return ["systemd"] + resolve(family, packages["runtime"])


def recommendations(family: str) -> list:
    """The packages this family should install but can run without.

    Args:
        family: One of :data:`SYSTEM_PACKAGE_FAMILIES`.

    Returns:
        Package names, spelled the way that family spells them.
    """
    packages, resolve = _package_lists()
    return resolve(family, packages["wifi"])


def _package_lists():
    """The hub's own dependency constants and the name resolution beside them.

    Returns:
        The lists keyed by role, and the function that spells them for a
        family.
    """
    if str(HUB_ROOT) not in sys.path:
        sys.path.insert(0, str(HUB_ROOT))
    from neutrino_hub.system.constants import (
        SYSTEM_RUNTIME_PACKAGES,
        SYSTEM_WIFI_PACKAGES,
    )
    from neutrino_hub.system.package_manager import packages_for

    return {
        "runtime": SYSTEM_RUNTIME_PACKAGES,
        "wifi": SYSTEM_WIFI_PACKAGES,
    }, packages_for


WRAPPER = """#!/bin/sh
# The hub runs from the interpreter the package carries, never the system one.
exec {python}/bin/python3 -m neutrino_hub.cli.entry "$@"
"""


def build_environment(tree: Path, version: str, machine: str) -> None:
    """Stage the interpreter the package carries and install the hub into it.

    Args:
        tree: The staging directory.
        version: The version being packaged, stamped into the tree.
        machine: The architecture, named however the packaging format names
            it; :data:`MACHINE_NAMES` maps it to the interpreter's own name.

    Raises:
        SystemExit: If the interpreter cannot be fetched or the hub cannot be
            installed into it.
    """
    staged_python = tree / str(PYTHON_DIR).lstrip("/")
    _fetch_interpreter(staged_python, machine)

    # No packaging format installs a .dist-info for the hub itself, so the
    # version is stamped where importlib.metadata cannot answer.
    stamp = HUB_ROOT / "neutrino_hub" / "_version.py"
    stamp.write_text(
        '"""Written by the packaging build. Do not edit."""\n\n'
        f'HUB_VERSION = "{version}"\n',
        encoding="utf-8",
    )
    try:
        run(
            [
                str(staged_python / "bin" / "python3"),
                "-m",
                "pip",
                "install",
                "--quiet",
                "--no-compile",
                str(HUB_ROOT),
            ]
        )
    finally:
        stamp.unlink(missing_ok=True)

    strip_build_paths(staged_python, tree)
    stage_vendored(tree, machine)
    stage_licenses(tree)


def stage_vendored(tree: Path, machine: str) -> None:
    """Put the software the hub drives into the tree beside its own.

    Args:
        tree: The staging directory.
        machine: The architecture, named however the packaging format names it.

    Raises:
        SystemExit: If there is no build for the machine, or what arrives is
            not what was pinned.
    """
    name = MACHINE_NAMES.get(machine, machine)
    binaries = tree / str(VENDOR_DIR).lstrip("/")
    binaries.mkdir(parents=True, exist_ok=True)

    normalized = NORMALIZED_NAMES[name]
    payload = _fetch(
        XRAY_URL.format(
            version=XRAY_VERSION,
            asset_arch=_machine_name(XRAY_MACHINES, normalized, "xray"),
        ),
        XRAY_SHA256,
        normalized,
        "xray",
    )
    with tempfile.TemporaryDirectory() as workdir:
        archive = Path(workdir) / "xray.zip"
        archive.write_bytes(payload)
        with zipfile.ZipFile(archive) as bundle:
            # Only the binary: the geodata beside it in the release is a
            # different set from the one these packages may carry.
            bundle.extract("xray", workdir)
        _install_binary(Path(workdir) / "xray", binaries / "xray")

    payload = _fetch(
        CLIPROXYAPI_URL.format(
            version=CLIPROXYAPI_VERSION,
            machine=_machine_name(CLIPROXYAPI_MACHINES, name, "cliproxyapi"),
        ),
        CLIPROXYAPI_SHA256,
        name,
        "cliproxyapi",
    )
    with tempfile.TemporaryDirectory() as workdir:
        archive = Path(workdir) / "cliproxyapi.tar.gz"
        archive.write_bytes(payload)
        with tarfile.open(archive) as bundle:
            bundle.extract("cli-proxy-api", workdir)
        _install_binary(Path(workdir) / "cli-proxy-api", binaries / "cli-proxy-api")

    geodata = tree / str(GEODATA_DIR).lstrip("/")
    geodata.mkdir(parents=True, exist_ok=True)
    for file_name, pin in GEODATA.items():
        payload = _fetch(pin["url"], {name: pin["sha256"]}, name, file_name)
        target = geodata / file_name
        target.write_bytes(payload)
        target.chmod(0o644)


def stage_licenses(tree: Path) -> None:
    """Copy the licences of everything the package carries into it.

    Args:
        tree: The staging directory.
    """
    source = HUB_ROOT.parent / "licenses"
    destination = tree / "usr/share/doc" / PACKAGE_NAME / "licenses"
    destination.mkdir(parents=True, exist_ok=True)
    for path in sorted(source.iterdir()):
        if path.is_file():
            shutil.copyfile(path, destination / path.name)
            (destination / path.name).chmod(0o644)


def _machine_name(names: dict, machine: str, what: str) -> str:
    """What one upstream calls a machine.

    Args:
        names: That upstream's own naming.
        machine: The normalized architecture.
        what: The component, for the error.

    Returns:
        The name to put in the URL.

    Raises:
        SystemExit: When that upstream publishes nothing for the machine.
    """
    if machine not in names:
        raise SystemExit(f"{what} publishes no build for {machine}")
    return names[machine]


def _fetch(url: str, hashes: dict, machine: str, what: str) -> bytes:
    """Download one pinned file and check it against its hash.

    Args:
        url: Where it lives.
        hashes: The pinned hashes, keyed by machine.
        machine: The normalized architecture.
        what: The component, for the messages.

    Returns:
        The file's bytes.

    Raises:
        SystemExit: If nothing is pinned for the machine, or what arrived is
            not it.
    """
    if machine not in hashes:
        raise SystemExit(f"no {what} hash pinned for {machine}")
    print(f"  fetching {what} {url.rsplit('/', 1)[-1]}")
    with urllib.request.urlopen(url, timeout=300) as response:
        payload = response.read()
    digest = hashlib.sha256(payload).hexdigest()
    if digest != hashes[machine]:
        raise SystemExit(
            f"{what} at {url} hashes to {digest}, not the pinned {hashes[machine]}"
        )
    return payload


def _install_binary(source: Path, destination: Path) -> None:
    """Move an extracted binary into the tree, executable.

    Args:
        source: Where it was unpacked.
        destination: Where it belongs.
    """
    shutil.copyfile(source, destination)
    destination.chmod(0o755)


def _fetch_interpreter(staged_python: Path, machine: str) -> None:
    """Download the pinned interpreter and unpack it into the staging tree.

    Args:
        staged_python: Where the interpreter belongs in the tree.
        machine: The architecture, named however the packaging format names it.

    Raises:
        SystemExit: If there is no build for the machine, or what arrived is
            not what was pinned.
    """
    name = MACHINE_NAMES.get(machine)
    if name is None or name not in PYTHON_SHA256:
        raise SystemExit(
            f"no interpreter build pinned for {machine}; there is one for: "
            f"{', '.join(sorted(PYTHON_SHA256))}"
        )
    url = PYTHON_URL.format(build=PYTHON_BUILD, version=PYTHON_VERSION, machine=name)
    print(f"  fetching {url.rsplit('/', 1)[-1]}")
    with urllib.request.urlopen(url, timeout=300) as response:
        payload = response.read()
    digest = hashlib.sha256(payload).hexdigest()
    if digest != PYTHON_SHA256[name]:
        raise SystemExit(
            f"the interpreter at {url} hashes to {digest}, "
            f"not the pinned {PYTHON_SHA256[name]}"
        )

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


def strip_build_paths(staged_python: Path, tree: Path) -> None:
    """Point everything inside the environment at its installed location.

    pip writes the staging path into the console scripts it generates. Left
    alone, every one of them would name a directory that exists only on the
    build machine.

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

    # The package runs one entry point; the interpreter's own idle and
    # documentation tooling is not it.
    for name in ("idle3", f"idle{PYTHON_VERSION[:4]}", "2to3"):
        (staged_python / "bin" / name).unlink(missing_ok=True)

    _drop_tk(staged_python)


def _drop_tk(staged_python: Path) -> None:
    """Take tkinter and the Tcl/Tk libraries out of the staged interpreter.

    Nothing here draws a window: the panel is a web page. They also carry the
    rpath of the machine the interpreter was built on, which rpmbuild rejects
    outright, so removing them settles both at once.

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


def panel_unit(documentation_url: str = "https://github.com/iffiX/neutrino") -> str:
    """The panel's systemd unit with the checkout's assumptions taken out.

    Args:
        documentation_url: What replaces the unit's file:// pointer.

    Returns:
        The unit file to ship.
    """
    services = HUB_ROOT / "neutrino_hub" / "data" / "services"
    unit = (services / "neutrino_hub_web.service").read_text(encoding="utf-8")
    return (
        unit.replace("WorkingDirectory=@REPO_ROOT@/hub\n", "")
        .replace("Environment=PYTHONPATH=@REPO_ROOT@/hub\n", "")
        .replace("@PYTHON@", f"{PYTHON_DIR}/bin/python3")
        .replace(
            "Documentation=file://@REPO_ROOT@/docs/standard/misc/config.md",
            f"Documentation={documentation_url}",
        )
    )


def require_built_frontend() -> None:
    """Refuse to package a hub with no panel in it.

    Raises:
        SystemExit: When the frontend has not been built.
    """
    index = HUB_ROOT / "neutrino_hub" / "data" / "frontend" / "index.html"
    if not index.exists():
        raise SystemExit(
            "the panel has not been built; run `npm run build` in hub/frontend first"
        )


def version() -> str:
    """The version declared in the hub's pyproject."""
    for line in (HUB_ROOT / "pyproject.toml").read_text(encoding="utf-8").splitlines():
        if line.startswith("version = "):
            return line.split('"')[1]
    raise SystemExit("no version in hub/pyproject.toml")


def run(command: list) -> None:
    """Run a build step, failing loudly.

    Args:
        command: The argument vector.

    Raises:
        SystemExit: If the command fails.
    """
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(
            f"{' '.join(command[:3])} failed:\n{(result.stderr or result.stdout).strip()}"
        )


def write(path: Path, text: str, *, is_executable: bool = False) -> None:
    """Write one file into the tree, creating its parents.

    Args:
        path: Where to write.
        text: What to write.
        is_executable: Whether to mark it 0755.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755 if is_executable else 0o644)
