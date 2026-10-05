"""Build the agent's macOS installer.

    python3 packaging/build/build_agent_macos.py --output-dir dist/

Runs on: macOS on Apple silicon or on Intel, the machine the package is
for, with Python 3.13 and the Xcode command line tools.

The installer carries the agent compiled: Nuitka turns the package and the
interpreter it runs on into a standalone ``nagent`` with the libraries beside
it, under ``/Library/Application Support/Neutrino/agent/app``, linked into
``/usr/local/bin``. The ``com.neutrino.agent`` LaunchDaemon runs it as root at
boot with ``run``, its output in ``/Library/Logs/Neutrino/agent``.

RustDesk comes as upstream's app bundle out of its pinned disk image, copied
as it is, its signature intact, to ``app/rustdesk/RustDesk.app`` in the
agent's own folder. The package registers nothing of RustDesk's and starts
nothing of it: the agent registers its copy when the hub's Remote desktop
switch is on. The preinstall script takes away what the agent's earlier
packages installed of RustDesk at the system's standard place, as their
receipt lists it, and nothing else; the postinstall script starts the agent.
A package on macOS has no uninstaller: ``sudo nagent service uninstall``
removes the agent and what the agent's modules added, and keeps the
configuration and the state.

The standalone tree is read back with ``otool`` and refused when a file of
it loads a library from outside the system, then signed ad hoc, file by
file: Apple silicon refuses native code with no signature at all. RustDesk
is copied in after that and keeps upstream's own signature.

Needs the Xcode command line tools for ``codesign``, ``otool``, ``pkgbuild``
and ``productbuild``, and ``hdiutil``, which every Mac has.

Not pure: makes a virtual environment, downloads a compiler and RustDesk,
compiles, signs, writes a package tree, runs pkgbuild and productbuild.
"""

import argparse
import platform
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent" / "packaging"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packaging"))
from shared import edition_build  # noqa: E402
from shared import nuitka_build  # noqa: E402
import payload  # noqa: E402
from shared import pkg_build  # noqa: E402
from shared import rustdesk_assets  # noqa: E402
from shared.constants import PACKAGING_ASSET_PATTERNS  # noqa: E402

REPO_ROOT = payload.REPO_ROOT
PACKAGE_NAME = payload.PACKAGE_NAME

# The interpreter the agent is compiled against is the one running this
# script. One minor, checked, the same as the client's.
BUILD_PYTHON_VERSION = (3, 13)

AGENT_BINARY_NAME = "nagent"
# The agent's directory of the one Neutrino tree, where the standalone agent
# is installed under it, the two roots beside it the runtime reads, and the
# link a terminal reaches it through. The state root stays open to every
# account, which runs the software the hub sends from under it; what else
# it holds is root's own.
INSTALL_ROOT_DIR = Path("/Library/Application Support/Neutrino/agent")
INSTALL_AGENT_DIR = INSTALL_ROOT_DIR / "app"
INSTALL_CONFIG_DIR = INSTALL_ROOT_DIR / "config"
INSTALL_STATE_DIR = INSTALL_ROOT_DIR / "state"
# The agent's binding to its hub, which a machine that already joined holds.
INSTALL_BINDING_PATH = INSTALL_CONFIG_DIR / "agent.json"
INSTALL_LINK_PATH = Path("/usr/local/bin") / AGENT_BINARY_NAME
# The agent's copy of RustDesk, under the agent's own program directory.
INSTALL_RUSTDESK_DIR = INSTALL_AGENT_DIR / "rustdesk"

# The agent's own job, and where its output goes.
AGENT_LAUNCHD_LABEL = "com.neutrino.agent"
AGENT_LOG_DIR = "/Library/Logs/Neutrino/agent"
AGENT_LOG_PATH = AGENT_LOG_DIR + "/agent.log"

# What the agent's packages before the Remote desktop module installed of
# RustDesk at the system's standard place, by the paths their receipt lists:
# the app bundle under /Applications, and RustDesk's two jobs, the root
# service and the server it ran in each session at the screen.
OLD_RUSTDESK_APP_DIR = Path("/Applications") / rustdesk_assets.RUSTDESK_APP_NAME
OLD_RUSTDESK_SERVICE_LABEL = "com.carriez.RustDesk_service"
OLD_RUSTDESK_SERVER_LABEL = "com.carriez.RustDesk_server"
OLD_RUSTDESK_SERVICE_PLIST = f"Library/LaunchDaemons/{OLD_RUSTDESK_SERVICE_LABEL}.plist"
OLD_RUSTDESK_SERVER_PLIST = f"Library/LaunchAgents/{OLD_RUSTDESK_SERVER_LABEL}.plist"

# The identity the installer records the package under.
PACKAGE_IDENTIFIER = "com.neutrino.agent"

# What each name for the machine maps to: the platform the package is named
# for, Apple silicon and Intel.
MACOS_MACHINES = {"aarch64": "arm64", "x86_64": "amd64"}

PREINSTALL = f"""#!/bin/sh
# An upgrade replaces files the running job holds.
launchctl bootout system/{AGENT_LAUNCHD_LABEL} 2>/dev/null || true

# What an earlier package of the agent installed of RustDesk at the system's
# standard place goes, by what its receipt lists: its two jobs are booted
# out, the hosts run from its copy end, and its files are deleted. A
# RustDesk the receipt does not list is a person's own and stays.
listed=$(pkgutil --files {PACKAGE_IDENTIFIER} 2>/dev/null || true)
is_listed() {{
    printf '%s\\n' "$listed" | grep -qx "$1"
}}
if is_listed "{OLD_RUSTDESK_SERVICE_PLIST}"; then
    launchctl bootout system/{OLD_RUSTDESK_SERVICE_LABEL} 2>/dev/null || true
    rm -f "/{OLD_RUSTDESK_SERVICE_PLIST}"
fi
if is_listed "{OLD_RUSTDESK_SERVER_PLIST}"; then
    for seat in $(ps -axo uid=,comm= | awk '$2 ~ /loginwindow$/ {{print $1}}' | sort -u); do
        launchctl bootout gui/"$seat"/{OLD_RUSTDESK_SERVER_LABEL} 2>/dev/null || true
    done
    rm -f "/{OLD_RUSTDESK_SERVER_PLIST}"
fi
if is_listed "{str(OLD_RUSTDESK_APP_DIR).lstrip('/')}/Contents/MacOS/RustDesk"; then
    ps -axo pid=,command= | while read -r pid command; do
        case "$command" in
            *"{OLD_RUSTDESK_APP_DIR}/"*--connect*) ;;
            *"{OLD_RUSTDESK_APP_DIR}/"*) kill "$pid" 2>/dev/null || true ;;
        esac
    done
    rm -rf "{OLD_RUSTDESK_APP_DIR}"
fi
exit 0
"""

POSTINSTALL = f"""#!/bin/sh
{pkg_build.LAUNCHD_START_FUNCTION}
mkdir -p "{INSTALL_CONFIG_DIR}" "{INSTALL_STATE_DIR}"
chown root:wheel "{INSTALL_CONFIG_DIR}" "{INSTALL_STATE_DIR}"
chmod 700 "{INSTALL_CONFIG_DIR}"
chmod 755 "{INSTALL_STATE_DIR}"
mkdir -p "{AGENT_LOG_DIR}"
start_daemon {AGENT_LAUNCHD_LABEL} /Library/LaunchDaemons/{AGENT_LAUNCHD_LABEL}.plist || {{
    echo "  The agent's service did not start: {AGENT_LAUNCHD_LABEL}" >&2
    exit 1
}}
if ! {payload.AGENT_BOUND_TEST.format(path=INSTALL_BINDING_PATH)}; then
    echo ""
    echo "  Neutrino agent installed. Join a hub with:"
    echo ""
    echo "      sudo nagent join <enrollment link>"
    echo ""
fi
exit 0
"""


def main() -> int:
    """Build the installer.

    Returns:
        The process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    edition_build.add_edition_argument(parser)
    parser.add_argument("--output-dir", default="dist", help="where to write the .pkg")
    parser.add_argument(
        "--architecture", default="arm64", help="the architecture to build for"
    )
    parser.add_argument(
        "--stage-only",
        action="store_true",
        help="write and check the package root, then stop before pkgbuild",
    )
    arguments = parser.parse_args()
    edition_build.require_edition_tree(arguments.edition)
    _check_tools(arguments.stage_only)

    version = payload.version()
    machine = macos_machine(arguments.architecture)
    output_dir = Path(arguments.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / pkg_name(version, machine)

    with tempfile.TemporaryDirectory() as workdir:
        root = Path(workdir)
        staged = _lay_out(root, version, machine)
        if arguments.stage_only:
            print(f"staged {staged['root']}")
            return 0
        pkg_build.build(
            staged["root"],
            target,
            identifier=PACKAGE_IDENTIFIER,
            version=version,
            scripts_dir=staged["scripts"],
            title="Neutrino Agent",
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
        SystemExit: When it is not a machine the agent is published for on
            macOS.
    """
    name = payload.machine_name(architecture)
    if name not in MACOS_MACHINES:
        raise SystemExit(
            f"the macOS agent is published for arm64 and amd64, not {architecture}"
        )
    return MACOS_MACHINES[name]


def pkg_name(version: str, machine: str) -> str:
    """What the installer is called, the way the release publishes it.

    Args:
        version: The version being packaged.
        machine: ``arm64`` or ``amd64``.

    Returns:
        The file name.
    """
    return PACKAGING_ASSET_PATTERNS["macos_pkg"].format(
        name=PACKAGE_NAME, version=version, architecture=machine
    )


def write_launchd_jobs(package_root: Path) -> None:
    """Write the agent's LaunchDaemon, the one job the package installs.

    Args:
        package_root: The directory standing in for the filesystem root.
    """
    pkg_build.write_launchd_plist(
        package_root,
        label=AGENT_LAUNCHD_LABEL,
        program_arguments=[str(INSTALL_AGENT_DIR / AGENT_BINARY_NAME), "run"],
        log_path=AGENT_LOG_PATH,
    )


def _lay_out(root: Path, version: str, machine: str) -> dict:
    """Write everything the installer carries.

    Args:
        root: The working directory to build under.
        version: The version being packaged.
        machine: ``arm64`` or ``amd64``.

    Returns:
        ``{"root", "scripts"}``: the package root standing in for the
        filesystem, and the install scripts.

    Raises:
        SystemExit: When this is not a Mac of the pinned Python and
            machine, when the compile writes no binary, or when RustDesk is
            not what was pinned.
    """
    _check_build_machine(machine)
    tree = root / "tree"
    payload.stage_agent_tree(tree, version)

    python = _make_build_environment(root / "venv")
    dist = _compile(python, tree, root / "build", version)

    package_root = root / "root"
    installed = package_root / str(INSTALL_AGENT_DIR).lstrip("/")
    installed.parent.mkdir(parents=True)
    shutil.copytree(dist, installed, symlinks=True)
    _stage_licenses(installed / "licenses")
    pkg_build.require_system_links(installed)
    _sign_tree(installed)

    link = package_root / str(INSTALL_LINK_PATH).lstrip("/")
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(INSTALL_AGENT_DIR / AGENT_BINARY_NAME)

    rustdesk_assets.stage_darwin_app(
        package_root / str(INSTALL_RUSTDESK_DIR).lstrip("/"),
        machine=payload.machine_name(machine),
    )
    write_launchd_jobs(package_root)
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
    if sys.version_info[:2] != BUILD_PYTHON_VERSION:
        wanted = ".".join(str(part) for part in BUILD_PYTHON_VERSION)
        raise SystemExit(
            f"the agent is compiled against Python {wanted}; "
            f"this is {sys.version.split()[0]}"
        )
    here = MACOS_MACHINES.get(
        payload.MACHINE_NAMES.get(platform.machine().lower(), ""), ""
    )
    if here != machine:
        raise SystemExit(
            f"an installer for {machine} is compiled on an {machine} Mac; "
            f"this one is {platform.machine()}"
        )


def _make_build_environment(venv: Path) -> Path:
    """A virtual environment holding the pinned compiler.

    Args:
        venv: Where to make it.

    Returns:
        The environment's interpreter.

    Raises:
        SystemExit: When pip refuses.
    """
    payload.run([sys.executable, "-m", "venv", str(venv)])
    python = venv / "bin" / "python3"
    payload.run(nuitka_build.pip_install_command(python))
    return python


def _compile(python: Path, tree: Path, build: Path, version: str) -> Path:
    """Run Nuitka over the staged package into a standalone program.

    Args:
        python: The build environment's interpreter.
        tree: The directory the staged ``neutrino_agent`` package is in.
        build: Where the compiler works.
        version: The version being packaged.

    Returns:
        The standalone directory: the binary and everything beside it.

    Raises:
        SystemExit: When the compiler refuses or writes no binary.
    """
    return nuitka_build.compile_standalone(
        python,
        tree / "neutrino_agent" / "cli" / "entry.py",
        build,
        AGENT_BINARY_NAME,
        source_root=tree,
        options=(
            "--include-package=neutrino_agent",
            nuitka_build.NUITKA_ARGV_PASSTHROUGH,
        ),
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


def _stage_licenses(destination: Path) -> None:
    """Copy the licences of what the package carries into it.

    Args:
        destination: The directory the licences belong in.

    Raises:
        SystemExit: When a licence the package owes is not in the checkout.
    """
    destination.mkdir(parents=True, exist_ok=True)
    for name in payload.CARRIED_LICENSES:
        source = REPO_ROOT / "licenses" / name
        if not source.is_file():
            raise SystemExit(
                f"the package carries {name} and there is none at {source}"
            )
        shutil.copyfile(source, destination / name)


def _check_tools(is_stage_only: bool) -> None:
    """Refuse to start on a machine that cannot finish the build.

    Args:
        is_stage_only: Whether the build stops before pkgbuild.

    Raises:
        SystemExit: When this is not a Mac, or a tool is missing.
    """
    if sys.platform != "darwin":
        raise SystemExit(f"{Path(__file__).name} runs on macOS; this is {sys.platform}")
    tools = ("codesign", "hdiutil") + (() if is_stage_only else ("pkgbuild", "productbuild"))
    for tool in tools:
        if shutil.which(tool) is None:
            raise SystemExit(
                f"{tool} is needed and is not on the path: xcode-select --install"
            )


if __name__ == "__main__":
    raise SystemExit(main())
