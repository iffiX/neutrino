"""Building a macOS ``.pkg`` from a package root.

The caller lays out a directory standing in for the filesystem root, adds
launchd jobs and install scripts to it through the helpers here, signs what
it compiled, reads every Mach-O file of it back with
:func:`require_system_links`, and :func:`build` wraps the root with
``pkgbuild`` and the component with ``productbuild``.

Needs the Xcode command line tools for ``codesign``, ``otool``,
``pkgbuild`` and ``productbuild``.

Not pure: signs, reads files with otool, writes package trees, runs
pkgbuild and productbuild.
"""

# PEP 604 unions below are annotations only; the agent's tests import this on
# the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import plistlib
import shutil
import subprocess
from pathlib import Path

# Where launchd reads system daemons and per-session agents from.
LAUNCH_DAEMONS_DIR = "Library/LaunchDaemons"
LAUNCH_AGENTS_DIR = "Library/LaunchAgents"

# The first bytes of every Mach-O file, thin or universal, either order.
MACH_O_MAGICS = (
    b"\xcf\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
    b"\xca\xfe\xba\xbe",
    b"\xbe\xba\xfe\xca",
)
# Where a load reference of a carried file may point: the system's own
# libraries, or the carried tree itself through the loader's own prefixes.
# A Homebrew or MacPorts prefix, or a bare name, loads on the machine that
# built the package and on no other.
SYSTEM_LINK_PREFIXES = (
    "/usr/lib/",
    "/System/Library/",
    "@rpath/",
    "@loader_path/",
    "@executable_path/",
)


def write_launchd_plist(
    package_root: Path,
    *,
    label: str,
    program_arguments: list,
    is_agent: bool = False,
    log_path: str = "",
    extra: dict | None = None,
) -> Path:
    """Write one launchd job into the package root, started at load and
    kept alive.

    Args:
        package_root: The directory standing in for the filesystem root.
        label: The job's label, which is also the file's name.
        program_arguments: The command the job runs.
        is_agent: Whether it is a per-session LaunchAgent rather than a
            system LaunchDaemon.
        log_path: Where its standard output and error go; empty leaves
            them unset.
        extra: Further keys, which override the defaults.

    Returns:
        The plist written.
    """
    job = {
        "Label": label,
        "ProgramArguments": list(program_arguments),
        "RunAtLoad": True,
        "KeepAlive": True,
    }
    if log_path:
        job["StandardOutPath"] = log_path
        job["StandardErrorPath"] = log_path
    job.update(extra or {})
    directory = package_root / (LAUNCH_AGENTS_DIR if is_agent else LAUNCH_DAEMONS_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{label}.plist"
    target.write_bytes(plistlib.dumps(job))
    target.chmod(0o644)
    return target


def write_scripts(
    scripts_dir: Path, *, preinstall: str = "", postinstall: str = ""
) -> Path:
    """Write the install scripts ``pkgbuild --scripts`` takes.

    Args:
        scripts_dir: The directory to write them into.
        preinstall: The shell script run before the files land; empty
            writes none.
        postinstall: The shell script run after; empty writes none.

    Returns:
        The directory.
    """
    scripts_dir.mkdir(parents=True, exist_ok=True)
    for name, text in (("preinstall", preinstall), ("postinstall", postinstall)):
        if text:
            script = scripts_dir / name
            script.write_text(text, encoding="utf-8")
            script.chmod(0o755)
    return scripts_dir


def sign_ad_hoc(path: Path) -> None:
    """Sign a bundle or a binary ad hoc, every binary inside it included.

    Args:
        path: What to sign.

    Raises:
        SystemExit: When codesign refuses.
    """
    _run(["codesign", "--force", "--deep", "--sign", "-", str(path)])


def is_mach_o(path: Path) -> bool:
    """Whether a file is a Mach-O binary, thin or universal.

    Args:
        path: The file.

    Returns:
        True when its first bytes are a Mach-O magic.

    Raises:
        OSError: When the file cannot be read.
    """
    with open(path, "rb") as stream:
        return stream.read(4) in MACH_O_MAGICS


def foreign_links(listing: str, install_names: str = "") -> list:
    """The load references of one file that point outside the system and
    the carried tree.

    Args:
        listing: ``otool -L`` output for the file: a line naming the file,
            one per architecture for a universal file, each followed by one
            indented reference per line with its versions in brackets.
        install_names: ``otool -D`` output for the same file. A library's
            own name is listed by ``otool -L`` among its references and is
            no load.

    Returns:
        Each reference outside :data:`SYSTEM_LINK_PREFIXES`, once, in the
        order listed.
    """
    own = {
        line.strip()
        for line in install_names.splitlines()
        if line.strip() and not line.rstrip().endswith(":")
    }
    found = []
    for line in listing.splitlines():
        if not line.strip() or not line[0].isspace():
            continue
        reference = line.strip()
        if reference.endswith(")") and " (" in reference:
            reference = reference.rpartition(" (")[0]
        if reference in own or reference.startswith(SYSTEM_LINK_PREFIXES):
            continue
        if reference not in found:
            found.append(reference)
    return found


def require_system_links(directory: Path) -> None:
    """Refuse a tree any of whose Mach-O files loads a library from outside
    the system and the tree.

    Args:
        directory: The finished tree.

    Raises:
        SystemExit: When otool refuses a file, or any file has a reference
            :func:`foreign_links` returns; the message names each file and
            reference.
    """
    refused = []
    for path in sorted(directory.rglob("*")):
        if path.is_symlink() or not path.is_file() or not is_mach_o(path):
            continue
        listing = _read(["otool", "-L", str(path)])
        install_names = _read(["otool", "-D", str(path)])
        for reference in foreign_links(listing, install_names):
            refused.append(f"{path.relative_to(directory)}: {reference}")
    if refused:
        raise SystemExit(
            f"Mach-O files under {directory} load libraries from outside the "
            "system:\n" + "\n".join(refused)
        )


def build(
    package_root: Path,
    target: Path,
    *,
    identifier: str,
    version: str,
    scripts_dir: Path | None = None,
) -> None:
    """Run pkgbuild over the package root, then productbuild around it.

    Args:
        package_root: The directory standing in for the filesystem root.
        target: Where the .pkg should land.
        identifier: The identity the installer records the package under.
        version: The version the package declares.
        scripts_dir: What :func:`write_scripts` wrote, when the package
            runs any.

    Raises:
        SystemExit: When the tools are not installed, or refuse.
    """
    for tool in ("pkgbuild", "productbuild"):
        if shutil.which(tool) is None:
            raise SystemExit(
                f"{tool} is needed to build a macOS installer: xcode-select --install"
            )
    component = target.parent / f"{identifier}.component.pkg"
    command = [
        "pkgbuild",
        "--root",
        str(package_root),
        "--identifier",
        identifier,
        "--version",
        version,
    ]
    if scripts_dir is not None:
        command += ["--scripts", str(scripts_dir)]
    _run(command + ["--install-location", "/", str(component)])
    try:
        _run(["productbuild", "--package", str(component), str(target)])
    finally:
        component.unlink(missing_ok=True)


def _run(command: list) -> None:
    """Run one build step, failing loudly.

    Args:
        command: The argument vector.

    Raises:
        SystemExit: If the command fails.
    """
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(
            f"{' '.join(command[:3])} failed:\n"
            f"{(result.stderr or result.stdout).strip()}"
        )


def _read(command: list) -> str:
    """Run one tool that only reads, and return what it printed.

    Args:
        command: The argument vector.

    Returns:
        Its standard output.

    Raises:
        SystemExit: If the command fails.
    """
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(
            f"{' '.join(command)} failed:\n"
            f"{(result.stderr or result.stdout).strip()}"
        )
    return result.stdout
