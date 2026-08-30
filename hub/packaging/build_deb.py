"""Build the hub's .deb.

    python3 hub/packaging/build_deb.py --output-dir dist/

The package carries its own virtual environment under /opt/neutrino/venv and
touches nothing the system installed: the hub needs thirty packages including
FastAPI and asyncssh, and pinning a system Python to them is what
`EXTERNALLY-MANAGED` exists to prevent.

Build it on the distribution it is for, in a container. Two things bind the
package to its build environment: compiled wheels (cryptography, uvloop) fix
the architecture, and the virtual environment carries no standard library, so
the target needs the exact interpreter version the build used. Debian 12 gives
python3.11 and a glibc 2.36 baseline:

    podman run --rm --network=host -v "$PWD:/src:ro" -v "$PWD/dist:/out" \
        debian:12 sh -c 'apt-get -qq update && apt-get -qq install -y \
        python3 python3-venv python3-pip dpkg-dev && cp -r /src /build && \
        cd /build && python3 hub/packaging/build_deb.py --output-dir /out'

Not pure: creates a virtual environment, installs into it, runs dpkg-deb.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HUB_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_NAME = "neutrino-hub"

# Where the package's own environment lives, and the path its interpreter is
# addressed by. The venv is built at this path so nothing inside it has to be
# rewritten afterwards.
INSTALL_PREFIX = Path("/opt/neutrino")
VENV_DIR = INSTALL_PREFIX / "venv"

CONTROL = """Package: {name}
Version: {version}
Section: admin
Priority: optional
Architecture: {architecture}
Depends: {python_package}, systemd, nftables, dnsmasq, iproute2
Recommends: arp-scan, vnstat
Maintainer: {maintainer}
Installed-Size: {size}
Description: Neutrino Hub, a personal developer infrastructure hub
 Transparent proxy routing, LAN device management, an AI gateway and a web
 control panel, on one box. Carries its own Python environment.
"""

POSTINST = """#!/bin/sh
set -e

install -d -m 755 /etc/neutrino
install -d -m 700 /etc/neutrino/config
install -d -m 755 /etc/neutrino/generated
install -d -m 755 /var/log/neutrino

systemctl daemon-reload || true

echo ""
echo "  Neutrino Hub installed. Set it up with:"
echo ""
echo "      sudo nhub install"
echo ""
"""

PRERM = """#!/bin/sh
set -e

if [ "$1" = remove ] || [ "$1" = deconfigure ]; then
    for unit in neutrino_web neutrino_router neutrino_cliproxy; do
        systemctl stop "${unit}.service" >/dev/null 2>&1 || true
        systemctl disable "${unit}.service" >/dev/null 2>&1 || true
    done
fi
"""

POSTRM = """#!/bin/sh
set -e

systemctl daemon-reload >/dev/null 2>&1 || true

if [ "$1" = purge ]; then
    echo "  Leaving /etc/neutrino/config in place; remove it by hand if you"
    echo "  no longer need the node credentials and device keys it holds."
fi
"""

WRAPPER = """#!/bin/sh
# The hub runs from its own environment, never the system interpreter.
exec {venv}/bin/python -m neutrino_hub.cli.entry "$@"
"""


def main() -> int:
    """Build the package.

    Returns:
        The process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", default="dist", help="where to write the .deb")
    parser.add_argument(
        "--architecture",
        default=_host_architecture(),
        help="the Architecture field; must match the machine building it",
    )
    parser.add_argument(
        "--maintainer",
        default="iffiX <muhanli2022@u.northwestern.edu>",
        help="the Maintainer field",
    )
    arguments = parser.parse_args()

    _require_built_frontend()
    version = _version()
    output_dir = Path(arguments.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as workdir:
        tree = Path(workdir) / f"{PACKAGE_NAME}_{version}_{arguments.architecture}"
        _build_venv(tree, version)
        _lay_out(tree, version, arguments.architecture, arguments.maintainer)
        target = output_dir / f"{PACKAGE_NAME}_{version}_{arguments.architecture}.deb"
        _build(tree, target)

    print(f"wrote {target} ({target.stat().st_size // 1024 // 1024} MiB)")
    return 0


def _build_venv(tree: Path, version: str) -> None:
    """Create the environment the package ships and install the hub into it.

    The venv is created under the staging tree at the same relative path it
    will occupy once installed, and the interpreter inside it is a copy rather
    than a symlink, so the package does not depend on the build machine's
    Python staying where it was.

    Args:
        tree: The staging directory.
        version: The version being packaged, stamped into the tree.

    Raises:
        SystemExit: If the environment cannot be built.
    """
    staged_venv = tree / str(VENV_DIR).lstrip("/")
    staged_venv.parent.mkdir(parents=True, exist_ok=True)
    _run([sys.executable, "-m", "venv", "--copies", str(staged_venv)])

    # dpkg installs no .dist-info for the hub itself, so the version is
    # stamped in the same way the agent's build does it.
    stamp = HUB_ROOT / "neutrino_hub" / "_version.py"
    stamp.write_text(
        '"""Written by the packaging build. Do not edit."""\n\n'
        f'HUB_VERSION = "{version}"\n',
        encoding="utf-8",
    )
    try:
        _run(
            [
                str(staged_venv / "bin" / "pip"),
                "install",
                "--quiet",
                "--no-compile",
                str(HUB_ROOT),
            ]
        )
    finally:
        stamp.unlink(missing_ok=True)

    _strip_build_paths(staged_venv, tree)


def _strip_build_paths(staged_venv: Path, tree: Path) -> None:
    """Point everything inside the environment at its installed location.

    pip writes the staging path into console scripts and into pyvenv.cfg. Left
    alone, every one of them would name a directory that exists only on the
    build machine.

    Args:
        staged_venv: The environment as staged.
        tree: The staging root, which is the prefix to remove.
    """
    staged_prefix = str(tree)
    for path in staged_venv.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if staged_prefix not in text:
            continue
        path.write_text(text.replace(staged_prefix, ""), encoding="utf-8")

    # pip, setuptools and the activate scripts are not what the package runs.
    for name in ("activate", "activate.csh", "activate.fish", "Activate.ps1"):
        (staged_venv / "bin" / name).unlink(missing_ok=True)


def _lay_out(tree: Path, version: str, architecture: str, maintainer: str) -> None:
    """Write everything outside the environment.

    Args:
        tree: The staging directory.
        version: The version being packaged.
        architecture: The Architecture field's value.
        maintainer: The Maintainer field's value.
    """
    _write(
        tree / "usr/bin/nhub",
        WRAPPER.format(venv=VENV_DIR),
        is_executable=True,
    )

    # Unit files are rendered at install time by `nhub install`, which knows
    # the paths; what ships here is the panel's own unit, already absolute.
    services = HUB_ROOT / "neutrino_hub" / "data" / "services"
    unit = (services / "neutrino_web.service").read_text(encoding="utf-8")
    unit = (
        unit.replace("WorkingDirectory=@REPO_ROOT@/hub\n", "")
        .replace("Environment=PYTHONPATH=@REPO_ROOT@/hub\n", "")
        .replace("@PYTHON@", f"{VENV_DIR}/bin/python")
        .replace(
            "Documentation=file://@REPO_ROOT@/docs/standard/misc/config.md",
            "Documentation=https://github.com/iffiX/neutrino",
        )
    )
    _write(tree / "lib/systemd/system/neutrino_web.service", unit)

    size = sum(f.stat().st_size for f in tree.rglob("*") if f.is_file()) // 1024
    control = CONTROL.format(
        name=PACKAGE_NAME,
        version=version,
        architecture=architecture,
        maintainer=maintainer,
        size=size,
        python_package=_python_package(),
    )
    _write(tree / "DEBIAN/control", control)
    _write(tree / "DEBIAN/postinst", POSTINST, is_executable=True)
    _write(tree / "DEBIAN/prerm", PRERM, is_executable=True)
    _write(tree / "DEBIAN/postrm", POSTRM, is_executable=True)


def _python_package() -> str:
    """The interpreter this package will need, as a Debian dependency.

    A virtual environment copies the interpreter binary but not the standard
    library, so the machine installing this has to have the very version it
    was built against. `python3 (>= 3.11)` would be satisfied by 3.12 and then
    fail at run time with "could not find platform independent libraries".

    Returns:
        Something like ``python3.11``.
    """
    return f"python{sys.version_info.major}.{sys.version_info.minor}"


def _require_built_frontend() -> None:
    """Refuse to package a hub with no panel in it.

    Raises:
        SystemExit: When the frontend has not been built.
    """
    index = HUB_ROOT / "neutrino_hub" / "data" / "frontend" / "index.html"
    if not index.exists():
        raise SystemExit(
            "the panel has not been built; run `npm run build` in hub/frontend first"
        )


def _build(tree: Path, target: Path) -> None:
    """Run dpkg-deb over a laid-out tree.

    Args:
        tree: The package tree.
        target: Where to write the .deb.
    """
    _run(["dpkg-deb", "--root-owner-group", "--build", str(tree), str(target)])


def _host_architecture() -> str:
    """The Debian architecture name for the machine running this."""
    result = subprocess.run(
        ["dpkg", "--print-architecture"], capture_output=True, text=True
    )
    return result.stdout.strip() or "amd64"


def _version() -> str:
    """The version declared in the hub's pyproject."""
    for line in (HUB_ROOT / "pyproject.toml").read_text(encoding="utf-8").splitlines():
        if line.startswith("version = "):
            return line.split('"')[1]
    raise SystemExit("no version in hub/pyproject.toml")


def _run(command: list) -> None:
    """Run a build step, failing loudly.

    Args:
        command: The argument vector.

    Raises:
        SystemExit: If the command fails.
    """
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(
            f"{' '.join(command[:3])} failed:\n{(result.stderr or result.stdout).strip()}"
        )


def _write(path: Path, text: str, *, is_executable: bool = False) -> None:
    """Write one file into the tree, creating its parents.

    Args:
        path: Where to write.
        text: What to write.
        is_executable: Whether to mark it 0755.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755 if is_executable else 0o644)


if __name__ == "__main__":
    sys.exit(main())
