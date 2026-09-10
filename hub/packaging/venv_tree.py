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
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
import urllib.request
from pathlib import Path

HUB_ROOT = Path(__file__).resolve().parent.parent
AGENT_ROOT = HUB_ROOT.parent / "agent"
PACKAGE_NAME = "neutrino-hub"

# The one icon source; the build copies what the wheel ships from here into
# the package tree, which the checkout does not carry.
ICONS_SOURCE_DIR = HUB_ROOT.parent / "images" / "icons"
ICONS_PACKAGE_DIR = HUB_ROOT / "neutrino_hub" / "data" / "resources"


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
#
# The stripped flavor of the same build. What it drops is the debug symbols,
# which nothing on an appliance reads and which weighed more than everything
# else the package carries put together.
PYTHON_URL = (
    "https://github.com/astral-sh/python-build-standalone/releases/download/"
    "{build}/cpython-{version}+{build}-{machine}"
    "-unknown-linux-gnu-install_only_stripped.tar.gz"
)
PYTHON_SHA256 = {
    "x86_64": "8af9a8214c71b2dd698005e39fab87aad02a994330508857da4e6d1ba7e6ddb6",  # scan: allow
    "aarch64": "e5d0df1a6070a8614d808496e5ea28c727480e40ffcce1a94697a067f1690aa8",  # scan: allow
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
# ../../skills/core-code-author/design/files.md.
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
# The release names the 64-bit ARM asset `aarch64`, where xray names its
# `arm64-v8a`; neither follows the other.
CLIPROXYAPI_MACHINES = {"x86_64": "amd64", "aarch64": "aarch64"}
CLIPROXYAPI_X86_64_SHA256 = (
    "43e112686b4a5b7b818531144cd695eeaacdd54c46dced87be6fb3967c22e149"  # scan: allow
)
CLIPROXYAPI_AARCH64_SHA256 = (
    "086ae6513aa522bbd1000f4e83e5b5223df6038bd69f1c6cad56619b84c06947"  # scan: allow
)
CLIPROXYAPI_SHA256 = {
    "x86_64": CLIPROXYAPI_X86_64_SHA256,
    "aarch64": CLIPROXYAPI_AARCH64_SHA256,
}
# The permissive v2fly databases, which are what these packages may carry. A
# running machine fetches the fuller Loyalsoldier set for its own use; that one
# is GPL-3.0, and a package carrying it would be distributing it.
GEODATA = _runtime("neutrino_hub.modules.xray.constants", "XRAY_GEODATA")

# Where the agent packages the hub hands out live once installed, and how they
# are addressed there. The runtime module states both: packaging seeds the
# directory the panel then reads, and a key spelled two ways would be a cache
# that never hits.
AGENT_PACKAGE_CACHE_DIR, AGENT_PACKAGE_MANIFEST_NAME = _runtime(
    "neutrino_hub.modules.devices.constants",
    "AGENT_PACKAGE_CACHE_DIR",
    "AGENT_PACKAGE_MANIFEST_NAME",
)
_AGENT_PACKAGE_MODULE = "neutrino_hub.modules.devices.agent_package"
AGENT_PACKAGE_NAME = _runtime(_AGENT_PACKAGE_MODULE, "package_name")
AGENT_PLATFORM_KEY = _runtime(_AGENT_PACKAGE_MODULE, "platform_key")
AGENT_PACKAGE_FAMILY = _runtime(_AGENT_PACKAGE_MODULE, "package_family")
AGENT_PACKAGE_MACHINE = _runtime(_AGENT_PACKAGE_MODULE, "package_architecture")

# Where a release publishes the agent packages this build seeds, so an
# installed hub can serve a platform this build did not make. A build that is
# not a release names none, and the manifest then carries the seeded entries
# alone.
AGENT_PACKAGE_URL_BASE_ENV = "NEUTRINO_AGENT_PACKAGE_URL_BASE"

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


# What the bytecode pass leaves alone: the standard library's own test suites
# hold files that are deliberately unparseable, and nothing on a box imports
# them.
BYTECODE_EXCLUDED = r"/(test|tests|idle_test)/"

# What every maintainer script runs over the prefix, given the paths its
# package manager tracks. Configuration, state and logs live under roots it
# never names.
PRUNE_UNTRACKED = """# Everything under the package's own prefix that the package did not install,
# and the directories that leaves empty. The tracked paths are read on
# standard input, and an empty list removes nothing.
prune_untracked() {
    prefix="$1"
    [ -d "$prefix" ] || return 0
    tracked="$(mktemp)" || return 0
    LC_ALL=C sort >"$tracked"
    if [ ! -s "$tracked" ]; then
        rm -f "$tracked"
        return 0
    fi
    found="$(mktemp)" || { rm -f "$tracked"; return 0; }
    find "$prefix" ! -type d -print | LC_ALL=C sort >"$found"
    LC_ALL=C comm -23 "$found" "$tracked" | while IFS= read -r path; do
        case "$path" in "$prefix"/*) rm -f "$path" ;; esac
    done
    find "$prefix" -type d -print | LC_ALL=C sort >"$found"
    LC_ALL=C comm -23 "$found" "$tracked" | LC_ALL=C sort -r |
        while IFS= read -r path; do
            case "$path" in "$prefix"/*) rmdir "$path" 2>/dev/null || true ;; esac
        done
    rm -f "$tracked" "$found"
}
"""

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
    stage_icons()
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

    compile_bytecode(staged_python, PYTHON_DIR)
    strip_build_paths(staged_python, tree)
    stage_agent_cache(tree, staged_python, machine)
    stage_vendored(tree, machine)
    stage_licenses(tree)


def stage_icons() -> None:
    """Copy the shipped icons from ``images/icons`` into the package tree.

    The copies land in ``neutrino_hub/data/resources``, which the wheel's
    package data names and the checkout gitignores.

    Raises:
        SystemExit: When ``images/icons`` is not beside the hub tree.
    """
    sources = sorted(ICONS_SOURCE_DIR.glob("*.png"))
    if not sources:
        raise SystemExit(f"no icons to ship under {ICONS_SOURCE_DIR}")
    ICONS_PACKAGE_DIR.mkdir(parents=True, exist_ok=True)
    for source in sources:
        shutil.copyfile(source, ICONS_PACKAGE_DIR / source.name)


def stage_agent_cache(tree: Path, staged_python: Path, machine: str) -> None:
    """Seed the agent package cache and stamp the manifest that reads it.

    Built from the same checkout, so the hub and the agent it hands out
    cannot drift. The files land where an installed hub looks for them, so a
    Linux enrollment and a Linux self-update need no network at all.

    The agent carries an interpreter and compiled bindings of its own, so what
    is seeded is for this container's machine and no other. A hub serving
    devices of a second architecture fetches those from the release the
    manifest names, or is given them by hand under
    ``config/devices/packages``.

    The build container carries ``dpkg-dev``, ``rpm`` and the headers the
    agent's bindings compile against.

    Args:
        tree: The staging directory.
        staged_python: The interpreter tree the hub was installed into.
        machine: The architecture, named however the packaging format names
            it.

    Raises:
        SystemExit: When a build writes a file whose platform cannot be read
            from its name, which would seed the cache under a key nothing
            asks for.
    """
    cache = tree / str(AGENT_PACKAGE_CACHE_DIR).lstrip("/")
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as workdir:
        built = Path(workdir)
        for script in ("build_deb.py", "build_rpm.py"):
            run(
                [
                    str(staged_python / "bin" / "python3"),
                    str(AGENT_ROOT / "packaging" / script),
                    "--output-dir",
                    str(built),
                    "--architecture",
                    machine,
                ],
                cwd=AGENT_ROOT,
            )
        manifest = agent_cache_entries(sorted(built.iterdir()), _agent_url_base())
        for path in sorted(built.iterdir()):
            key = AGENT_PLATFORM_KEY(*_agent_platform(path.name))
            target = cache / AGENT_PACKAGE_NAME(manifest[key])
            shutil.copyfile(path, target)
            target.chmod(0o644)

    site_packages = next((staged_python / "lib").glob("python*/site-packages"))
    write(
        site_packages / "neutrino_hub" / "data" / AGENT_PACKAGE_MANIFEST_NAME,
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
    )


def agent_cache_entries(paths: list, url_base: str) -> dict:
    """What the manifest says about the packages a build seeded.

    Args:
        paths: The files the agent's builds wrote.
        url_base: Where a release publishes them, empty for a build that
            publishes nothing.

    Returns:
        Platform key to ``{name, url, sha256, size}``. The name is the file's
        own, which is what a release publishes it as.

    Raises:
        SystemExit: When a file's name says no family or no machine.
    """
    entries = {}
    for path in paths:
        family, architecture = _agent_platform(path.name)
        payload = path.read_bytes()
        entries[AGENT_PLATFORM_KEY(family, architecture)] = {
            "name": path.name,
            "url": f"{url_base.rstrip('/')}/{path.name}" if url_base else "",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size": len(payload),
        }
    return entries


def _agent_platform(name: str) -> tuple:
    """The family and machine one agent package file is for.

    Args:
        name: The file name, as either format writes it.

    Returns:
        ``(family, architecture)``.

    Raises:
        SystemExit: When the name says either of them not at all.
    """
    family = AGENT_PACKAGE_FAMILY(name)
    architecture = AGENT_PACKAGE_MACHINE(name)
    if not family or not architecture:
        raise SystemExit(f"{name} names no family and machine to serve it for")
    return family, architecture


def _agent_url_base() -> str:
    """Where a release publishes the agent packages, empty for any other build."""
    return os.environ.get(AGENT_PACKAGE_URL_BASE_ENV, "").strip()


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


def compile_bytecode(staged_python: Path, install_python: Path) -> None:
    """Compile the carried interpreter's tree so the package ships its bytecode.

    A ``.pyc`` the interpreter writes after the install is in no package's
    file list, and a directory a later version drops cannot be removed over
    one. Compiled here, every one of them is a file the package manager
    installs and replaces.

    Args:
        staged_python: The interpreter tree as staged.
        install_python: Where that tree is installed, which is the path
            recorded in the bytecode.

    Raises:
        SystemExit: When the interpreter cannot compile its own tree.
    """
    run(
        [
            str(staged_python / "bin" / "python3"),
            "-m",
            "compileall",
            "-q",
            "-f",
            # The package manager sets its own mtimes, and a timestamp
            # validated .pyc would be rejected and written again at runtime.
            "--invalidation-mode",
            "unchecked-hash",
            "-x",
            BYTECODE_EXCLUDED,
            "-d",
            str(install_python / "lib"),
            str(staged_python / "lib"),
        ]
    )


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
            "Documentation=file://@REPO_ROOT@/skills/core-code-author/misc/config.md",
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
    """Write one file into the tree, creating its parents.

    Args:
        path: Where to write.
        text: What to write.
        is_executable: Whether to mark it 0755.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755 if is_executable else 0o644)
