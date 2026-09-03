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
        python3 python3-venv python3-pip dpkg-dev rpm && cp -r /src /build && \
        cd /build && python3 hub/packaging/build_deb.py --output-dir /out'

Not pure: creates a virtual environment, installs into it, runs dpkg-deb.
"""

import argparse
import subprocess
import tempfile
from pathlib import Path

from venv_tree import (
    PACKAGE_NAME,
    dependencies,
    recommendations,
    PYTHON_DIR,
    build_environment,
    panel_unit,
    require_built_frontend,
    run,
    version,
    write,
    WRAPPER,
)

CONTROL = """Package: {name}
Version: {version}
Section: admin
Priority: optional
Architecture: {architecture}
Depends: {depends}
Recommends: {recommends}
Maintainer: {maintainer}
Installed-Size: {size}
Description: Neutrino Hub, a personal developer infrastructure hub
 Transparent proxy routing, LAN device management, an AI gateway and a web
 control panel, on one box. Carries its own Python environment.
"""

POSTINST = """#!/bin/sh
set -e

install -d -m 755 /etc/neutrino
install -d -m 700 /etc/neutrino/hub
install -d -m 755 /var/lib/neutrino
install -d -m 755 /var/lib/neutrino/generated
install -d -m 755 /var/log/neutrino

systemctl daemon-reload || true

# An upgrade can change the unit files and the software they start, and
# `nhub apply` is what writes them onto a box somebody already set up.
if [ "$1" = configure ] && [ -n "$2" ]; then
    nhub apply >/dev/null 2>&1 ||
        echo "  Run 'sudo nhub apply' to pick up this version."
    # And the panel, because it is the process running the code this package
    # just replaced. `nhub apply` re-renders what the modules produce and
    # restarts what consumes it, but the panel serves itself: without this it
    # goes on running the old Python behind the new frontend, which is a strip
    # asking for fields the old API does not send. Only when it is already up
    # — a box nobody has set up has no panel to restart.
    systemctl try-restart neutrino_hub_web.service >/dev/null 2>&1 || true
    exit 0
fi

echo ""
echo "  Neutrino Hub installed. Set it up with:"
echo ""
echo "      sudo nhub setup"
echo ""
"""

PRERM = """#!/bin/sh
set -e

if [ "$1" = remove ] || [ "$1" = deconfigure ]; then
    for unit in neutrino_hub_web neutrino_hub_router neutrino_hub_xray neutrino_hub_cliproxyapi; do
        systemctl stop "${unit}.service" >/dev/null 2>&1 || true
        systemctl disable "${unit}.service" >/dev/null 2>&1 || true
    done
fi
"""

POSTRM = """#!/bin/sh
set -e

systemctl daemon-reload >/dev/null 2>&1 || true

# Named rather than excluding "upgrade": postrm runs on an upgrade as well,
# after the new files are already unpacked. What is left once dpkg removes the
# package's own files is the bytecode the interpreter wrote while it ran.
if [ "$1" = remove ] || [ "$1" = purge ]; then
    rm -rf /opt/neutrino
fi

if [ "$1" = purge ]; then
    rm -rf /etc/neutrino/hub /var/lib/neutrino /var/log/neutrino /run/neutrino
    rmdir /etc/neutrino 2>/dev/null || true
fi
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

    require_built_frontend()
    package_version = version()
    output_dir = Path(arguments.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as workdir:
        tree = (
            Path(workdir) / f"{PACKAGE_NAME}_{package_version}_{arguments.architecture}"
        )
        build_environment(tree, package_version, arguments.architecture)
        _lay_out(tree, package_version, arguments.architecture, arguments.maintainer)
        target = (
            output_dir
            / f"{PACKAGE_NAME}_{package_version}_{arguments.architecture}.deb"
        )
        _build(tree, target)

    print(f"wrote {target} ({target.stat().st_size // 1024 // 1024} MiB)")
    return 0


def _lay_out(
    tree: Path, package_version: str, architecture: str, maintainer: str
) -> None:
    """Write everything outside the environment.

    Args:
        tree: The staging directory.
        package_version: The version being packaged.
        architecture: The Architecture field's value.
        maintainer: The Maintainer field's value.
    """
    write(
        tree / "usr/bin/nhub",
        WRAPPER.format(python=PYTHON_DIR),
        is_executable=True,
    )

    # Unit files are rendered at setup time by `nhub setup`, which knows
    # the paths; what ships here is the panel's own unit, already absolute.
    write(tree / "lib/systemd/system/neutrino_hub_web.service", panel_unit())

    size = sum(f.stat().st_size for f in tree.rglob("*") if f.is_file()) // 1024
    control = CONTROL.format(
        name=PACKAGE_NAME,
        version=package_version,
        architecture=architecture,
        maintainer=maintainer,
        size=size,
        depends=", ".join(dependencies("debian")),
        recommends=", ".join(recommendations("debian")),
    )
    write(tree / "DEBIAN/control", control)
    write(tree / "DEBIAN/postinst", POSTINST, is_executable=True)
    write(tree / "DEBIAN/prerm", PRERM, is_executable=True)
    write(tree / "DEBIAN/postrm", POSTRM, is_executable=True)


def _build(tree: Path, target: Path) -> None:
    """Run dpkg-deb over a laid-out tree.

    Args:
        tree: The package tree.
        target: Where to write the .deb.
    """
    run(["dpkg-deb", "--root-owner-group", "--build", str(tree), str(target)])


def _host_architecture() -> str:
    """The Debian architecture name for the machine running this."""
    result = subprocess.run(
        ["dpkg", "--print-architecture"], capture_output=True, text=True
    )
    return result.stdout.strip() or "amd64"


if __name__ == "__main__":
    raise SystemExit(main())
