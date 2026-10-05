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
import re
import shutil
import subprocess
from pathlib import Path
from xml.sax.saxutils import escape

# The distribution's root element, which the title goes inside.
PKG_DISTRIBUTION_ROOT = re.compile(r"<installer-gui-script\b[^>]*>")

# Where launchd reads system daemons and per-session agents from.
LAUNCH_DAEMONS_DIR = "Library/LaunchDaemons"
LAUNCHD_LANG = "en_US.UTF-8"
LAUNCH_AGENTS_DIR = "Library/LaunchAgents"

# The shell function a postinstall starts one LaunchDaemon with:
# ``start_daemon <label> <plist>``. launchd still holds a label for about a
# second after ``bootout`` returns, and answers a ``bootstrap`` of it, or of
# a label that is loaded, with "5: Input/output error". So it waits until
# the label is gone, at most 30 seconds, then bootstraps up to five times
# two seconds apart, and returns the last try's status.
LAUNCHD_START_FUNCTION = """start_daemon() {
    waited=0
    while launchctl print "system/$1" >/dev/null 2>&1; do
        waited=$((waited + 1))
        [ "$waited" -ge 60 ] && break
        sleep 0.5
    done
    tries=1
    while [ "$tries" -lt 5 ]; do
        launchctl bootstrap system "$2" && return 0
        tries=$((tries + 1))
        sleep 2
    done
    launchctl bootstrap system "$2"
}
"""

# What every bundle in a payload is marked with in the component property
# list. Installer moves a relocatable bundle to wherever a bundle of the same
# identifier already lies, as it moved the agent's RustDesk.app into the
# client's app; one whose version is checked is skipped when the installed
# copy is newer or equal. Every top bundle goes where the payload puts it
# and replaces what is there; a bundle inside one, which pkgbuild lists with
# its path and an empty overwrite action alone, is only kept from moving.
PINNED_BUNDLE = {
    "BundleIsRelocatable": False,
    "BundleIsVersionChecked": False,
    "BundleHasStrictIdentifier": True,
    "BundleOverwriteAction": "upgrade",
}
PINNED_CHILD_BUNDLE = {"BundleIsRelocatable": False}

# The shell function an install script asks who is at the screen with:
# ``console_user`` prints the account, or nothing for nobody. It reads the
# system configuration's console user through scutil, and the owner of
# /dev/console only where scutil cannot be run; under auto-login that owner
# stays root while a person is signed in. The login window, root and no
# name are nobody.
CONSOLE_USER_FUNCTION = """console_user() {
    if [ -x /usr/sbin/scutil ]; then
        name=$(printf 'show State:/Users/ConsoleUser\\n' | /usr/sbin/scutil |
            awk '$1 == "Name" && $2 == ":" { print $3; exit }')
    else
        name=$(stat -f %Su /dev/console)
    fi
    case "$name" in
    "" | root | loginwindow) ;;
    *) echo "$name" ;;
    esac
}
"""

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
    """Write one launchd job into the package root, started at load, kept
    alive and given a UTF-8 locale.

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
        # launchd starts a job with no locale, under which Python decodes
        # command output as ASCII and a curly quote in it is an error.
        "EnvironmentVariables": {"LANG": LAUNCHD_LANG},
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
    min_os_version: str = "",
    title: str = "",
) -> None:
    """Run pkgbuild over the package root, then productbuild around it.

    With a title, productbuild first writes the distribution it would build
    from, the title goes into it, and the package is built from that, so
    ``installer`` names the package by it.

    Args:
        package_root: The directory standing in for the filesystem root.
        target: Where the .pkg should land.
        identifier: The identity the installer records the package under.
        version: The version the package declares.
        scripts_dir: What :func:`write_scripts` wrote, when the package
            runs any.
        min_os_version: The oldest macOS the package installs on; given, the
            payload takes the strongest compression that version reads.
        title: The name ``installer`` shows for the package.

    Raises:
        SystemExit: When the tools are not installed, or refuse.
    """
    for tool in ("pkgbuild", "productbuild"):
        if shutil.which(tool) is None:
            raise SystemExit(
                f"{tool} is needed to build a macOS installer: xcode-select --install"
            )
    component = target.parent / f"{identifier}.component.pkg"
    component_plist = target.parent / f"{identifier}.component.plist"
    write_component_plist(package_root, component_plist)
    command = [
        "pkgbuild",
        "--root",
        str(package_root),
        "--identifier",
        identifier,
        "--version",
        version,
        "--component-plist",
        str(component_plist),
    ]
    if scripts_dir is not None:
        command += ["--scripts", str(scripts_dir)]
    if min_os_version:
        command += ["--compression", "latest", "--min-os-version", min_os_version]
    _run(command + ["--install-location", "/", str(component)])
    distribution = target.parent / f"{identifier}.distribution.xml"
    try:
        if title and _write_titled_distribution(component, distribution, title):
            _run(
                [
                    "productbuild",
                    "--distribution",
                    str(distribution),
                    "--package-path",
                    str(component.parent),
                    str(target),
                ]
            )
        else:
            _run(["productbuild", "--package", str(component), str(target)])
    finally:
        component.unlink(missing_ok=True)
        component_plist.unlink(missing_ok=True)
        distribution.unlink(missing_ok=True)


def _write_titled_distribution(component: Path, distribution: Path, title: str) -> bool:
    """Write the distribution productbuild would build a component into,
    with a title.

    Args:
        component: The component package.
        distribution: Where the distribution goes.
        title: The title.

    Returns:
        False when the distribution has no root element to put the title
        under, so the package is built from the component as it is.

    Raises:
        SystemExit: When productbuild refuses.
    """
    _run(
        ["productbuild", "--synthesize", "--package", str(component), str(distribution)]
    )
    text = distribution.read_text(encoding="utf-8")
    titled = PKG_DISTRIBUTION_ROOT.sub(
        lambda found: f"{found.group(0)}\n    <title>{escape(title)}</title>",
        text,
        count=1,
    )
    if titled == text:
        print(f"  {distribution.name} has no root element; the package goes untitled")
        return False
    distribution.write_text(titled, encoding="utf-8")
    return True


def write_component_plist(package_root: Path, path: Path) -> Path:
    """Write the component property list with every bundle pinned.

    ``pkgbuild --analyze`` lists the bundles the root holds; each is given
    :data:`PINNED_BUNDLE`, and each bundle inside one
    :data:`PINNED_CHILD_BUNDLE`.

    Args:
        package_root: The directory standing in for the filesystem root.
        path: Where the property list goes.

    Returns:
        The path written.

    Raises:
        SystemExit: When pkgbuild refuses.
    """
    _run(["pkgbuild", "--analyze", "--root", str(package_root), str(path)])
    with path.open("rb") as stream:
        bundles = plistlib.load(stream)
    with path.open("wb") as stream:
        plistlib.dump(pin_bundles(bundles), stream)
    return path


def pin_bundles(bundles: list, *, pinned_keys: dict = PINNED_BUNDLE) -> list:
    """Every bundle of an analyzed component list, pinned. Pure.

    Args:
        bundles: What ``pkgbuild --analyze`` wrote: one dict per bundle,
            with the bundles inside it under ``ChildBundles``.
        pinned_keys: What each entry at this level is given.

    Returns:
        The same entries with ``pinned_keys`` set on each, and
        :data:`PINNED_CHILD_BUNDLE` on every bundle inside one.
    """
    pinned = []
    for bundle in bundles:
        entry = dict(bundle, **pinned_keys)
        if bundle.get("ChildBundles"):
            entry["ChildBundles"] = pin_bundles(
                bundle["ChildBundles"], pinned_keys=PINNED_CHILD_BUNDLE
            )
        pinned.append(entry)
    return pinned


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
