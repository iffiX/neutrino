"""Build the client's .deb.

    python3 client/packaging/build_deb.py --output-dir dist/ --architecture amd64

The package carries its own interpreter under /opt/neutrino_client, the
window's bindings built beside it, and the two binaries the client drives, so
it names no Python at all. That fixes it to one architecture: build it in a
container of the machine it is for, the way the hub's package is built.

The client is a person's application, not a service: the package installs a
launcher and an autostart entry and registers no unit.

Needs the development headers the window's bindings compile against, and
`dpkg-deb` for both the build and the viewer it unpacks.

Not pure: writes a package tree and runs dpkg-deb.
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import bundled  # noqa: E402
import payload  # noqa: E402
from gui_assets import ICONS_DIR  # noqa: E402

# The helper's path and the desktop name are the client's own, named here so
# the package and the runtime cannot drift.
from neutrino_client.constants import (  # noqa: E402
    CLIENT_DESKTOP_NAME,
    CLIENT_MOUNT_HELPER_PATH,
    CLIENT_MOUNT_POLKIT_ACTION,
)

CLIENT_ROOT = payload.CLIENT_ROOT
PACKAGE_NAME = payload.PACKAGE_NAME

# The C stack the window loads through its own bindings, what a mount and its
# authorization need, and what the RustDesk viewer the package carries loads:
# upstream's own list, with the alternatives Debian's t64 transition split
# names over.
RUNTIME_DEPENDENCIES = (
    "gir1.2-webkit2-4.1",
    "libgirepository-1.0-1",
    "gir1.2-ayatanaappindicator3-0.1",
    "cifs-utils",
    "polkitd | policykit-1",
    "libgtk-3-0t64 | libgtk-3-0",
    "libxcb-randr0",
    "libxdo3 | libxdo4",
    "libxfixes3",
    "libxcb-shape0",
    "libxcb-xfixes0",
    "libasound2t64 | libasound2",
    "libsystemd0",
    "curl",
    "libva2",
    "libva-drm2",
    "libva-x11-2",
    "libgstreamer-plugins-base1.0-0",
    "libpam0g",
    "gstreamer1.0-pipewire",
)

CONTROL = """Package: {name}
Version: {version}
Section: net
Priority: optional
Architecture: {architecture}
Depends: {depends}
Maintainer: {maintainer}
Description: Neutrino client
 A person's window onto the services a Neutrino Hub publishes for them:
 links, ports forwarded to this machine, shares mounted under their home,
 the AI gateway their tools point at, and desktops the fleet shares.
 .
 Carries its own interpreter and the window's bindings, so it installs on a
 machine with no Python and touches none the machine already has.
"""

POSTINST = """#!/bin/sh
set -e

{prune}
if [ "$1" = configure ]; then
    listing=/var/lib/dpkg/info/{package}.list
    if [ -r "$listing" ]; then
        prune_untracked {prefix} <"$listing"
    fi
fi

if [ -d /usr/share/icons/hicolor ]; then
    gtk-update-icon-cache -f /usr/share/icons/hicolor >/dev/null 2>&1 || true
fi
update-desktop-database /usr/share/applications >/dev/null 2>&1 || true

echo ""
echo "  Neutrino client installed. Open it and join a hub:"
echo ""
echo "      nclient gui"
echo ""
"""

POSTRM = """#!/bin/sh
set -e

# What dpkg leaves once its own files are gone: the bytecode the interpreter
# wrote beside them.
if [ "$1" = remove ] || [ "$1" = purge ]; then
    rm -rf {prefix}
fi
"""

WRAPPER = """#!/bin/sh
# The client runs from the interpreter the package carries, never the system
# one.
exec {python}/bin/python3 -m neutrino_client.cli.entry "$@"
"""

MOUNT_HELPER = """#!/bin/sh
exec {python}/bin/python3 -m neutrino_client.cli.mount_helper "$@"
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
    payload.stage_client_tree(payload.site_packages_of(staged_python), version)
    payload.stage_linux_gui_bindings(staged_python)
    payload.compile_bytecode(staged_python, payload.PYTHON_DIR)
    payload.strip_build_paths(staged_python, tree)
    bundled.stage_linux_binaries(tree, architecture)
    payload.stage_licenses(tree)
    _lay_out_desktop(tree)

    payload.write(
        tree / "usr/bin/nclient",
        WRAPPER.format(python=payload.PYTHON_DIR),
        is_executable=True,
    )
    payload.write(
        tree / str(CLIENT_MOUNT_HELPER_PATH).lstrip("/"),
        MOUNT_HELPER.format(python=payload.PYTHON_DIR),
        is_executable=True,
    )
    payload.write(
        tree / f"usr/share/polkit-1/actions/{CLIENT_MOUNT_POLKIT_ACTION}.policy",
        (
            CLIENT_ROOT
            / "neutrino_client/data/polkit"
            / f"{CLIENT_MOUNT_POLKIT_ACTION}.policy"
        ).read_text(encoding="utf-8"),
    )

    control = CONTROL.format(
        name=PACKAGE_NAME,
        version=version,
        architecture=architecture,
        depends=", ".join(RUNTIME_DEPENDENCIES),
        maintainer=maintainer,
    )
    payload.write(tree / "DEBIAN/control", control)
    payload.write(
        tree / "DEBIAN/postinst",
        POSTINST.format(
            prune=payload.PRUNE_UNTRACKED,
            package=PACKAGE_NAME,
            prefix=payload.INSTALL_PREFIX,
        ),
        is_executable=True,
    )
    payload.write(
        tree / "DEBIAN/postrm",
        POSTRM.format(prefix=payload.INSTALL_PREFIX),
        is_executable=True,
    )


def _lay_out_desktop(tree: Path) -> None:
    """Install the launcher, the autostart entry and the icons.

    Args:
        tree: The directory to build under.
    """
    desktop = CLIENT_ROOT / "neutrino_client/data/desktop"
    payload.write(
        tree / f"usr/share/applications/{CLIENT_DESKTOP_NAME}.desktop",
        (desktop / f"{CLIENT_DESKTOP_NAME}.desktop").read_text(encoding="utf-8"),
    )
    payload.write(
        tree / f"etc/xdg/autostart/{CLIENT_DESKTOP_NAME}.desktop",
        (desktop / f"{CLIENT_DESKTOP_NAME}_autostart.desktop").read_text(
            encoding="utf-8"
        ),
    )
    for source, edge in (("neutrino_256.png", 256), ("neutrino_48.png", 48)):
        destination = (
            tree
            / f"usr/share/icons/hicolor/{edge}x{edge}/apps/{CLIENT_DESKTOP_NAME}.png"
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ICONS_DIR / source, destination)
        destination.chmod(0o644)


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
