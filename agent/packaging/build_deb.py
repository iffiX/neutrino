"""Build the agent's .deb.

    python3 agent/packaging/build_deb.py --output-dir dist/

The package is `Architecture: all`: the agent is pure standard library, so one
file covers x86-64, ARM64 and 32-bit ARM. Python itself comes from
`Depends: python3`, which is how apt is told to provide the runtime rather
than the package carrying one.

Not pure: writes a package tree and runs dpkg-deb.
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_NAME = "neutrino-agent"

# Debian's own location for a system-wide Python package, so
# `python3 -m neutrino_agent.cli` resolves with no PYTHONPATH.
SITE_DIR = "usr/lib/python3/dist-packages"

# The oldest Python the agent is written against; older Raspbian ships 3.9.
MINIMUM_PYTHON = "3.9"

CONTROL = """Package: {name}
Version: {version}
Section: admin
Priority: optional
Architecture: all
Depends: python3 (>= {python}), systemd, cifs-utils, openssh-server
Maintainer: {maintainer}
Description: Neutrino device agent
 Keeps a managed machine's modules in the state its Neutrino Hub asks for:
 installs and removes software from the hub's catalog, reports metrics, and
 offers a small local page for joining a hub.
 .
 Pure standard library, so it runs on whatever Python the machine already has.
"""

POSTINST = """#!/bin/sh
set -e

# An agent installed by the old shell script leaves a unit in
# /etc/systemd/system, which takes precedence over this package's. Left in
# place it would keep starting the copy under /opt, and the hub would go on
# seeing the version that copy reports.
if [ -f /etc/systemd/system/neutrino_agent.service ] || [ -d /opt/neutrino_agent ]; then
    echo "  Removing the tarball-era agent, which this package replaces."
    systemctl stop neutrino_agent.service >/dev/null 2>&1 || true
    rm -f /etc/systemd/system/neutrino_agent.service
    rm -rf /opt/neutrino_agent /etc/neutrino_agent
fi

systemctl daemon-reload || true

# The agent runs from install: unbound it idles waiting for a link, and its
# control channel answers nagent ui. A service that only starts after a
# connect is a heartbeat counter that never accumulates.
systemctl enable --now neutrino_agent.service >/dev/null 2>&1 || true

if [ -d /usr/share/icons/hicolor ]; then
    gtk-update-icon-cache -f /usr/share/icons/hicolor >/dev/null 2>&1 || true
fi
update-desktop-database /usr/share/applications >/dev/null 2>&1 || true

echo ""
echo "  Neutrino agent installed. Join a hub with:"
echo ""
echo "      sudo nagent connect <enrollment link>"
echo ""
"""

PRERM = """#!/bin/sh
set -e

if [ "$1" = remove ] || [ "$1" = deconfigure ]; then
    if [ "$1" = remove ]; then
        # Removal is this machine leaving: the hub is told, so its panel
        # stops showing the device as managed. Best-effort — an unreachable
        # hub does not block the removal.
        nagent disconnect >/dev/null 2>&1 || true
    fi
    systemctl stop neutrino_agent.service >/dev/null 2>&1 || true
    systemctl disable neutrino_agent.service >/dev/null 2>&1 || true
fi
"""

POSTRM = """#!/bin/sh
set -e

systemctl daemon-reload >/dev/null 2>&1 || true

if [ "$1" = purge ]; then
    rm -rf /etc/neutrino_agent
fi
"""

WRAPPER = """#!/bin/sh
# The agent is a system-wide Python package; this only names the entry point.
exec /usr/bin/python3 -m neutrino_agent.cli.entry "$@"
"""


def main() -> int:
    """Build the package.

    Returns:
        The process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", default="dist", help="where to write the .deb")
    parser.add_argument(
        "--maintainer",
        default="iffiX <muhanli2022@u.northwestern.edu>",
        help="the Maintainer field",
    )
    arguments = parser.parse_args()

    version = _version()
    output_dir = Path(arguments.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as workdir:
        tree = Path(workdir) / f"{PACKAGE_NAME}_{version}_all"
        _lay_out(tree, version, arguments.maintainer)
        target = output_dir / f"{PACKAGE_NAME}_{version}_all.deb"
        _build(tree, target)

    print(f"wrote {target} ({target.stat().st_size // 1024} KiB)")
    return 0


def _lay_out(tree: Path, version: str, maintainer: str) -> None:
    """Write the whole package tree.

    Args:
        tree: The directory to build under.
        version: The version being packaged.
        maintainer: The Maintainer field's value.
    """
    package_dir = tree / SITE_DIR / "neutrino_agent"
    shutil.copytree(
        AGENT_ROOT / "neutrino_agent",
        package_dir,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    # dpkg installs no .dist-info, so importlib.metadata cannot answer for a
    # packaged agent. The version is stamped into the tree instead, and the
    # hub compares it against its own.
    (package_dir / "_version.py").write_text(
        f'"""Written by the packaging build. Do not edit."""\n\n'
        f'AGENT_VERSION = "{version}"\n',
        encoding="utf-8",
    )

    # Whatever umask the build ran under does not belong in a package.
    for path in package_dir.rglob("*"):
        path.chmod(0o755 if path.is_dir() else 0o644)

    _write(tree / "usr/bin/nagent", WRAPPER, is_executable=True)
    _write(
        tree / "lib/systemd/system/neutrino_agent.service",
        (AGENT_ROOT / "neutrino_agent/data/systemd/neutrino_agent.service").read_text(
            encoding="utf-8"
        ),
    )

    desktop = AGENT_ROOT / "neutrino_agent/data/desktop"
    _write(
        tree / "usr/share/applications/neutrino_agent.desktop",
        (desktop / "neutrino_agent.desktop").read_text(encoding="utf-8"),
    )
    for source, edge in (("neutrino_agent.png", 256), ("neutrino_agent_48.png", 48)):
        destination = (
            tree / f"usr/share/icons/hicolor/{edge}x{edge}/apps/neutrino_agent.png"
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(desktop / source, destination)

    control = CONTROL.format(
        name=PACKAGE_NAME,
        version=version,
        python=MINIMUM_PYTHON,
        maintainer=maintainer,
    )
    _write(tree / "DEBIAN/control", control)
    _write(tree / "DEBIAN/postinst", POSTINST, is_executable=True)
    _write(tree / "DEBIAN/prerm", PRERM, is_executable=True)
    _write(tree / "DEBIAN/postrm", POSTRM, is_executable=True)


def _build(tree: Path, target: Path) -> None:
    """Run dpkg-deb over a laid-out tree.

    Args:
        tree: The package tree.
        target: Where to write the .deb.

    Raises:
        SystemExit: If dpkg-deb refuses.
    """
    # --root-owner-group makes every file root:root without fakeroot, which
    # keeps the build runnable as an ordinary user and in CI.
    result = subprocess.run(
        ["dpkg-deb", "--root-owner-group", "--build", str(tree), str(target)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit((result.stderr or result.stdout).strip())


def _version() -> str:
    """The version declared in the agent's pyproject."""
    for line in (
        (AGENT_ROOT / "pyproject.toml").read_text(encoding="utf-8").splitlines()
    ):
        if line.startswith("version = "):
            return line.split('"')[1]
    raise SystemExit("no version in agent/pyproject.toml")


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
