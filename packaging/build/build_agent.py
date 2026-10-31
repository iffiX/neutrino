"""Build the agent's Linux packages, the .deb, the .rpm and the Arch package.

    python3 packaging/build/build_agent.py --architecture amd64 --output-dir dist/

Runs on: any Linux machine with podman or docker. Each package is built in a
container of its family, because it carries an interpreter and the window's
bindings compiled against that family's C libraries. ``--architecture
arm64`` on an x86-64 machine runs the container under emulation and needs
QEMU registered with binfmt_misc first.

Each package carries the Go programs of its target, built into
``dist/go/linux-<architecture>/`` first; the build stops, naming them, when
they are not there.

Not pure: runs container and packaging tools.
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "packaging"))
sys.path.insert(0, str(REPO_ROOT / "agent" / "packaging"))
from shared import edition_build  # noqa: E402
from shared import container_build  # noqa: E402
from shared.go_build import GO_PROGRAMS_DIR  # noqa: E402
import payload  # noqa: E402

# What builds the agent for each family, and what that family needs installed
# first. The window's bindings are compiled here against the family's own C
# libraries, so each package is built where it is going.
AGENT_BUILDS = {
    "debian": {
        "image": "debian:12",
        "install": "apt-get -qq update && "
        "apt-get -qq install -y python3 dpkg-dev pkg-config build-essential "
        "libgirepository1.0-dev libcairo2-dev ca-certificates && "
        "mkdir -p /build && cp -r /src/licenses /build/licenses",
        "script": "build_deb.py",
    },
    "rhel": {
        "image": "fedora:41",
        "install": "dnf -q -y install python3 rpm-build pkgconf-pkg-config gcc "
        "gobject-introspection-devel cairo-devel cairo-gobject-devel "
        "libffi-devel cpio && "
        "mkdir -p /build && cp -r /src/licenses /build/licenses",
        "script": "build_rpm.py",
    },
    "arch": {
        "image": "archlinux:latest",
        "install": "pacman -Sy --noconfirm --needed archlinux-keyring && "
        "pacman -S --noconfirm --needed python base-devel libarchive && "
        "(useradd -m builder 2>/dev/null || true) && "
        "mkdir -p /build && cp -r /src/licenses /build/licenses",
        "script": "build_pkg.py",
        # Arch Linux is x86-64 only; Arch Linux ARM is another project with
        # no image of its own to build in.
        "architectures": ("amd64",),
    },
}

# The Go programs go into the container where the package build takes them
# from, ``dist/go/`` under its own root.
AGENT_CONTAINER_BUILD = (
    "{install} && mkdir -p /build/agent /build/images /build/packaging "
    f"/build/{GO_PROGRAMS_DIR.parent} && "
    "cp -r /src/agent/neutrino_agent /src/agent/packaging "
    "/src/agent/pyproject.toml /build/agent/ && "
    "cp -r /src/packaging/shared /build/packaging/ && "
    f"cp -r /src/{GO_PROGRAMS_DIR} /build/{GO_PROGRAMS_DIR.parent}/ && "
    "cp -r /src/images/icons /build/images/ && cd /build && "
    "python3 agent/packaging/{script} --output-dir /out "
    "--architecture {architecture}"
)


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
    arguments = parser.parse_args()
    edition_build.require_edition_tree(arguments.edition)
    if container_build.container_engine() is None:
        raise SystemExit("podman or docker is needed and neither is on the path")

    payload.go_programs(payload.go_target("linux", arguments.architecture))
    output_dir = (REPO_ROOT / arguments.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    for family in container_build.families(arguments.families):
        published = AGENT_BUILDS[family].get(
            "architectures", container_build.BUILD_PLATFORMS
        )
        if arguments.architecture not in published:
            print(f"  no agent package for {family} {arguments.architecture}")
            continue
        print(
            f"building the agent package for {family} "
            f"{arguments.architecture} in {AGENT_BUILDS[family]['image']}"
        )
        container_build.build_in_container(
            AGENT_BUILDS[family],
            AGENT_CONTAINER_BUILD,
            output_dir,
            arguments.architecture,
            family,
            edition=arguments.edition,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
