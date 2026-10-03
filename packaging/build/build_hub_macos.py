"""Build the hub's macOS installer.

    python3 packaging/build/build_hub_macos.py --output-dir dist/ \
        --architecture arm64 --agent-packages dist/

Runs on: macOS on Apple silicon or on Intel, the machine the package is
for, with Python 3.13 and the Xcode command line tools, after ``npm run
build`` in ``hub/frontend``. ``--agent-packages`` names a directory holding
the agent's ``.pkg`` of the same machine, built before.

The installer carries the hub compiled: Nuitka turns the package and the
interpreter it runs on into a standalone ``nhub`` with the libraries and
``neutrino_hub/data`` beside it, under
``/Library/Application Support/Neutrino/hub/app``, linked into
``/usr/local/bin``. Beside it under ``bin`` are xray, cli-proxy-api,
netbird, easytier-core, easytier-cli and tun2socks for the machine. The
geodata and the agent's ``.pkg`` land under the state directory, every
agent package in the directory named in the manifest.

The ``com.neutrino.hub`` LaunchDaemon runs ``nhub run`` as root. The
postinstall makes ``config`` and ``state`` root's alone and the log
directory, loads and starts the service, which serves the setup wizard
until the box is set up, and prints the wizard's address. An upgrade over a
hub whose service was loaded loads it again.

``/Applications/Neutrino Hub.app`` is the application entry: a bundle
holding a script that runs ``nhub open``, and the icon.

Every Mach-O file is read back with ``otool`` and refused when it loads a
library from outside the system, then signed ad hoc: Apple silicon refuses
native code with no signature at all.

Not pure: makes a virtual environment, downloads a compiler and the
programs the hub drives, compiles, signs, writes a package tree, runs
pkgbuild and productbuild.
"""

import argparse
import platform
import plistlib
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "hub" / "packaging"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packaging"))
import compiled_tree  # noqa: E402
from constants import HUB_ICON_NAME  # noqa: E402
from shared import hub_assets  # noqa: E402
from shared import pkg_build  # noqa: E402
from shared.constants import PACKAGING_ASSET_PATTERNS  # noqa: E402
import venv_tree  # noqa: E402

sys.path.append(
    str(Path(__file__).resolve().parents[2] / "client" / "desktop" / "packaging")
)
import icons  # noqa: E402

PACKAGE_NAME = compiled_tree.PACKAGE_NAME

HUB_BINARY_NAME = "nhub"
# The hub's directory of the one Neutrino tree, and the three roots under it
# and beside it the runtime reads.
INSTALL_HUB_DIR = Path("/Library/Application Support/Neutrino/hub")
INSTALL_APP_DIR = INSTALL_HUB_DIR / "app"
INSTALL_CONFIG_DIR = INSTALL_HUB_DIR / "config"
INSTALL_STATE_DIR = INSTALL_HUB_DIR / "state"
INSTALL_LOG_DIR = Path("/Library/Logs/Neutrino/hub")
INSTALL_LINK_PATH = Path("/usr/local/bin") / HUB_BINARY_NAME
# Where the programs the hub drives sit, under the program root.
PROGRAMS_DIR_NAME = "bin"

# The one service: the supervisor, which serves the panel and runs every
# daemon as its child. Its own output goes beside the children's logs.
HUB_LAUNCHD_LABEL = "com.neutrino.hub"
HUB_RUN_ARGUMENTS = ("run",)
HUB_LOG_PATH = str(INSTALL_LOG_DIR / "hub.log")
HUB_LAUNCHD_PLIST = f"/Library/LaunchDaemons/{HUB_LAUNCHD_LABEL}.plist"
# Left by the preinstall when the service was loaded, so the postinstall of
# an upgrade loads it again.
RELOAD_MARKER = INSTALL_STATE_DIR / ".reload_after_install"

# The application entry: a bundle whose program is a script that opens the
# panel, or the setup wizard before setup.
APP_ENTRY_NAME = "Neutrino Hub"
APP_BUNDLE_DIR = Path("/Applications") / f"{APP_ENTRY_NAME}.app"
APP_BUNDLE_IDENTIFIER = "com.neutrino.hub.open"
APP_ICON_NAME = "neutrino_hub"
APP_SCRIPT = f"""#!/bin/sh
exec "{INSTALL_LINK_PATH}" open
"""

# The identity the installer records the package under.
PACKAGE_IDENTIFIER = "com.neutrino.hub"

# What each name for the machine maps to: the platform the package is named
# for, Apple silicon and Intel.
MACOS_MACHINES = {"aarch64": "arm64", "x86_64": "amd64"}
# The agent package family a macOS hub seeds.
AGENT_FAMILY = "pkg"

PREINSTALL = f"""#!/bin/sh
# An upgrade replaces files the running service holds.
rm -f "{RELOAD_MARKER}"
if launchctl print system/{HUB_LAUNCHD_LABEL} >/dev/null 2>&1; then
    touch "{RELOAD_MARKER}"
    launchctl bootout system/{HUB_LAUNCHD_LABEL} 2>/dev/null || true
fi
exit 0
"""

POSTINSTALL = f"""#!/bin/sh
for directory in "{INSTALL_CONFIG_DIR}" "{INSTALL_STATE_DIR}"; do
    mkdir -p "$directory"
    chown root:wheel "$directory"
    chmod 700 "$directory"
done
mkdir -p "{INSTALL_LOG_DIR}"
if [ -f "{RELOAD_MARKER}" ]; then
    rm -f "{RELOAD_MARKER}"
    launchctl bootstrap system {HUB_LAUNCHD_PLIST} || true
    exit 0
fi
launchctl bootstrap system {HUB_LAUNCHD_PLIST} 2>/dev/null || true
launchctl kickstart system/{HUB_LAUNCHD_LABEL} 2>/dev/null || true
address="$("{INSTALL_LINK_PATH}" open --print 2>/dev/null)" || address=""
echo ""
if [ -n "$address" ]; then
    echo "  Neutrino Hub installed. Set it up in a browser at:"
    echo ""
    echo "      $address"
else
    echo "  Neutrino Hub installed. Open Neutrino Hub in Applications to set it up."
fi
echo ""
echo "  Or in a terminal: sudo nhub setup"
echo ""
exit 0
"""


def main() -> int:
    """Build the installer.

    Returns:
        The process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", default="dist", help="where to write the .pkg")
    parser.add_argument(
        "--architecture", default="arm64", help="the architecture to build for"
    )
    parser.add_argument(
        "--agent-packages",
        required=True,
        help="a directory of agent packages already built, the agent's .pkg "
        "of this machine among them",
    )
    parser.add_argument(
        "--agent-package-url-base",
        default="",
        help="where a release publishes the agent packages the manifest names",
    )
    parser.add_argument(
        "--stage-only",
        action="store_true",
        help="write and check the package root, then stop before pkgbuild",
    )
    arguments = parser.parse_args()
    _check_tools(arguments.stage_only)

    version = venv_tree.version()
    machine = macos_machine(arguments.architecture)
    output_dir = Path(arguments.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / pkg_name(version, machine)

    with tempfile.TemporaryDirectory() as workdir:
        root = Path(workdir)
        staged = _lay_out(
            root,
            version,
            machine,
            agent_packages=Path(arguments.agent_packages).resolve(),
            url_base=arguments.agent_package_url_base,
        )
        if arguments.stage_only:
            print(f"staged {staged['root']}")
            return 0
        pkg_build.build(
            staged["root"],
            target,
            identifier=PACKAGE_IDENTIFIER,
            version=version,
            scripts_dir=staged["scripts"],
        )

    if not target.is_file():
        raise SystemExit(f"productbuild wrote no {target.name}")
    print(f"wrote {target} ({target.stat().st_size // 1024 // 1024} MiB)")
    return 0


def macos_machine(architecture: str) -> str:
    """The platform name the package carries for a machine.

    Args:
        architecture: The architecture, named however the command line
            names it.

    Returns:
        ``arm64`` or ``amd64``.

    Raises:
        SystemExit: When it is not a machine the hub is published for on
            macOS.
    """
    name = venv_tree.MACHINE_NAMES.get(architecture, "")
    if name not in MACOS_MACHINES:
        raise SystemExit(
            f"the macOS hub is published for arm64 and amd64, not {architecture}"
        )
    return MACOS_MACHINES[name]


def pkg_name(version: str, machine: str) -> str:
    """What the installer is called, the way the release publishes it.

    Args:
        version: The version being packaged, or ``{version}`` to leave it
            open for the stamp.
        machine: ``arm64`` or ``amd64``.

    Returns:
        The file name.
    """
    return PACKAGING_ASSET_PATTERNS["macos_pkg"].format(
        name=PACKAGE_NAME, version=version, architecture=machine
    )


def write_launchd_job(package_root: Path) -> Path:
    """Write the hub's LaunchDaemon into the package root.

    Args:
        package_root: The directory standing in for the filesystem root.

    Returns:
        The plist written.
    """
    return pkg_build.write_launchd_plist(
        package_root,
        label=HUB_LAUNCHD_LABEL,
        program_arguments=[str(INSTALL_APP_DIR / HUB_BINARY_NAME), *HUB_RUN_ARGUMENTS],
        log_path=HUB_LOG_PATH,
    )


def write_app_entry(package_root: Path, version: str) -> Path:
    """Write ``Neutrino Hub.app`` into the package root.

    Args:
        package_root: The directory standing in for the filesystem root.
        version: The version the bundle declares.

    Returns:
        The bundle written.

    Raises:
        SystemExit: When there is no icon to draw it with.
    """
    bundle = package_root / str(APP_BUNDLE_DIR).lstrip("/")
    contents = bundle / "Contents"
    script = contents / "MacOS" / APP_ENTRY_NAME
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(APP_SCRIPT, encoding="utf-8")
    script.chmod(0o755)
    icons.write_icns(
        contents / "Resources" / f"{APP_ICON_NAME}.icns", name=HUB_ICON_NAME
    )
    information = {
        "CFBundleName": APP_ENTRY_NAME,
        "CFBundleDisplayName": APP_ENTRY_NAME,
        "CFBundleIdentifier": APP_BUNDLE_IDENTIFIER,
        "CFBundleExecutable": APP_ENTRY_NAME,
        "CFBundleIconFile": APP_ICON_NAME,
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
    }
    (contents / "Info.plist").write_bytes(plistlib.dumps(information))
    return bundle


def _lay_out(
    root: Path, version: str, machine: str, *, agent_packages: Path, url_base: str
) -> dict:
    """Write everything the installer carries.

    Args:
        root: The working directory to build under.
        version: The version being packaged.
        machine: ``arm64`` or ``amd64``.
        agent_packages: The directory the agent's packages are in.
        url_base: Where a release publishes them, empty for none.

    Returns:
        ``{"root", "scripts"}``: the package root standing in for the
        filesystem, and the install scripts.

    Raises:
        SystemExit: When this is not a Mac of the pinned Python and
            machine, the compile writes no binary, a carried file is not
            what was pinned, or no agent package is there for the machine.
    """
    _check_build_machine(machine)
    tree = root / "tree"
    compiled_tree.stage_hub_tree(tree, version, pkg_name("{version}", machine))

    python = compiled_tree.make_build_environment(root / "venv")
    dist = compiled_tree.compile_hub(python, tree, root / "build", HUB_BINARY_NAME)

    package_root = root / "root"
    app = package_root / str(INSTALL_APP_DIR).lstrip("/")
    app.parent.mkdir(parents=True)
    shutil.copytree(dist, app, symlinks=True)
    hub_assets.stage_programs(app / PROGRAMS_DIR_NAME, "darwin", machine)
    compiled_tree.stage_licenses(app / "licenses")

    state = package_root / str(INSTALL_STATE_DIR).lstrip("/")
    hub_assets.stage_geodata(state / compiled_tree.GEODATA_DIR_NAME)
    compiled_tree.seed_agent_cache(
        agent_packages,
        state / compiled_tree.AGENT_CACHE_DIR_NAME,
        app / "neutrino_hub" / compiled_tree.DATA_DIR_NAME,
        family=AGENT_FAMILY,
        machine=machine,
        url_base=url_base,
    )
    pkg_build.require_system_links(app)
    _sign_tree(app)

    link = package_root / str(INSTALL_LINK_PATH).lstrip("/")
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(INSTALL_APP_DIR / HUB_BINARY_NAME)

    write_launchd_job(package_root)
    pkg_build.sign_ad_hoc(write_app_entry(package_root, version))
    scripts = pkg_build.write_scripts(
        root / "scripts", preinstall=PREINSTALL, postinstall=POSTINSTALL
    )
    return {"root": package_root, "scripts": scripts}


def _check_build_machine(machine: str) -> None:
    """Refuse a build off a Mac, one that would carry another interpreter
    than the pinned one, or one for a machine this is not.

    Args:
        machine: ``arm64`` or ``amd64``, as asked for.

    Raises:
        SystemExit: On any mismatch.
    """
    if sys.platform != "darwin":
        raise SystemExit(
            f"the macOS installer is built on a Mac; this is {sys.platform}"
        )
    compiled_tree.check_build_python()
    here = MACOS_MACHINES.get(
        venv_tree.MACHINE_NAMES.get(platform.machine().lower(), ""), ""
    )
    if here != machine:
        raise SystemExit(
            f"an installer for {machine} is compiled on an {machine} Mac; "
            f"this one is {platform.machine()}"
        )


def _sign_tree(directory: Path) -> None:
    """Sign every Mach-O file under a directory ad hoc.

    Args:
        directory: The standalone tree.

    Raises:
        SystemExit: When codesign refuses.
    """
    for path in sorted(directory.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        if pkg_build.is_mach_o(path):
            pkg_build.sign_ad_hoc(path)


def _check_tools(is_stage_only: bool) -> None:
    """Refuse to start on a machine that cannot finish the build.

    Args:
        is_stage_only: Whether the build stops before pkgbuild.

    Raises:
        SystemExit: When this is not a Mac, or a tool is missing.
    """
    if sys.platform != "darwin":
        raise SystemExit(f"{Path(__file__).name} runs on macOS; this is {sys.platform}")
    tools = ("codesign",) + (() if is_stage_only else ("pkgbuild", "productbuild"))
    for tool in tools:
        if shutil.which(tool) is None:
            raise SystemExit(
                f"{tool} is needed and is not on the path: xcode-select --install"
            )


if __name__ == "__main__":
    raise SystemExit(main())
