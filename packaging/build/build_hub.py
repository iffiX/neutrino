"""Build the hub's Linux packages, the .deb, the .rpm and the Arch package.

    python3 packaging/build/build_hub.py --architecture amd64 --output-dir dist/

Runs on: any Linux machine with podman or docker, after ``npm run build`` in
``hub/frontend``, since the package refuses to build without the panel. Each
package is built in a container of its family, because the environment it
carries has no standard library of its own and the compiled wheels in it fix
the architecture. ``--architecture arm64`` on an x86-64 machine runs the
container under emulation and needs QEMU registered with binfmt_misc first.

Each hub package carries one agent package, the one of its own family and
machine, and the Arch package none. ``--agent-packages`` names a directory
holding every agent package of the release, which the manifest names with
their hashes; without it the hub's build makes its own one and names that
alone. ``--agent-package-url-base`` is where the release publishes them.

Not pure: runs container and packaging tools.
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "packaging"))
from shared import edition_build  # noqa: E402
from shared import container_build  # noqa: E402

# What builds the hub for each distribution family, and what that family needs
# installed first, the agent package of the same family among it. Each is run inside a container of that family, because the
# environment the package carries has no standard library of its own and the
# compiled wheels in it fix the architecture.
HUB_BUILDS = {
    "debian": {
        "image": "debian:12",
        "install": "apt-get -qq update && "
        "apt-get -qq install -y python3 python3-venv python3-pip dpkg-dev "
        "pkg-config build-essential libgirepository1.0-dev libcairo2-dev "
        "ca-certificates",
        "script": "build_deb.py",
        "architecture": "{arch}",
    },
    "rhel": {
        "image": "fedora:41",
        "install": "dnf -q -y install python3 python3-pip rpm-build cpio gcc "
        "pkgconf-pkg-config gobject-introspection-devel cairo-devel "
        "cairo-gobject-devel libffi-devel",
        "script": "build_rpm.py",
        "architecture": "{rpm_arch}",
    },
    "arch": {
        "image": "archlinux:latest",
        "install": "pacman -Sy --noconfirm --needed archlinux-keyring && "
        "pacman -S --noconfirm --needed python python-pip base-devel "
        "gobject-introspection cairo libffi && "
        "(useradd -m builder 2>/dev/null || true)",
        "script": "build_pkg.py",
        "architecture": "{pkg_arch}",
        "extra": "--build-user builder",
        # Arch Linux is x86-64 only; Arch Linux ARM is another project with
        # no image of its own to build in.
        "architectures": ("amd64",),
    },
}

# Only what the hub's package build reads is copied in: the package, the
# packaging, the shared naming tables, the agent tree it bakes native
# packages from, the shipped icons, and the licences of everything it
# carries. Taking the whole tree would carry `config/`, whose real files are
# root-owned and unreadable, and `hub/frontend/node_modules`, which the
# package does not contain.
HUB_CONTAINER_BUILD = (
    "{install} && mkdir -p /build/hub /build/agent /build/images /build/packaging && "
    "cp -r /src/hub/neutrino_hub /src/hub/packaging /src/hub/pyproject.toml "
    "/build/hub/ && "
    "cp -r /src/packaging/shared /build/packaging/ && "
    "cp -r /src/agent/neutrino_agent /src/agent/packaging "
    "/src/agent/pyproject.toml "
    "/build/agent/ && "
    "cp -r /src/images/icons /build/images/ && "
    "cp -r /src/licenses /build/licenses && cd /build && "
    "python3 hub/packaging/{script} --output-dir /out "
    "--architecture {architecture} {extra}"
)

# The built panel the package refuses to go without.
HUB_PANEL_INDEX = REPO_ROOT / "hub" / "neutrino_hub" / "data" / "frontend" / "index.html"


def main() -> int:
    """Build the packages.

    Returns:
        The process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    edition_build.add_edition_argument(parser)
    parser.add_argument("--output-dir", default="dist", help="where to write packages")
    parser.add_argument(
        "--architecture",
        default=container_build.host_architecture(),
        help="the architecture to build for",
    )
    parser.add_argument(
        "--families",
        default=",".join(container_build.CONTAINER_FAMILIES),
        help="which distribution families to build for",
    )
    parser.add_argument(
        "--agent-package-url-base",
        default="",
        help="where a release publishes the agent packages the hub seeds",
    )
    parser.add_argument(
        "--agent-packages",
        default="",
        help="a directory of every agent package of the release; the hub "
        "package carries the one of its own family and machine",
    )
    arguments = parser.parse_args()
    edition_build.require_edition_tree(arguments.edition)
    if container_build.container_engine() is None:
        raise SystemExit("podman or docker is needed and neither is on the path")
    if not HUB_PANEL_INDEX.is_file():
        raise SystemExit(
            "the panel is not built; run npm ci and npm run build in hub/frontend"
        )

    output_dir = (REPO_ROOT / arguments.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    for family in container_build.families(arguments.families):
        published = HUB_BUILDS[family].get(
            "architectures", container_build.BUILD_PLATFORMS
        )
        if arguments.architecture not in published:
            print(f"  no hub package for {family} {arguments.architecture}")
            continue
        print(
            f"building the hub package for {family} "
            f"{arguments.architecture} in {HUB_BUILDS[family]['image']}"
        )
        container_build.build_in_container(
            HUB_BUILDS[family],
            HUB_CONTAINER_BUILD,
            output_dir,
            arguments.architecture,
            family,
            agent_package_url_base=arguments.agent_package_url_base,
            agent_packages=arguments.agent_packages,
            edition=arguments.edition,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
