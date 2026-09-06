"""Build the agent's .deb.

    python3 agent/packaging/build_deb.py --output-dir dist/ --architecture amd64

The package carries its own interpreter under /opt/neutrino_agent and the
window's bindings built beside it, so it names no Python at all. That fixes it
to one architecture: build it in a container of the machine it is for, the way
the hub's package is built.

Needs the development headers the window's bindings compile against; the build
refuses by name when the container has none.

Not pure: writes a package tree and runs dpkg-deb.
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import payload  # noqa: E402
from gui_assets import ICONS_DIR  # noqa: E402

AGENT_ROOT = payload.AGENT_ROOT
PACKAGE_NAME = payload.PACKAGE_NAME

# The C stack the window loads through its own bindings, and nothing else.
# `gir1.2-webkit2-4.1` pulls the GTK and WebKit typelibs with it; the
# introspection library is named as well, because which package pulls that one
# has moved between releases.
RUNTIME_DEPENDENCIES = ("gir1.2-webkit2-4.1", "libgirepository-1.0-1", "systemd")

CONTROL = """Package: {name}
Version: {version}
Section: admin
Priority: optional
Architecture: {architecture}
Depends: {depends}
Recommends: cifs-utils, openssh-server
Maintainer: {maintainer}
Description: Neutrino device agent
 Keeps a managed machine's modules in the state its Neutrino Hub asks for:
 installs and removes software from the hub's catalog, reports metrics, and
 offers a window for joining a hub and choosing what this machine runs.
 .
 Carries its own interpreter and the window's bindings, so it installs on a
 machine with no Python and touches none the machine already has.
"""

POSTINST = """#!/bin/sh
set -e

systemctl daemon-reload || true

# The agent runs from install: unbound it idles waiting for a link, and its
# control channel answers nagent gui. A service that only starts after a
# connect is a heartbeat counter that never accumulates. An upgrade must
# RESTART it — enable --now on a running unit is a no-op, and the whole
# self-update path ends here: without the restart the new code lies on
# disk while the old process goes on beating.
if [ "$1" = configure ] && [ -n "$2" ]; then
    systemctl try-restart neutrino_agent.service >/dev/null 2>&1 || true
fi
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

# What dpkg leaves once its own files are gone: the bytecode the interpreter
# wrote beside them.
if [ "$1" = remove ] || [ "$1" = purge ]; then
    rm -rf {prefix}
fi

if [ "$1" = purge ]; then
    rm -rf /etc/neutrino/agent
    rmdir /etc/neutrino 2>/dev/null || true
fi
"""

WRAPPER = """#!/bin/sh
# The agent runs from the interpreter the package carries, never the system
# one; the window process it starts inherits the same one.
exec {python}/bin/python3 -m neutrino_agent.cli.entry "$@"
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
        help="the architecture to build for",
    )
    parser.add_argument(
        "--maintainer",
        default="iffiX <muhanli2022@u.northwestern.edu>",
        help="the Maintainer field",
    )
    arguments = parser.parse_args()

    version = payload.version()
    architecture = payload.DEBIAN_ARCHITECTURES[
        payload.machine_name(arguments.architecture)
    ]
    output_dir = Path(arguments.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as workdir:
        tree = Path(workdir) / f"{PACKAGE_NAME}_{version}_{architecture}"
        _lay_out(tree, version, architecture, arguments.maintainer)
        target = output_dir / f"{PACKAGE_NAME}_{version}_{architecture}.deb"
        _build(tree, target)

    print(f"wrote {target} ({target.stat().st_size // 1024 // 1024} MiB)")
    return 0


def _lay_out(tree: Path, version: str, architecture: str, maintainer: str) -> None:
    """Write the whole package tree.

    Args:
        tree: The directory to build under.
        version: The version being packaged.
        architecture: The Debian architecture name.
        maintainer: The Maintainer field's value.
    """
    staged_python = tree / str(payload.PYTHON_DIR).lstrip("/")
    payload.stage_linux_interpreter(staged_python, architecture)
    payload.stage_agent_tree(payload.site_packages_of(staged_python), version)
    payload.stage_linux_gui_bindings(staged_python)
    payload.strip_build_paths(staged_python, tree)

    payload.write(
        tree / "usr/bin/nagent",
        WRAPPER.format(python=payload.PYTHON_DIR),
        is_executable=True,
    )
    payload.write(
        tree / "lib/systemd/system/neutrino_agent.service",
        (AGENT_ROOT / "neutrino_agent/data/systemd/neutrino_agent.service").read_text(
            encoding="utf-8"
        ),
    )

    desktop = AGENT_ROOT / "neutrino_agent/data/desktop"
    payload.write(
        tree / "usr/share/applications/neutrino_agent.desktop",
        (desktop / "neutrino_agent.desktop").read_text(encoding="utf-8"),
    )
    for source, edge in (("neutrino_256.png", 256), ("neutrino_48.png", 48)):
        destination = (
            tree / f"usr/share/icons/hicolor/{edge}x{edge}/apps/neutrino_agent.png"
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ICONS_DIR / source, destination)
        destination.chmod(0o644)

    control = CONTROL.format(
        name=PACKAGE_NAME,
        version=version,
        architecture=architecture,
        depends=", ".join(RUNTIME_DEPENDENCIES),
        maintainer=maintainer,
    )
    payload.write(tree / "DEBIAN/control", control)
    payload.write(tree / "DEBIAN/postinst", POSTINST, is_executable=True)
    payload.write(tree / "DEBIAN/prerm", PRERM, is_executable=True)
    payload.write(
        tree / "DEBIAN/postrm",
        POSTRM.format(prefix=payload.INSTALL_PREFIX),
        is_executable=True,
    )


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


def _host_architecture() -> str:
    """The Debian architecture name for the machine this runs on."""
    result = subprocess.run(
        ["dpkg", "--print-architecture"], capture_output=True, text=True
    )
    return result.stdout.strip() or "amd64"


if __name__ == "__main__":
    sys.exit(main())
