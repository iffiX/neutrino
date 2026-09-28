"""Build the client's macOS installer.

    python3 client/packaging/build_pkg.py --output-dir dist/

The installer carries the client compiled into an app bundle: Nuitka turns
the package, the interpreter it runs on and the window's Python side into
``Neutrino Client.app`` with ``nclient`` as its binary and the libraries
beside it. The interpreter compiled in is the one running this script, so
the build machine's Python is pinned to a minor here and checked; the
compile is native, so an Apple Silicon package comes off an Apple Silicon
Mac.

The client is a person's application, not a service and not a login item:
it runs when the person opens it. The installer puts the bundle under
``/Applications`` and links ``nclient`` into ``/usr/local/bin``. The two
overlay daemons it carries are LaunchDaemons, both kept running: NetBird's,
and the client's own EasyTier daemon, ``nclient easytier-daemon``, which
runs EasyTier's core only while a network or a console is configured.

The bundle is signed ad hoc. Apple Silicon refuses native code with no
signature at all, and an ad hoc one is what a build with no developer
identity can give; Gatekeeper still asks the person once on first open.

Needs the Xcode command line tools for ``codesign``, ``pkgbuild`` and
``productbuild``, and ``hdiutil``, which every Mac has.

Not pure: makes a virtual environment, downloads wheels and a compiler,
compiles, signs, writes a package tree, runs pkgbuild and productbuild.
"""

import argparse
import os
import platform
import shlex
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "packaging"))
import bundled  # noqa: E402
import icons  # noqa: E402
import nuitka_build  # noqa: E402
import payload  # noqa: E402
import pkg_build  # noqa: E402

# The labels, the directories and the portal are the client's own, named here
# so the installer and the runtime cannot drift.
from neutrino_client.constants import (  # noqa: E402
    CLIENT_BUNDLED_PATHS_DARWIN,
    CLIENT_EASYTIER_DAEMON_VERB,
    CLIENT_EASYTIER_LAUNCHD_LABEL,
    CLIENT_EASYTIER_STATE_DIR_DARWIN,
    CLIENT_LAUNCHD_DAEMONS_DIR,
    CLIENT_NETBIRD_CONFIG_PATH_DARWIN,
    CLIENT_NETBIRD_LAUNCHD_LABEL,
)

CLIENT_ROOT = payload.CLIENT_ROOT
REPO_ROOT = payload.REPO_ROOT
PACKAGE_NAME = payload.PACKAGE_NAME

# The interpreter the client is compiled against is the one running this
# script, so it is what the bundle carries. One minor, checked, so a build
# machine with another does not quietly ship a different Python.
BUILD_PYTHON_VERSION = (3, 13)

# What the compiled client is called inside the bundle, and what the bundle
# itself is called under /Applications.
CLIENT_BINARY_NAME = "nclient"
APP_NAME = "Neutrino Client"
APP_BUNDLE_NAME = f"{APP_NAME}.app"

# The identity the installer records the package under.
PACKAGE_IDENTIFIER = "com.neutrino.client"

# Where the installer puts the bundle, and the link a terminal reaches the
# command through.
INSTALL_APPLICATIONS_DIR = Path("/Applications")
INSTALL_LINK_PATH = Path("/usr/local/bin") / CLIENT_BINARY_NAME

# What the install runs around the files: both daemons unloaded and NetBird
# taken off its network before, their directories made and both loaded
# after.
PREINSTALL = f"""#!/bin/sh
for label in {CLIENT_NETBIRD_LAUNCHD_LABEL} {CLIENT_EASYTIER_LAUNCHD_LABEL}; do
    launchctl bootout "system/$label" >/dev/null 2>&1 || true
done
exit 0
"""
POSTINSTALL = f"""#!/bin/sh
for directory in "{os.path.dirname(CLIENT_NETBIRD_CONFIG_PATH_DARWIN)}" \\
        "{CLIENT_EASYTIER_STATE_DIR_DARWIN}"; do
    mkdir -p "$directory"
    chown root:wheel "$directory"
    chmod 700 "$directory"
done
for label in {CLIENT_NETBIRD_LAUNCHD_LABEL} {CLIENT_EASYTIER_LAUNCHD_LABEL}; do
    launchctl bootstrap system "{CLIENT_LAUNCHD_DAEMONS_DIR}/$label.plist" \\
        >/dev/null 2>&1 || true
done
exit 0
"""

# Where each daemon's output goes.
NETBIRD_LOG_PATH = "/Library/Logs/neutrino_client_netbird.log"
# The socket every NetBird daemon on a Mac listens on; one already there
# belongs to NetBird's own install, which the client then uses as it is.
NETBIRD_SOCKET_PATH = "/var/run/netbird.sock"
EASYTIER_LOG_PATH = "/Library/Logs/neutrino_client_easytier.log"

# What each name for the machine maps to: the wheel's own, and the platform
# the package is named for. Apple Silicon only.
MACOS_MACHINES = {"aarch64": "arm64"}

# The window's Python side, pinned to the file and compiled in: pyobjc's
# core, the Cocoa wrappers the window and the menu bar item run on, and the
# WebKit wrappers the page loads through. One version across the three.
PYOBJC_VERSION = "12.2.2"
MACOS_WHEELS = (
    (
        "pyobjc-core",
        PYOBJC_VERSION,
        "https://files.pythonhosted.org/packages/1b/ed/"
        "a8bf040caf3704023d74086b7fb96cf4ed2e844e24bd94e5248ba214b700/"
        "pyobjc_core-12.2.2-cp313-cp313-macosx_10_13_universal2.whl",
        "950bd2d9c74634398c4e3d24ef2f213d4e23d705083697464fa67afedc53c1ad",  # scan: allow
    ),
    (
        "pyobjc-framework-Cocoa",
        PYOBJC_VERSION,
        "https://files.pythonhosted.org/packages/db/e1/"
        "5d9b04ebb60042b9cb49adc2d33115e2f2c2e4ff7d548017bfaff8b7f536/"
        "pyobjc_framework_cocoa-12.2.2-cp313-cp313-macosx_10_13_universal2.whl",
        "600b1723184ca094931330e79355274949965460e23de38628d601b5a967baf9",  # scan: allow
    ),
    (
        "pyobjc-framework-WebKit",
        PYOBJC_VERSION,
        "https://files.pythonhosted.org/packages/69/84/"
        "036541aaf4795c0022b6b1dda9a4e099e14b137012065a799a0b174947e5/"
        "pyobjc_framework_webkit-12.2.2-cp313-cp313-macosx_10_13_universal2.whl",
        "206f88451e1c3e152c72c16c2af2664646cd752a3007c9cda8029a9e3f0ec9a4",  # scan: allow
    ),
)

# The packages those wheels install, named to the compiler: the shell
# imports them at the moment a window opens, which no import scan sees.
PYOBJC_PACKAGES = (
    "objc",
    "PyObjCTools",
    "CoreFoundation",
    "Foundation",
    "AppKit",
    "WebKit",
)


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
    target = output_dir / f"{PACKAGE_NAME}-{version}-macos-{machine}.pkg"

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
        SystemExit: When it is not a machine the client is published for
            on macOS.
    """
    name = payload.machine_name(architecture)
    if name not in MACOS_MACHINES:
        raise SystemExit(
            f"the macOS client is published for {', '.join(sorted(MACOS_MACHINES))}, "
            f"not {architecture}"
        )
    return MACOS_MACHINES[name]


def _lay_out(root: Path, version: str, machine: str) -> dict:
    """Write everything the installer carries.

    Args:
        root: The working directory to build under.
        version: The version being packaged.
        machine: ``arm64``.

    Returns:
        ``{"root", "app", "scripts"}``: the package root standing in for the
        filesystem, the signed bundle under it, and the install scripts.

    Raises:
        SystemExit: When this is not a Mac of the pinned Python and
            machine, when the compile writes no bundle, or when a carried
            file is not what was pinned.
    """
    _check_build_machine(machine)

    # The package with its version stamped and its page beside it, which is
    # what the compiler is pointed at; the checkout itself is never what
    # ships.
    tree = root / "tree"
    package = payload.stage_client_tree(tree, version)

    python = _make_build_environment(root / "venv")
    compiled = _compile(python, tree, root / "build", version)

    package_root = root / "root"
    app = package_root / str(INSTALL_APPLICATIONS_DIR).lstrip("/") / APP_BUNDLE_NAME
    app.parent.mkdir(parents=True)
    shutil.move(str(compiled), str(app))
    contents = app / "Contents"
    # Compiled modules keep a __file__ under Contents/MacOS, so the
    # package's own data goes beside where that points.
    shutil.copytree(package / "data", contents / "MacOS" / package.name / "data")

    bundled.stage_darwin_binaries(contents)
    _stage_licenses(contents / "Resources" / "licenses")
    pkg_build.sign_ad_hoc(app)

    link = package_root / str(INSTALL_LINK_PATH).lstrip("/")
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(
        INSTALL_APPLICATIONS_DIR
        / APP_BUNDLE_NAME
        / "Contents/MacOS"
        / CLIENT_BINARY_NAME
    )
    write_daemons(package_root)
    scripts = pkg_build.write_scripts(
        root / "scripts", preinstall=PREINSTALL, postinstall=POSTINSTALL
    )
    return {"root": package_root, "app": app, "scripts": scripts}


def installed_resource(name: str) -> str:
    """Where one carried binary is once the bundle is installed.

    Args:
        name: The binary's name in ``CLIENT_BUNDLED_PATHS_DARWIN``.

    Returns:
        Its absolute path.
    """
    return str(
        INSTALL_APPLICATIONS_DIR
        / APP_BUNDLE_NAME
        / "Contents"
        / CLIENT_BUNDLED_PATHS_DARWIN[name]
    )


def netbird_command() -> str:
    """The shell that runs NetBird unless another daemon holds its socket.

    Returns:
        ``/bin/sh -c`` text that exits 0 when the socket exists and otherwise
        runs the daemon in its place.
    """
    netbird = shlex.quote(installed_resource("netbird"))
    config = shlex.quote(CLIENT_NETBIRD_CONFIG_PATH_DARWIN)
    return (
        f"[ -S {NETBIRD_SOCKET_PATH} ] && exit 0; "
        f"exec {netbird} service run --config {config} --log-file console"
    )


def easytier_daemon_arguments() -> list:
    """The client's EasyTier daemon, as its LaunchDaemon runs it.

    Returns:
        The installed client and the daemon's verb.
    """
    return [
        str(
            INSTALL_APPLICATIONS_DIR
            / APP_BUNDLE_NAME
            / "Contents/MacOS"
            / CLIENT_BINARY_NAME
        ),
        CLIENT_EASYTIER_DAEMON_VERB,
    ]


def write_daemons(package_root: Path) -> None:
    """Write both daemons' LaunchDaemons into the package root.

    Args:
        package_root: The directory standing in for the filesystem root.
    """
    pkg_build.write_launchd_plist(
        package_root,
        label=CLIENT_NETBIRD_LAUNCHD_LABEL,
        program_arguments=["/bin/sh", "-c", netbird_command()],
        log_path=NETBIRD_LOG_PATH,
        extra={"KeepAlive": {"SuccessfulExit": False}},
    )
    pkg_build.write_launchd_plist(
        package_root,
        label=CLIENT_EASYTIER_LAUNCHD_LABEL,
        program_arguments=easytier_daemon_arguments(),
        log_path=EASYTIER_LOG_PATH,
    )


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
            f"the client is compiled against Python {wanted}; "
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
    """A virtual environment holding the compiler and the window's Python
    side at their pinned versions.

    Args:
        venv: Where to make it.

    Returns:
        The environment's interpreter.

    Raises:
        SystemExit: When a wheel is not what was pinned, or pip refuses.
    """
    payload.run([sys.executable, "-m", "venv", str(venv)])
    python = venv / "bin" / "python3"
    payload.run(nuitka_build.pip_install_command(python))
    # Into the environment's own site-packages; pinned files by path rather
    # than names pip resolves.
    major, minor = BUILD_PYTHON_VERSION
    payload.stage_wheels(
        python,
        venv / "lib" / f"python{major}.{minor}" / "site-packages",
        MACOS_WHEELS,
    )
    return python


def _compile(python: Path, tree: Path, build: Path, version: str) -> Path:
    """Run Nuitka over the staged package into an app bundle.

    Args:
        python: The build environment's interpreter.
        tree: The directory the staged ``neutrino_client`` package is in.
        build: Where the compiler works.
        version: The version stamped into the bundle's own properties.

    Returns:
        The bundle: the binary under ``Contents/MacOS`` and everything
        beside it.

    Raises:
        SystemExit: When the compiler refuses or writes no bundle.
    """
    return nuitka_build.compile_app_bundle(
        python,
        tree / "neutrino_client" / "cli" / "entry.py",
        build,
        CLIENT_BINARY_NAME,
        source_root=tree,
        app_name=APP_NAME,
        icon=icons.write_icns(build.parent / "bundle.icns"),
        version=version,
        options=(
            "--include-package=neutrino_client",
            *(f"--include-package={name}" for name in PYOBJC_PACKAGES),
        ),
    )


def _stage_licenses(destination: Path) -> None:
    """Copy the licences of what the bundle carries into it.

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
