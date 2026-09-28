"""Building a macOS ``.pkg`` from a package root.

The caller lays out a directory standing in for the filesystem root, adds
launchd jobs and install scripts to it through the helpers here, signs what
it compiled, and :func:`build` wraps the root with ``pkgbuild`` and the
component with ``productbuild``.

Needs the Xcode command line tools for ``codesign``, ``pkgbuild`` and
``productbuild``.

Not pure: signs, writes package trees, runs pkgbuild and productbuild.
"""

import plistlib
import shutil
import subprocess
from pathlib import Path

# Where launchd reads system daemons and per-session agents from.
LAUNCH_DAEMONS_DIR = "Library/LaunchDaemons"
LAUNCH_AGENTS_DIR = "Library/LaunchAgents"


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
