"""Staging the environment every hub package carries.

All three packagers ship the same thing — an interpreter and the hub installed
into it under /opt/neutrino/hub, a wrapper on the path, and the panel's unit —
and differ only in how their distribution wants that described. What they have in
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
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

from constants import HUB_ICON_NAME, PACKAGING_GLIBC_FLOOR

# The repository's packaging directory, for the names every package shares.
SHARED_PACKAGING_DIR = Path(__file__).resolve().parents[2] / "packaging"
if str(SHARED_PACKAGING_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_PACKAGING_DIR))
from shared import edition_build  # noqa: E402
from shared import hub_assets  # noqa: E402
from shared.constants import PACKAGING_ASSET_PATTERNS  # noqa: E402

HUB_ROOT = Path(__file__).resolve().parent.parent
AGENT_ROOT = HUB_ROOT.parent / "agent"
PACKAGE_NAME = "neutrino-hub"
# The system the carried programs are built for, as their pin tables key it.
HUB_ASSETS_SYSTEM = "linux"

# The one icon source; the build copies what the wheel ships from here into
# the package tree, which the checkout does not carry.
ICONS_SOURCE_DIR = HUB_ROOT.parent / "images" / "icons"
ICONS_PACKAGE_DIR = HUB_ROOT / "neutrino_hub" / "data" / "resources"

# A glibc version as readelf's version sections name it.
GLIBC_VERSION = re.compile(r"GLIBC_(\d+)\.(\d+)")


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
INSTALL_PREFIX = Path("/opt/neutrino/hub")
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
# script run as root, and no record of which version landed. Every one is
# pinned to a release and to the hash of the file that release serves, by the
# runtime module that drives it; packaging/shared/hub_assets.py reads them.
VENDOR_DIR = INSTALL_PREFIX / "bin"

# Not beside the binary. The databases are replaced while the machine runs, so
# they are state and live with the rest of it; every path that starts xray says
# where they are. The layout and its reasoning are in
# ../../skills/core-code-author/design/files.md.
GEODATA_DIR = Path("/var/lib/neutrino/hub/geodata")

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
# The agent package family each hub package carries one file of, by the
# hub package's own kind. The Arch package carries none, because no agent
# package is published for Arch.
AGENT_FAMILY_OF_HUB_KIND = {"deb": "deb", "rpm": "rpm", "pkg": ""}
# What builds the agent's own package of each family, when no directory of
# packages already built is given.
AGENT_BUILD_SCRIPTS = {"deb": "build_deb.py", "rpm": "build_rpm.py"}

# Where a release publishes the agent packages, so an installed hub can fetch
# a platform its package does not carry. A build that is not a release names
# none, and the manifest then carries the seeded entry alone.
AGENT_PACKAGE_URL_BASE_ENV = "NEUTRINO_AGENT_PACKAGE_URL_BASE"

# A directory of agent packages already built, every family and machine the
# release makes. The build reads every one into the manifest and seeds the
# one of its own platform; without it the hub's build makes that one itself.
AGENT_PACKAGES_DIR_ENV = "NEUTRINO_AGENT_PACKAGES_DIR"

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
        Package names, spelled the way that family spells them, and a package
        the family spells two ways named by the preferred one.
    """
    packages, package_manager = _package_lists()
    return ["systemd"] + package_manager.packages_for(family, packages["runtime"])


def dependency_choices(family: str) -> list:
    """The same packages, each with every name this family has for it.

    A format whose dependency field spells alternatives declares all of them,
    so one package installs on the releases that carry either name.

    Args:
        family: One of :data:`SYSTEM_PACKAGE_FAMILIES`.

    Returns:
        One tuple of names per package, the preferred name first.
    """
    packages, package_manager = _package_lists()
    return [("systemd",)] + package_manager.package_choices(family, packages["runtime"])


def recommendations(family: str) -> list:
    """The packages this family should install but can run without.

    Args:
        family: One of :data:`SYSTEM_PACKAGE_FAMILIES`.

    Returns:
        Package names, spelled the way that family spells them.
    """
    packages, package_manager = _package_lists()
    return package_manager.packages_for(family, packages["wifi"])


def _package_lists():
    """The hub's own dependency constants and the name resolution beside them.

    Returns:
        The lists keyed by role, and the module that spells them for a family.
    """
    if str(HUB_ROOT) not in sys.path:
        sys.path.insert(0, str(HUB_ROOT))
    from neutrino_hub.system import package_manager
    from neutrino_hub.system.constants import (
        SYSTEM_RUNTIME_PACKAGES,
        SYSTEM_WIFI_PACKAGES,
    )

    return {
        "runtime": SYSTEM_RUNTIME_PACKAGES,
        "wifi": SYSTEM_WIFI_PACKAGES,
    }, package_manager


# What the interpreter carries to install with, dropped once the hub is in the
# tree: an installed package is replaced whole, never installed into.
INTERPRETER_INSTALLER = ("pip", "ensurepip", "setuptools", "pkg_resources")

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

# The application entry every Linux package installs, and the icons it is
# drawn with, by edge.
DESKTOP_ENTRY_NAME = "neutrino-hub"
DESKTOP_ENTRY = """[Desktop Entry]
Type=Application
Name=Neutrino Hub
Comment=Open the hub's panel
Exec=nhub open
Icon=neutrino-hub
Terminal=false
Categories=Network;
"""
DESKTOP_ICON_EDGES = (256, 48)

# What a first install runs once the files are in place: the panel's unit
# starts, serving the setup wizard, and its address is printed.
FIRST_INSTALL = """systemctl enable --now neutrino_hub_web.service >/dev/null 2>&1 || true
address="$(nhub open --print 2>/dev/null)" || address=""
echo ""
if [ -n "$address" ]; then
    echo "  Neutrino Hub installed. Set it up in a browser at:"
    echo ""
    echo "      $address"
else
    echo "  Neutrino Hub installed. Set it up with:"
    echo ""
    echo "      sudo nhub open"
fi
echo ""
echo "  Or in a terminal: sudo nhub setup"
echo ""
"""


def asset_name(kind: str, version: str, machine: str) -> str:
    """The file a build of this kind writes, which is what a release carries.

    Args:
        kind: ``deb``, ``rpm`` or ``pkg``.
        version: The version being packaged, or ``{version}`` to leave it
            open for the hub to fill when it asks a release for a later one.
        machine: The architecture as that format spells it.

    Returns:
        The file name.
    """
    return PACKAGING_ASSET_PATTERNS[kind].format(
        name=PACKAGE_NAME, version=version, architecture=machine
    )


def version_stamp(version: str, asset: str) -> str:
    """The module the build writes into the tree, for the hub to read at run.

    No packaging format installs a .dist-info for the hub itself, so the
    version is stamped where importlib.metadata cannot answer, and the
    package's own release file name beside it, with the version left open,
    the edition the build was asked for, and the versions of the carried
    programs the build pins outside the hub.

    Args:
        version: The version being packaged.
        asset: The file name this build writes, with ``{version}`` in place
            of the version.

    Returns:
        The text of ``neutrino_hub/_version.py``.

    Raises:
        SystemExit: When ``NEUTRINO_EDITION`` names no edition.
    """
    return (
        '"""Written by the packaging build. Do not edit."""\n\n'
        f'HUB_VERSION = "{version}"\n'
        f'HUB_PACKAGE_ASSET = "{asset}"\n'
        f'EDITION = "{edition_build.build_edition()}"\n'
        f"HUB_CARRIED_VERSIONS = {hub_assets.stamped_versions()!r}\n"
    )


def build_environment(
    tree: Path, version: str, machine: str, *, kind: str, asset: str
) -> None:
    """Stage the interpreter the package carries and install the hub into it.

    Args:
        tree: The staging directory.
        version: The version being packaged, stamped into the tree.
        machine: The architecture, named however the packaging format names
            it; :data:`MACHINE_NAMES` maps it to the interpreter's own name.
        kind: ``deb``, ``rpm`` or ``pkg``, the package being built, which
            names the agent package it carries.
        asset: The file name this build writes, with ``{version}`` left
            open, stamped beside the version.

    Raises:
        SystemExit: If the interpreter cannot be fetched or the hub cannot be
            installed into it.
    """
    staged_python = tree / str(PYTHON_DIR).lstrip("/")
    _fetch_interpreter(staged_python, machine)

    stamp = HUB_ROOT / "neutrino_hub" / "_version.py"
    stamp.write_text(version_stamp(version, asset), encoding="utf-8")
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
                # A dependency with no wheel for this machine would be
                # compiled here, against the container's glibc rather than
                # the floor the package declares.
                "--only-binary=:all:",
                str(HUB_ROOT),
            ]
        )
    finally:
        stamp.unlink(missing_ok=True)

    trim_interpreter(staged_python)
    compile_bytecode(staged_python, PYTHON_DIR)
    strip_build_paths(staged_python, tree)
    stage_agent_cache(
        tree, staged_python, machine, family=AGENT_FAMILY_OF_HUB_KIND[kind]
    )
    stage_vendored(tree, machine)
    stage_licenses(tree)
    require_glibc_floor(tree)


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


def stage_agent_cache(
    tree: Path, staged_python: Path, machine: str, *, family: str
) -> None:
    """Seed the hub's own agent package and stamp the manifest that reads it.

    Built from the same checkout, so the hub and the agent it hands out
    cannot drift. The one file lands where an installed hub looks for it, so
    the hub's own agent and every device of its platform need no network.

    A release hands this build every agent package it made, through
    :data:`AGENT_PACKAGES_DIR_ENV`: each enters the manifest with its hash and
    its URL, and the one of this package's family and machine enters the
    cache. A build given none makes that one agent package itself.

    Args:
        tree: The staging directory.
        staged_python: The interpreter tree the hub was installed into.
        machine: The architecture, named however the packaging format names
            it.
        family: ``deb`` or ``rpm``, the agent package this hub package
            carries; empty carries none.

    Raises:
        SystemExit: When a file's platform cannot be read from its name,
            the directory given holds no agent package at all, or none of
            this package's family and machine.
    """
    cache = tree / str(AGENT_PACKAGE_CACHE_DIR).lstrip("/")
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as workdir:
        built = Path(workdir)
        prebuilt = _agent_packages_dir()
        if prebuilt is not None:
            found = sorted(
                path
                for path in prebuilt.iterdir()
                if path.name.startswith("neutrino-agent")
            )
            if not found:
                raise SystemExit(f"no agent package under {prebuilt}")
            for path in found:
                shutil.copyfile(path, built / path.name)
        elif family:
            run(
                [
                    str(staged_python / "bin" / "python3"),
                    str(AGENT_ROOT / "packaging" / AGENT_BUILD_SCRIPTS[family]),
                    "--output-dir",
                    str(built),
                    "--architecture",
                    machine,
                ],
                cwd=AGENT_ROOT,
            )
        seeded = AGENT_PLATFORM_KEY(family, AGENT_PACKAGE_MACHINE(machine))
        manifest = agent_manifest(
            sorted(built.iterdir()), _agent_url_base(), seeded=seeded
        )
        if seeded and seeded not in manifest:
            raise SystemExit(
                f"no agent {family} for {machine} among the agent packages; "
                "build it first and pass its directory"
            )
        if seeded:
            name = AGENT_PACKAGE_NAME(manifest[seeded])
            target = cache / name
            shutil.copyfile(built / name, target)
            target.chmod(0o644)

    site_packages = next((staged_python / "lib").glob("python*/site-packages"))
    write(
        site_packages / "neutrino_hub" / "data" / AGENT_PACKAGE_MANIFEST_NAME,
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
    )


def agent_manifest(paths: list, url_base: str, *, seeded: str) -> dict:
    """What a hub package's manifest names, beside the one file it carries.

    Args:
        paths: Every agent package the build was given or made.
        url_base: Where the release publishes them, empty for a build that
            publishes nothing.
        seeded: The platform key of the file the package carries, empty for
            none.

    Returns:
        Platform key to ``{name, url, sha256, size}``: every platform for a
        release, and the seeded one alone for a build with no URL base, so a
        platform nothing published is refused by name.

    Raises:
        SystemExit: When a file's name says no family or no machine.
    """
    entries = agent_cache_entries(paths, url_base)
    if url_base:
        return entries
    return {key: entry for key, entry in entries.items() if key == seeded}


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


def _agent_packages_dir() -> Path | None:
    """The agent packages a release handed this build, None to build its own."""
    given = os.environ.get(AGENT_PACKAGES_DIR_ENV, "").strip()
    return Path(given) if given else None


def stage_vendored(tree: Path, machine: str) -> None:
    """Put the software the hub drives into the tree beside its own.

    Args:
        tree: The staging directory.
        machine: The architecture, named however the packaging format names it.

    Raises:
        SystemExit: If there is no build for the machine, or what arrives is
            not what was pinned.
    """
    normalized = NORMALIZED_NAMES.get(MACHINE_NAMES.get(machine, machine))
    if normalized is None:
        raise SystemExit(f"the hub carries no programs for {machine}")
    hub_assets.stage_programs(
        tree / str(VENDOR_DIR).lstrip("/"), HUB_ASSETS_SYSTEM, normalized
    )
    hub_assets.stage_geodata(tree / str(GEODATA_DIR).lstrip("/"))


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


def require_glibc_floor(tree: Path) -> None:
    """Refuse a package tree that needs a newer glibc than the floor.

    Args:
        tree: The staging directory standing in for the filesystem root.

    Raises:
        SystemExit: When a file in the tree names a glibc version above
            :data:`PACKAGING_GLIBC_FLOOR`.
    """
    floor = tuple(int(part) for part in PACKAGING_GLIBC_FLOOR.split("."))
    above = []
    for path in sorted(tree.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        needed = _glibc_needed(path)
        if needed > floor:
            version = ".".join(str(part) for part in needed)
            above.append(f"  {path.relative_to(tree)} needs GLIBC_{version}")
    if above:
        listed = "\n".join(above)
        raise SystemExit(
            f"the package installs on glibc {PACKAGING_GLIBC_FLOOR} and up, "
            f"and these need newer:\n{listed}"
        )


def _glibc_needed(path: Path) -> tuple:
    """The highest glibc version one file names.

    Args:
        path: The file to read.

    Returns:
        The version as ``(major, minor)``, empty when the file is not an ELF
        or names no glibc version at all.

    Raises:
        SystemExit: When readelf cannot read an ELF file.
    """
    with path.open("rb") as handle:
        if handle.read(4) != b"\x7fELF":
            return ()
    result = subprocess.run(
        ["readelf", "--wide", "-V", str(path)], capture_output=True, text=True
    )
    if result.returncode != 0:
        raise SystemExit(f"readelf could not read {path}: {result.stderr.strip()}")
    found = [
        (int(major), int(minor))
        for major, minor in GLIBC_VERSION.findall(result.stdout)
    ]
    return max(found, default=())


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


def trim_interpreter(staged_python: Path) -> None:
    """Take out of the staged interpreter what the installed package never runs.

    It runs once the hub is installed into the tree, since installing is what
    the interpreter's own installer is for and nothing installs into the tree
    again: a package manager replaces the whole of it.

    Args:
        staged_python: The interpreter tree as staged.
    """
    library = staged_python / "lib"

    # The interpreter is linked statically, which `readelf -d bin/python3`
    # states by naming no libpython. The shared build beside it is 30 MB that
    # only an embedder loads, and nothing in the package embeds one.
    for path in library.glob("libpython*.so*"):
        path.unlink(missing_ok=True)

    for parent in (*library.glob("python*"), *library.glob("python*/site-packages")):
        for path in parent.iterdir():
            # A dist-info directory carries the version in its name.
            if path.name.split("-")[0] not in INTERPRETER_INSTALLER:
                continue
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)

    # The package runs one entry point; the interpreter's own installer, idle
    # and documentation tooling is not it.
    for name in ("idle3", f"idle{PYTHON_VERSION[:4]}", "2to3"):
        (staged_python / "bin" / name).unlink(missing_ok=True)
    for path in (staged_python / "bin").glob("pip*"):
        path.unlink(missing_ok=True)

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


def stop_hub_lines(*, indent: str = "    ") -> str:
    """The removal scripts' lines that hand the network back and stop the hub.

    The units are the code's own list, the panel's first, so a unit added
    there is stopped by every package's removal without another edit.

    Args:
        indent: What each line starts with.

    Returns:
        Shell lines, each ending in a newline.
    """
    from neutrino_hub.system.constants import SYSTEM_MANAGED_UNITS
    from neutrino_hub.system.units import SYSTEM_UNIT_TEMPLATES

    units = [unit.removesuffix(".service") for unit in SYSTEM_MANAGED_UNITS.values()]
    panel = "neutrino_hub_web"
    units = [panel, *(unit for unit in units if unit != panel)]
    templates = [
        name.removesuffix("@.service")
        for name in SYSTEM_UNIT_TEMPLATES
        if name.endswith("@.service")
    ]
    lines = [
        "# The network goes back to the machine while the hub's code is still",
        "# here: the firewall, the engines it started, and the resolver.",
        "nhub reset network >/dev/null 2>&1 || true",
        f"for unit in {' '.join(units)}; do",
        '    systemctl stop "${unit}.service" >/dev/null 2>&1 || true',
        '    systemctl disable "${unit}.service" >/dev/null 2>&1 || true',
        "done",
        "# One instance per radio and per uplink, named at runtime, so each",
        "# family is stopped by its pattern.",
        f"for template in {' '.join(templates)}; do",
        '    systemctl stop "${template}@*.service" >/dev/null 2>&1 || true',
        "done",
        "# The router unit stops without tearing anything down, so removing the",
        "# package is where the firewall and the policy route go.",
        "nft delete table inet neutrino >/dev/null 2>&1 || true",
        "ip rule del fwmark 0x1 lookup 100 >/dev/null 2>&1 || true",
    ]
    return "".join(f"{indent}{line}\n" for line in lines)


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


def stage_desktop_entry(tree: Path) -> None:
    """Write the ``Neutrino Hub`` application entry and its icons into the tree.

    Args:
        tree: The staging directory standing in for the filesystem root.

    Raises:
        SystemExit: When an icon is not under ``images/icons``.
    """
    write(tree / f"usr/share/applications/{DESKTOP_ENTRY_NAME}.desktop", DESKTOP_ENTRY)
    for edge in DESKTOP_ICON_EDGES:
        source = ICONS_SOURCE_DIR / f"{HUB_ICON_NAME}_{edge}.png"
        if not source.is_file():
            raise SystemExit(f"no {source.name} under {ICONS_SOURCE_DIR}")
        target = tree / (
            f"usr/share/icons/hicolor/{edge}x{edge}/apps/{DESKTOP_ENTRY_NAME}.png"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        target.chmod(0o644)


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
