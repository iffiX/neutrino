"""Build the agent's macOS installer.

    python3 agent/packaging/build_pkg.py --output-dir dist/

One package for both machines: the interpreter is python.org's universal2
framework and the window's bindings are universal2 wheels, so a single file
installs on Intel and Apple Silicon alike.

That framework is built to live at /Library/Frameworks, and says so in every
Mach-O inside it. Carrying it under /opt/neutrino_agent means rewriting those
names and signing what was rewritten — a machine's own /Library/Frameworks is
not a place this project may install into.

The agent runs as a LaunchDaemon, which the platform already reads and starts
by the label below.

Needs macOS: pkgutil, install_name_tool, codesign, pkgbuild and productbuild
are the toolchain, and no other platform has them.

Not pure: downloads an interpreter and wheels, rewrites Mach-O headers, runs
the macOS packaging tools.
"""

import argparse
import os
import plistlib
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import icons  # noqa: E402
import payload  # noqa: E402

from neutrino_agent.platforms.darwin import (  # noqa: E402
    DARWIN_AGENT_LABEL,
    DARWIN_AGENT_PLIST,
)

AGENT_ROOT = payload.AGENT_ROOT
REPO_ROOT = payload.REPO_ROOT
PACKAGE_NAME = payload.PACKAGE_NAME

# The interpreter the package carries, pinned by hash. python.org's installer
# is the only universal2 CPython published as one build.
DARWIN_PYTHON_VERSION = "3.13.7"
DARWIN_PYTHON_SERIES = "3.13"
DARWIN_PYTHON_URL = (
    "https://www.python.org/ftp/python/{version}/python-{version}-macos11.pkg"
)
DARWIN_PYTHON_SHA256 = (
    "f7e8c8d63ab0a4e736b5864aa369098b16af622042c079addb2f1a08400560c5"  # scan: allow
)

# The component inside that installer which carries the framework, and where
# its payload says the framework belongs.
DARWIN_FRAMEWORK_COMPONENT = "Python_Framework.pkg"
DARWIN_FRAMEWORK_ORIGIN = (
    f"/Library/Frameworks/Python.framework/Versions/{DARWIN_PYTHON_SERIES}"
)

# Where it goes instead, and what runs from there.
DARWIN_FRAMEWORK_DIR = payload.INSTALL_PREFIX / "python" / "Python.framework"
DARWIN_FRAMEWORK_HOME = DARWIN_FRAMEWORK_DIR / "Versions" / DARWIN_PYTHON_SERIES
DARWIN_PYTHON = DARWIN_FRAMEWORK_HOME / "bin" / f"python{DARWIN_PYTHON_SERIES}"

# A command has to be on the path, and /usr/bin is the system's own.
DARWIN_WRAPPER_PATH = "usr/local/bin/nagent"

DARWIN_PACKAGE_IDENTIFIER = "com.neutrino.agent"

# The window's Python side, pinned to the file. pywebview drives WKWebView
# through pyobjc; the rest is what pywebview itself imports.
DARWIN_WHEELS = (
    (
        "pywebview",
        "6.2.1",
        "https://files.pythonhosted.org/packages/3d/25/"
        "9491695c22c4842c5b3903b4dc172e0eecf67a27c0af34a71512c9b76a0a/"
        "pywebview-6.2.1-py3-none-any.whl",
        "9d07275f53894ab4d5e2e0e996227193e7187dec276d9b624dccbce029216b46",  # scan: allow
    ),
    (
        "pyobjc-core",
        "12.2.2",
        "https://files.pythonhosted.org/packages/1b/ed/"
        "a8bf040caf3704023d74086b7fb96cf4ed2e844e24bd94e5248ba214b700/"
        "pyobjc_core-12.2.2-cp313-cp313-macosx_10_13_universal2.whl",
        "950bd2d9c74634398c4e3d24ef2f213d4e23d705083697464fa67afedc53c1ad",  # scan: allow
    ),
    (
        "pyobjc-framework-Cocoa",
        "12.2.2",
        "https://files.pythonhosted.org/packages/db/e1/"
        "5d9b04ebb60042b9cb49adc2d33115e2f2c2e4ff7d548017bfaff8b7f536/"
        "pyobjc_framework_cocoa-12.2.2-cp313-cp313-macosx_10_13_universal2.whl",
        "600b1723184ca094931330e79355274949965460e23de38628d601b5a967baf9",  # scan: allow
    ),
    (
        "pyobjc-framework-Quartz",
        "12.2.2",
        "https://files.pythonhosted.org/packages/bb/ae/"
        "b515852dbe491171f2f2e2eb7739588a5eb7f36720a739545337b8c0d706/"
        "pyobjc_framework_quartz-12.2.2-cp313-cp313-macosx_10_13_universal2.whl",
        "0ec9751904ef975bf0789d760dc4fadcb400edc4ffe4a736eb54971968babe5c",  # scan: allow
    ),
    (
        "pyobjc-framework-WebKit",
        "12.2.2",
        "https://files.pythonhosted.org/packages/69/84/"
        "036541aaf4795c0022b6b1dda9a4e099e14b137012065a799a0b174947e5/"
        "pyobjc_framework_webkit-12.2.2-cp313-cp313-macosx_10_13_universal2.whl",
        "206f88451e1c3e152c72c16c2af2664646cd752a3007c9cda8029a9e3f0ec9a4",  # scan: allow
    ),
    (
        "pyobjc-framework-Security",
        "12.2.2",
        "https://files.pythonhosted.org/packages/f1/7f/"
        "cef885aaf57f7b8c1a5c141dc118094d07558f6c289fabd63690abf30059/"
        "pyobjc_framework_security-12.2.2-cp313-cp313-macosx_10_13_universal2.whl",
        "ca580d5f56e1222d63f1322a4fbf63be0bad77e77cca084290310df007b3fdde",  # scan: allow
    ),
    (
        "pyobjc-framework-UniformTypeIdentifiers",
        "12.2.2",
        "https://files.pythonhosted.org/packages/79/c3/"
        "45ec69ed9fdcde5d0f229a031b610127c592d2c4674c3ff0e184d7f2741b/"
        "pyobjc_framework_uniformtypeidentifiers-12.2.2-py2.py3-none-any.whl",
        "1dc6a538df07c410e4bfd6457adcb0b663a5e0df331905dbe135bcfd3f89ae57",  # scan: allow
    ),
    (
        "bottle",
        "0.13.4",
        "https://files.pythonhosted.org/packages/83/f6/"
        "b55ec74cfe68c6584163faa311503c20b0da4c09883a41e8e00d6726c954/"
        "bottle-0.13.4-py2.py3-none-any.whl",
        "045684fbd2764eac9cdeb824861d1551d113e8b683d8d26e296898d3dd99a12e",  # scan: allow
    ),
    (
        "typing_extensions",
        "4.16.0",
        "https://files.pythonhosted.org/packages/49/d3/"
        "b8441a820a491ddfc024b0b0cf0393375b75ea13866d9c66727e54c2fc80/"
        "typing_extensions-4.16.0-py3-none-any.whl",
        "481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8",  # scan: allow
    ),
    (
        "proxy_tools",
        "0.1.0",
        "https://files.pythonhosted.org/packages/f2/cf/"
        "77d3e19b7fabd03895caca7857ef51e4c409e0ca6b37ee6e9f7daa50b642/"
        "proxy_tools-0.1.0.tar.gz",
        "ccb3751f529c047e2d8a58440d86b205303cf0fe8146f784d1cbcd94f0a28010",  # scan: allow
    ),
)

# The Mach-O magic numbers, so a file is opened as one only when it is one.
MACHO_MAGICS = (0xFEEDFACE, 0xFEEDFACF, 0xCEFAEDFE, 0xCFFAEDFE, 0xCAFEBABE, 0xBEBAFECA)

WRAPPER = """#!/bin/sh
# The agent runs from the interpreter the package carries, never the system
# one; the window process it starts inherits the same one.
exec {python} -m neutrino_agent.cli.entry "$@"
"""

POSTINSTALL = """#!/bin/sh
set -e

# bootstrap is the modern pair of load; kickstart starts it now rather than
# at the next boot.
launchctl bootout system {plist} >/dev/null 2>&1 || true
launchctl bootstrap system {plist} >/dev/null 2>&1 || true
launchctl kickstart -k system/{label} >/dev/null 2>&1 || true

echo ""
echo "  Neutrino agent installed. Join a hub with:"
echo ""
echo "      sudo nagent connect <enrollment link>"
echo ""
exit 0
"""


def main() -> int:
    """Build the package.

    Returns:
        The process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", default="dist", help="where to write the .pkg")
    arguments = parser.parse_args()

    version = payload.version()
    output_dir = Path(arguments.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    # One file for both machines, named for what it is; this name is what the
    # hub fetches by.
    target = output_dir / f"{PACKAGE_NAME}-{version}-macos-universal2.pkg"

    for tool in ("pkgutil", "install_name_tool", "codesign", "pkgbuild"):
        if shutil.which(tool) is None:
            raise SystemExit(
                f"{tool} is needed to build the macOS package; it is macOS's"
            )

    with tempfile.TemporaryDirectory() as workdir:
        root = Path(workdir)
        staged = root / "staged"
        scripts = root / "scripts"
        _lay_out(staged, scripts, version)
        _build(staged, scripts, target, version)

    print(f"wrote {target} ({target.stat().st_size // 1024 // 1024} MiB)")
    return 0


def _lay_out(staged: Path, scripts: Path, version: str) -> None:
    """Write everything the package installs.

    Args:
        staged: The directory standing in for the filesystem root.
        scripts: Where the installer's own scripts go.
        version: The version being packaged.
    """
    framework = staged / str(DARWIN_FRAMEWORK_DIR).lstrip("/")
    _stage_framework(framework)
    home = staged / str(DARWIN_FRAMEWORK_HOME).lstrip("/")
    _trim_framework(home)
    _relocate(home)

    site_packages = home / "lib" / f"python{DARWIN_PYTHON_SERIES}" / "site-packages"
    payload.stage_agent_tree(site_packages, version)
    # The framework's own interpreter does the installing, so the wheels are
    # matched against the tags they will actually run under. python.org ships
    # pip as a separate component, which this package does not take.
    staged_python = home / "bin" / f"python{DARWIN_PYTHON_SERIES}"
    payload.run([str(staged_python), "-m", "ensurepip"])
    payload.stage_wheels(staged_python, site_packages, DARWIN_WHEELS)

    payload.write(
        staged / DARWIN_WRAPPER_PATH,
        WRAPPER.format(python=DARWIN_PYTHON),
        is_executable=True,
    )
    icons.write_icns(
        staged / str(payload.INSTALL_PREFIX).lstrip("/") / "neutrino_agent.icns"
    )
    payload.write(
        staged / str(DARWIN_AGENT_PLIST).lstrip("/"),
        plistlib.dumps(
            {
                "Label": DARWIN_AGENT_LABEL,
                "ProgramArguments": [f"/{DARWIN_WRAPPER_PATH}", "run"],
                "RunAtLoad": True,
                "KeepAlive": True,
                "ProcessType": "Background",
            }
        ).decode("utf-8"),
    )
    payload.write(
        scripts / "postinstall",
        POSTINSTALL.format(plist=DARWIN_AGENT_PLIST, label=DARWIN_AGENT_LABEL),
        is_executable=True,
    )


def _stage_framework(framework: Path) -> None:
    """Unpack python.org's framework into the tree.

    Args:
        framework: Where ``Python.framework`` belongs.

    Raises:
        SystemExit: When the installer is not what was pinned, or does not
            hold the component this expects.
    """
    with tempfile.TemporaryDirectory() as workdir:
        installer = Path(workdir) / "python.pkg"
        installer.write_bytes(
            payload.fetch(
                DARWIN_PYTHON_URL.format(version=DARWIN_PYTHON_VERSION),
                DARWIN_PYTHON_SHA256,
                "the interpreter",
            )
        )
        expanded = Path(workdir) / "expanded"
        payload.run(["pkgutil", "--expand-full", str(installer), str(expanded)])
        # The component's payload is the framework itself: its own root is
        # what /Library/Frameworks/Python.framework would be.
        unpacked = expanded / DARWIN_FRAMEWORK_COMPONENT / "Payload"
        if not (unpacked / "Versions" / DARWIN_PYTHON_SERIES).is_dir():
            raise SystemExit(
                f"{DARWIN_FRAMEWORK_COMPONENT} does not carry "
                f"Versions/{DARWIN_PYTHON_SERIES}"
            )
        framework.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(unpacked, framework, symlinks=True)


def _trim_framework(home: Path) -> None:
    """Take out of the framework what no package needs.

    Tkinter draws no window here — the shell embeds WKWebView — and its
    frameworks are the largest thing in the tree after the interpreter.

    Args:
        home: The framework version directory.
    """
    for path in (
        home / "Frameworks",
        home / "lib" / f"python{DARWIN_PYTHON_SERIES}" / "tkinter",
        home / "lib" / f"python{DARWIN_PYTHON_SERIES}" / "idlelib",
        home / "lib" / f"python{DARWIN_PYTHON_SERIES}" / "turtledemo",
    ):
        shutil.rmtree(path, ignore_errors=True)
    for pattern in ("_tkinter*.so", "*.pyc"):
        for path in home.rglob(pattern):
            path.unlink(missing_ok=True)
    for name in ("idle3", f"idle{DARWIN_PYTHON_SERIES}", "2to3"):
        (home / "bin" / name).unlink(missing_ok=True)


def _relocate(home: Path) -> None:
    """Point every Mach-O in the framework at where the package puts it.

    The framework names itself absolutely, so a copy anywhere else loads
    nothing until each name is rewritten. Rewriting invalidates the
    signature, which Apple Silicon will not run, so each rewritten file is
    signed again ad hoc.

    Args:
        home: The framework version directory.
    """
    for path in sorted(home.rglob("*")):
        if path.is_symlink() or not path.is_file() or not _is_macho(path):
            continue
        names = [
            name
            for name in _linked_names(path)
            if name.startswith(DARWIN_FRAMEWORK_ORIGIN)
        ]
        if not names:
            continue
        own = _own_name(path)
        command = ["install_name_tool"]
        if own.startswith(DARWIN_FRAMEWORK_ORIGIN):
            command += ["-id", _relocated(own)]
        for name in names:
            command += ["-change", name, _relocated(name)]
        payload.run(command + [str(path)])
        payload.run(["codesign", "--force", "--sign", "-", str(path)])


def _relocated(name: str) -> str:
    """One install name, moved from the framework's origin to this package's.

    Args:
        name: The absolute path the Mach-O carries.

    Returns:
        The same path under :data:`DARWIN_FRAMEWORK_HOME`.
    """
    return str(DARWIN_FRAMEWORK_HOME) + name[len(DARWIN_FRAMEWORK_ORIGIN) :]


def _is_macho(path: Path) -> bool:
    """Whether a file is a Mach-O object.

    Args:
        path: The file to look at.

    Returns:
        True when its first four bytes are a Mach-O or fat magic.
    """
    with open(path, "rb") as stream:
        head = stream.read(4)
    if len(head) < 4:
        return False
    return struct.unpack(">I", head)[0] in MACHO_MAGICS


def _linked_names(path: Path) -> list:
    """Every dynamic library one Mach-O names, its own included.

    Args:
        path: The Mach-O to read.

    Returns:
        The paths it carries, in the order otool prints them.
    """
    result = subprocess.run(
        ["otool", "-L", str(path)], capture_output=True, text=True, check=False
    )
    names = []
    for line in result.stdout.splitlines()[1:]:
        stripped = line.strip()
        if stripped.startswith("/") and " (compatibility" in stripped:
            names.append(stripped.split(" (compatibility")[0])
    return names


def _own_name(path: Path) -> str:
    """What a Mach-O calls itself, when it is a library.

    Args:
        path: The Mach-O to read.

    Returns:
        Its own install name, or empty for an executable.
    """
    result = subprocess.run(
        ["otool", "-D", str(path)], capture_output=True, text=True, check=False
    )
    lines = [line.strip() for line in result.stdout.splitlines()[1:] if line.strip()]
    return lines[0] if lines and lines[0].startswith("/") else ""


def _build(staged: Path, scripts: Path, target: Path, version: str) -> None:
    """Turn the staged tree into an installer.

    Args:
        staged: The directory standing in for the filesystem root.
        scripts: The installer's own scripts.
        target: Where the .pkg should land.
        version: The version being packaged.

    Raises:
        SystemExit: When the tools refuse.
    """
    payload.run(
        [
            "pkgbuild",
            "--root",
            str(staged),
            "--scripts",
            str(scripts),
            "--identifier",
            DARWIN_PACKAGE_IDENTIFIER,
            "--version",
            version,
            "--install-location",
            "/",
            str(target),
        ]
    )
    if not target.is_file():
        raise SystemExit(f"pkgbuild wrote no {target.name}")
    os.chmod(target, 0o644)


if __name__ == "__main__":
    raise SystemExit(main())
