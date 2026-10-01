"""Build the desktop client's Linux packages, the .deb and the .rpm.

    python3 packaging/build/build_client_desktop.py --architecture amd64 --output-dir dist/

Runs on: a Linux machine of the architecture being built, with podman or
docker. The client is compiled with Nuitka inside the container, and Nuitka
under emulation takes hours, so an arm64 package is built on an arm64
machine.

Not pure: runs container and packaging tools.
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "packaging"))
from shared import container_build  # noqa: E402

# What builds the client for each format, and what the container needs
# installed first. The window's bindings are compiled here and the client is
# compiled around them, which takes a C compiler, patchelf and the typelibs
# the window loads; the viewer is unpacked out of upstream's .deb, so the
# container needs dpkg and readelf too.
#
# Both formats are built in one image, which is what keeps the client's glibc
# floor at 2.34. The client is the only package with C compiled in its
# container, so it takes the symbol versions of that container's glibc:
# Fedora 41 redirects strtol and sscanf to the __isoc23_ names glibc 2.38
# introduced. The typelibs Nuitka bundles and the binaries it writes
# therefore both come from Debian 12; what each format names as a dependency
# is still spelled its own way, in the packaging scripts.
#
# Debian 12 is also the one image carrying both WebKit2 ABIs, so both sets of
# typelibs go into the container and travel in every Linux package: the
# window opens on 4.1 where a machine has it and on 4.0 where it has that.
CLIENT_BUILDS = {
    "debian": {
        "image": "debian:12",
        "install": "apt-get -qq update >/dev/null 2>&1 && "
        "apt-get -qq install -y python3 dpkg dpkg-dev binutils pkg-config "
        "build-essential patchelf ccache libgirepository1.0-dev libcairo2-dev "
        "gir1.2-gtk-3.0 gir1.2-webkit2-4.1 gir1.2-webkit2-4.0 "
        "gir1.2-ayatanaappindicator3-0.1 "
        "ca-certificates >/dev/null 2>&1",
        "script": "build_deb.py",
    },
    "rhel": {
        "image": "debian:12",
        "install": "apt-get -qq update >/dev/null 2>&1 && "
        "apt-get -qq install -y python3 dpkg dpkg-dev binutils pkg-config "
        "build-essential patchelf ccache libgirepository1.0-dev libcairo2-dev "
        "gir1.2-gtk-3.0 gir1.2-webkit2-4.1 gir1.2-webkit2-4.0 "
        "gir1.2-ayatanaappindicator3-0.1 "
        "rpm cpio ca-certificates >/dev/null 2>&1",
        "script": "build_rpm.py",
    },
}

CLIENT_CONTAINER_BUILD = (
    "{install} && mkdir -p /build/client/desktop /build/images /build/packaging && "
    "cp -r /src/client/desktop/neutrino_client /src/client/desktop/packaging "
    "/src/client/desktop/frontend /src/client/desktop/pyproject.toml "
    "/build/client/desktop/ && "
    "cp -r /src/packaging/shared /build/packaging/ && "
    "cp -r /src/images/icons /build/images/ && "
    "cp -r /src/licenses /build/licenses && cd /build && "
    "python3 client/desktop/packaging/{script} --output-dir /out "
    "--architecture {architecture}"
)


def main() -> int:
    """Build the packages.

    Returns:
        The process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
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
    if container_build.container_engine() is None:
        raise SystemExit("podman or docker is needed and neither is on the path")

    output_dir = (REPO_ROOT / arguments.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    for family in container_build.families(arguments.families):
        if family not in CLIENT_BUILDS:
            print(f"  no client package for {family}")
            continue
        print(
            f"building the client package for {family} "
            f"{arguments.architecture} in {CLIENT_BUILDS[family]['image']}"
        )
        container_build.build_in_container(
            CLIENT_BUILDS[family],
            CLIENT_CONTAINER_BUILD,
            output_dir,
            arguments.architecture,
            family,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
