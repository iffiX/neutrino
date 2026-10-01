"""Build the agent's macOS installer.

    python3 agent/packaging/build_pkg.py --output-dir dist/

The installer carries the agent compiled: Nuitka turns the package and the
interpreter it runs on into a standalone ``nagent`` with the libraries beside
it, under ``/Library/Application Support/Neutrino/agent``, linked into
``/usr/local/bin``. The ``com.neutrino.agent`` LaunchDaemon runs it as root at
boot with ``run``, its output in ``/Library/Logs/neutrino_agent.log``.

RustDesk comes as upstream's app bundle out of its pinned disk image, under
``/Applications``, with the two launchd jobs its own installer would write:
the ``com.carriez.RustDesk_service`` daemon and the
``com.carriez.RustDesk_server`` agent in every session at the screen. The
preinstall script unloads the running jobs; the postinstall script loads
all three, the session agent into the session at the screen when there is
one.

The standalone tree is signed ad hoc, file by file: Apple Silicon refuses
native code with no signature at all. RustDesk keeps upstream's own.

Needs the Xcode command line tools for ``codesign``, ``pkgbuild`` and
``productbuild``, and ``hdiutil``, which every Mac has.

Not pure: makes a virtual environment, downloads a compiler and RustDesk,
compiles, signs, writes a package tree, runs pkgbuild and productbuild.
"""

import argparse
import platform
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "packaging"))
from shared import nuitka_build  # noqa: E402
import payload  # noqa: E402
from shared import pkg_build  # noqa: E402
from shared import rustdesk_assets  # noqa: E402

REPO_ROOT = payload.REPO_ROOT
PACKAGE_NAME = payload.PACKAGE_NAME

# The interpreter the agent is compiled against is the one running this
# script. One minor, checked, the same as the client's.
BUILD_PYTHON_VERSION = (3, 13)

AGENT_BINARY_NAME = "nagent"
# Where the standalone agent is installed, and the link a terminal reaches
# it through.
INSTALL_AGENT_DIR = Path("/Library/Application Support/Neutrino/agent")
INSTALL_LINK_PATH = Path("/usr/local/bin") / AGENT_BINARY_NAME
INSTALL_APPLICATIONS_DIR = Path("/Applications")

# The agent's own job, and where its output goes.
AGENT_LAUNCHD_LABEL = "com.neutrino.agent"
AGENT_LOG_PATH = "/Library/Logs/neutrino_agent.log"

# RustDesk's two jobs, named the way its own installer names them: the root
# service, and the server it runs in each session at the screen.
RUSTDESK_SERVICE_LABEL = "com.carriez.RustDesk_service"
RUSTDESK_SERVER_LABEL = "com.carriez.RustDesk_server"
RUSTDESK_APP_DIR = INSTALL_APPLICATIONS_DIR / rustdesk_assets.RUSTDESK_APP_NAME
RUSTDESK_BUNDLE_ID = "com.carriez.rustdesk"

# The identity the installer records the package under.
PACKAGE_IDENTIFIER = "com.neutrino.agent"

# Apple Silicon only: it is what RustDesk is pinned for.
MACOS_MACHINES = {"aarch64": "arm64"}

# The first bytes of every Mach-O file, thin or universal, either order.
MACH_O_MAGICS = (
    b"\xcf\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
    b"\xca\xfe\xba\xbe",
    b"\xbe\xba\xfe\xca",
)

PREINSTALL = f"""#!/bin/sh
# An upgrade replaces files the running jobs hold.
launchctl bootout system/{AGENT_LAUNCHD_LABEL} 2>/dev/null || true
launchctl bootout system/{RUSTDESK_SERVICE_LABEL} 2>/dev/null || true
exit 0
"""

POSTINSTALL = f"""#!/bin/sh
launchctl bootstrap system /Library/LaunchDaemons/{RUSTDESK_SERVICE_LABEL}.plist || true
launchctl bootstrap system /Library/LaunchDaemons/{AGENT_LAUNCHD_LABEL}.plist
# The session server goes into the session at the screen now; later sessions
# load it themselves.
seat=$(stat -f %u /dev/console)
if [ "$seat" != 0 ]; then
    launchctl bootstrap gui/"$seat" /Library/LaunchAgents/{RUSTDESK_SERVER_LABEL}.plist || true
fi
echo ""
echo "  Neutrino agent installed. Join a hub with:"
echo ""
echo "      sudo nagent join <enrollment link>"
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
        "--stage-only",
        action="store_true",
        help="write and check the package root, then stop before pkgbuild",
    )
    arguments = parser.parse_args()

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
        ``arm64``.

    Raises:
        SystemExit: When it is not a machine the agent is published for on
            macOS.
    """
    name = payload.machine_name(architecture)
    if name not in MACOS_MACHINES:
        raise SystemExit(f"the macOS agent is published for arm64, not {architecture}")
    return MACOS_MACHINES[name]


def pkg_name(version: str, machine: str) -> str:
    """What the installer is called, the way the release publishes it.

    Args:
        version: The version being packaged.
        machine: ``arm64``.

    Returns:
        The file name.
    """
    return f"{PACKAGE_NAME}-{version}-macos-{machine}.pkg"


def write_launchd_jobs(package_root: Path) -> None:
    """Write the agent's LaunchDaemon and RustDesk's two jobs.

    Args:
        package_root: The directory standing in for the filesystem root.
    """
    pkg_build.write_launchd_plist(
        package_root,
        label=AGENT_LAUNCHD_LABEL,
        program_arguments=[str(INSTALL_AGENT_DIR / AGENT_BINARY_NAME), "run"],
        log_path=AGENT_LOG_PATH,
    )
    macos_dir = RUSTDESK_APP_DIR / "Contents" / "MacOS"
    pkg_build.write_launchd_plist(
        package_root,
        label=RUSTDESK_SERVICE_LABEL,
        program_arguments=["/bin/sh", "-c", str(macos_dir / "service")],
        extra={"WorkingDirectory": str(macos_dir)},
    )
    pkg_build.write_launchd_plist(
        package_root,
        label=RUSTDESK_SERVER_LABEL,
        program_arguments=[str(macos_dir / "RustDesk"), "--server"],
        is_agent=True,
        extra={
            "LimitLoadToSessionType": ["LoginWindow", "Aqua"],
            "KeepAlive": {"SuccessfulExit": False, "AfterInitialDemand": True},
            "AssociatedBundleIdentifiers": RUSTDESK_BUNDLE_ID,
            "WorkingDirectory": str(macos_dir),
        },
    )


def _lay_out(root: Path, version: str, machine: str) -> dict:
    """Write everything the installer carries.

    Args:
        root: The working directory to build under.
        version: The version being packaged.
        machine: ``arm64``.

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
    _sign_tree(installed)

    link = package_root / str(INSTALL_LINK_PATH).lstrip("/")
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(INSTALL_AGENT_DIR / AGENT_BINARY_NAME)

    rustdesk_assets.stage_darwin_app(
        package_root / str(INSTALL_APPLICATIONS_DIR).lstrip("/")
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
        machine: ``arm64``, as asked for.

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
        options=("--include-package=neutrino_agent",),
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
        with open(path, "rb") as stream:
            if stream.read(4) in MACH_O_MAGICS:
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


if __name__ == "__main__":
    raise SystemExit(main())
