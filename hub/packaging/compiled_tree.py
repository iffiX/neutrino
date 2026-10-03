"""Staging the compiled hub the macOS and Windows packages carry.

Nuitka turns the hub package and the interpreter running the build into one
standalone ``nhub`` with its libraries beside it, and ``neutrino_hub/data``
is copied beside the compiled package, where its modules look for it. The
package is staged with its version stamped, the panel built and the icons
in it; the checkout itself is never what ships. The agent packages a
release built are named in the manifest, and the one for the hub's own
system and machine is seeded into the agent cache.

Not pure: makes a virtual environment, runs the compiler, copies files.
"""

import json
import shutil
import sys
from pathlib import Path

import venv_tree

SHARED_PACKAGING_DIR = Path(__file__).resolve().parents[2] / "packaging"
if str(SHARED_PACKAGING_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_PACKAGING_DIR))
from shared import nuitka_build  # noqa: E402

HUB_ROOT = venv_tree.HUB_ROOT
PACKAGE_NAME = venv_tree.PACKAGE_NAME

# The interpreter the hub is compiled against is the one running the build.
# One minor, checked, the same as the agent's and the client's.
BUILD_PYTHON_VERSION = (3, 13)

# Imported by name at run time rather than by an import a scan follows: the
# subcommands the entry point looks up in its table, and the event loop and
# protocol implementations uvicorn picks by string.
COMPILED_PACKAGES = ("neutrino_hub", "uvicorn")

# The package's data directory, and the icons' directory inside it.
DATA_DIR_NAME = "data"
RESOURCES_DIR_NAME = "resources"
# The runtime's own names for the two state directories the package seeds.
AGENT_CACHE_DIR_NAME = venv_tree.AGENT_PACKAGE_CACHE_DIR.name
GEODATA_DIR_NAME = venv_tree.GEODATA_DIR.name


def check_build_python() -> None:
    """Refuse a build that would carry another interpreter than the pinned one.

    Raises:
        SystemExit: When this Python is not the pinned minor.
    """
    if sys.version_info[:2] != BUILD_PYTHON_VERSION:
        wanted = ".".join(str(part) for part in BUILD_PYTHON_VERSION)
        raise SystemExit(
            f"the hub is compiled against Python {wanted}; "
            f"this is {sys.version.split()[0]}"
        )


def stage_hub_tree(parent: Path, version: str, asset: str) -> Path:
    """Copy the hub package into a tree, stamped, with its panel and icons.

    Args:
        parent: The directory the package is copied into.
        version: The version being packaged.
        asset: The file name this build writes, with ``{version}`` left
            open, stamped beside the version.

    Returns:
        The staged ``neutrino_hub`` directory.

    Raises:
        SystemExit: When the panel is not built, or there are no icons.
    """
    venv_tree.require_built_frontend()
    package = parent / "neutrino_hub"
    shutil.copytree(
        HUB_ROOT / "neutrino_hub",
        package,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "_version.py"),
    )
    (package / "_version.py").write_text(
        venv_tree.version_stamp(version, asset), encoding="utf-8"
    )
    icons = sorted(venv_tree.ICONS_SOURCE_DIR.glob("*.png"))
    if not icons:
        raise SystemExit(f"no icons to ship under {venv_tree.ICONS_SOURCE_DIR}")
    resources = package / DATA_DIR_NAME / RESOURCES_DIR_NAME
    resources.mkdir(parents=True, exist_ok=True)
    for icon in icons:
        shutil.copyfile(icon, resources / icon.name)
    return package


def make_build_environment(venv: Path) -> Path:
    """A virtual environment holding the pinned compiler and the hub's
    dependencies.

    Args:
        venv: Where to make it.

    Returns:
        The environment's interpreter.

    Raises:
        SystemExit: When pip refuses.
    """
    venv_tree.run([sys.executable, "-m", "venv", str(venv)])
    if sys.platform == "win32":
        python = venv / "Scripts" / "python.exe"
    else:
        python = venv / "bin" / "python3"
    venv_tree.run(nuitka_build.pip_install_command(python))
    # A dependency with no wheel for this machine would be compiled here,
    # against whatever libraries the build machine has installed.
    venv_tree.run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--quiet",
            "--only-binary=:all:",
            str(HUB_ROOT),
        ]
    )
    return python


def compile_hub(
    python: Path, tree: Path, build: Path, binary_name: str, options: tuple = ()
) -> Path:
    """Run Nuitka over the staged package and put its data beside it.

    Args:
        python: The build environment's interpreter.
        tree: The directory the staged ``neutrino_hub`` package is in.
        build: Where the compiler works.
        binary_name: What the binary is called.
        options: Options beyond the packages every hub build names.

    Returns:
        The standalone directory: the binary, everything it loads, and
        ``neutrino_hub/data``.

    Raises:
        SystemExit: When the compiler refuses or writes no binary.
    """
    dist = nuitka_build.compile_standalone(
        python,
        tree / "neutrino_hub" / "cli" / "entry.py",
        build,
        binary_name,
        source_root=tree,
        options=(
            *(f"--include-package={name}" for name in COMPILED_PACKAGES),
            *options,
        ),
    )
    shutil.copytree(
        tree / "neutrino_hub" / DATA_DIR_NAME,
        dist / "neutrino_hub" / DATA_DIR_NAME,
        dirs_exist_ok=True,
    )
    return dist


def seed_agent_cache(
    agent_packages: Path,
    cache: Path,
    data: Path,
    *,
    family: str,
    machine: str,
    url_base: str = "",
) -> Path:
    """Name every agent package in the manifest and seed the hub's own.

    Args:
        agent_packages: The directory the release's agent builds are in.
        cache: The agent cache directory in the package tree.
        data: The compiled package's ``neutrino_hub/data``, where the
            manifest is written.
        family: ``msi`` or ``pkg``, the hub's own system's.
        machine: ``amd64`` or ``arm64``, the hub's own machine.
        url_base: Where a release publishes the packages, empty for a build
            that publishes nothing.

    Returns:
        The seeded package.

    Raises:
        SystemExit: When the directory holds no agent package, a file's name
            says no family or machine, or none is for this system and
            machine.
    """
    found = sorted(
        path
        for path in agent_packages.iterdir()
        if path.is_file() and path.name.startswith("neutrino-agent")
    )
    if not found:
        raise SystemExit(f"no agent package under {agent_packages}")
    manifest = venv_tree.agent_cache_entries(found, url_base)
    key = venv_tree.AGENT_PLATFORM_KEY(family, machine)
    if key not in manifest:
        raise SystemExit(
            f"no agent {family} for {machine} under {agent_packages}; "
            "build it first and pass its directory"
        )
    name = venv_tree.AGENT_PACKAGE_NAME(manifest[key])
    cache.mkdir(parents=True, exist_ok=True)
    seeded = cache / name
    shutil.copyfile(agent_packages / name, seeded)
    data.mkdir(parents=True, exist_ok=True)
    (data / venv_tree.AGENT_PACKAGE_MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return seeded


def stage_licenses(destination: Path) -> None:
    """Copy the licences of everything the package carries into it.

    Args:
        destination: The directory the licences belong in.
    """
    destination.mkdir(parents=True, exist_ok=True)
    for path in sorted((HUB_ROOT.parent / "licenses").iterdir()):
        if path.is_file():
            shutil.copyfile(path, destination / path.name)
