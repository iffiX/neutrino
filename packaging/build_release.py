"""Build every package this machine can produce, and their checksums.

    python3 packaging/build_release.py --output-dir dist/

Neither package builds anywhere any more: both carry their own interpreter and
compiled extensions, so both are built in a container of the family and the
machine they are for. This runs those builds so the result does not depend on
whatever this machine happens to be.

The client's `.msi` and `.pkg` are not built here; they need the platforms
they are for, and their own scripts run there.

``--only sources`` writes one source archive: this tree at the commit being
released, with the source of everything the packages carry beside it under
``third_party/``, so a release attaches a single file.

``--only`` builds one part of the release. The tag workflow uses it to put the
architectures on separate runners and to write the checksums once, after every
part has been collected.

Not pure: runs container and packaging tools.
"""

import argparse
import hashlib
import io
import re
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# The source of everything the packages carry, pinned to the archive at the
# tag the binaries were built from: RustDesk (AGPL-3.0) in the agent and the
# client, EasyTier (LGPL-3.0), NetBird (BSD-3), xray (MPL-2.0) and
# CLIProxyAPI (MIT) in the hub, cc-switch (MIT) in the client. Each goes into
# the release's source archive unmodified.
SOURCE_ARCHIVES = (
    (
        "rustdesk-1.4.9-source.tar.gz",
        "https://github.com/rustdesk/rustdesk/archive/refs/tags/1.4.9.tar.gz",
        "1769fcc51751aab91bc0cfa691723722f51d3693ce3ddea3d92cfb1c319100e0",  # scan: allow
    ),
    (
        "easytier-2.6.4-source.tar.gz",
        "https://github.com/EasyTier/EasyTier/archive/refs/tags/v2.6.4.tar.gz",
        "352c0866da709415a837405a6ce4f51b8dfae27e5d5c1da1fb4d8f7338e46795",  # scan: allow
    ),
    (
        "netbird-0.78.1-source.tar.gz",
        "https://github.com/netbirdio/netbird/archive/refs/tags/v0.78.1.tar.gz",
        "2adde8bbd77ea595b5f50174be10574466f1c07fc9fbf827024245aec2f4dabc",  # scan: allow
    ),
    (
        "xray-core-26.3.27-source.tar.gz",
        "https://github.com/XTLS/Xray-core/archive/refs/tags/v26.3.27.tar.gz",
        "992a4997e6bb846d11469435d687f99ef812fcde1e0a009bb8e95189ea20331d",  # scan: allow
    ),
    (
        "cliproxyapi-7.2.146-source.tar.gz",
        "https://github.com/router-for-me/CLIProxyAPI/archive/refs/tags/v7.2.146.tar.gz",
        "10078716be34cc7ecf488c3b50b17d5675261a36eb78cbdfd768331b989f9fca",  # scan: allow
    ),
    (
        "cc-switch-cli-5.10.4-source.tar.gz",
        "https://github.com/SaladDay/cc-switch-cli/archive/refs/tags/v5.10.4.tar.gz",
        "cb10c2742b5552bb4de4cf58663afdf8d79e96e05ea68b5533489a6ba0583dcb",  # scan: allow
    ),
)

# The container platform for each architecture the packages are published
# for. Building for anything but the host's own needs QEMU registered with
# binfmt_misc, which is what the tag workflow does before it calls this.
# 32-bit ARM is not on the list: nothing carried is published for it.
BUILD_PLATFORMS = {"amd64": "linux/amd64", "arm64": "linux/arm64"}

# Only what the hub's package build reads is copied in — the package, the
# packaging, the agent tree it bakes native packages from with the agent's
# frontend, the shipped icons, and the licences of everything it carries.
# Taking the whole tree would carry `config/`, whose real files are
# root-owned and unreadable, and `hub/frontend/node_modules`, which the
# package does not contain.
# What builds the hub for each distribution family, and what that family needs
# installed first. Each is run inside a container of that family, because the
# environment the package carries has no standard library of its own and the
# compiled wheels in it fix the architecture.
HUB_BUILDS = {
    "debian": {
        "image": "debian:12",
        "install": "apt-get -qq update >/dev/null 2>&1 && "
        "apt-get -qq install -y python3 python3-venv python3-pip dpkg-dev rpm cpio "
        "pkg-config build-essential libgirepository1.0-dev libcairo2-dev "
        "ca-certificates >/dev/null 2>&1",
        "script": "build_deb.py",
        "architecture": "{arch}",
    },
    "rhel": {
        "image": "fedora:41",
        "install": "dnf -q -y install python3 python3-pip rpm-build dpkg gcc "
        "pkgconf-pkg-config gobject-introspection-devel cairo-devel "
        "cairo-gobject-devel libffi-devel >/dev/null 2>&1",
        "script": "build_rpm.py",
        "architecture": "{rpm_arch}",
    },
    "arch": {
        "image": "archlinux:latest",
        "install": "pacman -Sy --noconfirm --needed python python-pip base-devel "
        "dpkg rpm-tools gobject-introspection cairo libffi >/dev/null 2>&1 && "
        "useradd -m builder 2>/dev/null || true",
        "script": "build_pkg.py",
        "architecture": "{pkg_arch}",
        "extra": "--build-user builder",
        # Arch Linux is x86-64 only; Arch Linux ARM is another project with
        # no image of its own to build in.
        "architectures": ("amd64",),
    },
}

# What builds the agent for each family, and what that family needs installed
# first. The window's bindings are compiled here against the family's own C
# libraries, so each package is built where it is going.
AGENT_BUILDS = {
    "debian": {
        "image": "debian:12",
        "install": "apt-get -qq update >/dev/null 2>&1 && "
        "apt-get -qq install -y python3 dpkg-dev pkg-config build-essential "
        "libgirepository1.0-dev libcairo2-dev ca-certificates >/dev/null 2>&1 && "
        "mkdir -p /build && cp -r /src/licenses /build/licenses",
        "script": "build_deb.py",
    },
    "rhel": {
        "image": "fedora:41",
        "install": "dnf -q -y install python3 rpm-build pkgconf-pkg-config gcc "
        "gobject-introspection-devel cairo-devel cairo-gobject-devel "
        "libffi-devel cpio >/dev/null 2>&1 && "
        "mkdir -p /build && cp -r /src/licenses /build/licenses",
        "script": "build_rpm.py",
    },
}

# What builds the client for each family, and what that family needs
# installed first. The window's bindings are compiled here against the
# family's own C libraries and the client is compiled around them, which
# takes a C compiler, patchelf and the typelibs the window loads; the viewer
# is unpacked out of upstream's .deb, so both families need dpkg and readelf.
CLIENT_BUILDS = {
    "debian": {
        "image": "debian:12",
        "install": "apt-get -qq update >/dev/null 2>&1 && "
        "apt-get -qq install -y python3 dpkg dpkg-dev binutils pkg-config "
        "build-essential patchelf ccache libgirepository1.0-dev libcairo2-dev "
        "gir1.2-gtk-3.0 gir1.2-webkit2-4.1 gir1.2-ayatanaappindicator3-0.1 "
        "ca-certificates >/dev/null 2>&1",
        "script": "build_deb.py",
    },
    "rhel": {
        "image": "fedora:41",
        "install": "dnf -q -y install python3 rpm-build dpkg binutils "
        "pkgconf-pkg-config gcc patchelf ccache gobject-introspection-devel "
        "cairo-devel cairo-gobject-devel libffi-devel gtk3 webkit2gtk4.1 "
        "libayatana-appindicator-gtk3 cpio >/dev/null 2>&1",
        "script": "build_rpm.py",
    },
}

CLIENT_CONTAINER_BUILD = (
    "{install} && mkdir -p /build/client /build/images && "
    "cp -r /src/client/neutrino_client /src/client/packaging "
    "/src/client/frontend /src/client/pyproject.toml /build/client/ && "
    "cp -r /src/images/icons /build/images/ && "
    "cp -r /src/licenses /build/licenses && cd /build && "
    "python3 client/packaging/{script} --output-dir /out "
    "--architecture {architecture}"
)

AGENT_CONTAINER_BUILD = (
    "{install} && mkdir -p /build/agent /build/images && "
    "cp -r /src/agent/neutrino_agent /src/agent/packaging "
    "/src/agent/pyproject.toml /build/agent/ && "
    "cp -r /src/images/icons /build/images/ && cd /build && "
    "python3 agent/packaging/{script} --output-dir /out "
    "--architecture {architecture}"
)

CONTAINER_BUILD = (
    "{install} && mkdir -p /build/hub /build/agent /build/images && "
    "cp -r /src/hub/neutrino_hub /src/hub/packaging /src/hub/pyproject.toml "
    "/build/hub/ && "
    "cp -r /src/agent/neutrino_agent /src/agent/packaging "
    "/src/agent/pyproject.toml "
    "/build/agent/ && "
    "cp -r /src/images/icons /build/images/ && "
    "cp -r /src/licenses /build/licenses && cd /build && "
    "python3 hub/packaging/{script} --output-dir /out "
    "--architecture {architecture} {extra}"
)

# What the hub's build reads to learn where a release publishes the agent
# packages it seeds its cache with. Passed into the container only when it is
# given: without it the hub package carries the entries it seeded and no URL,
# which is what makes a local build refuse a platform it did not make rather
# than reach for a file nobody published.
AGENT_PACKAGE_URL_BASE_ENV = "NEUTRINO_AGENT_PACKAGE_URL_BASE"

# The name each family gives the same machine.
ARCHITECTURE_NAMES = {
    "amd64": {"debian": "amd64", "rhel": "x86_64", "arch": "x86_64"},
    "arm64": {"debian": "arm64", "rhel": "aarch64", "arch": "aarch64"},
}


def main() -> int:
    """Build the packages.

    Returns:
        The process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", default="dist", help="where to write packages")
    parser.add_argument(
        "--architecture",
        default=_host_architecture(),
        help="the architecture to build for",
    )
    parser.add_argument(
        "--only",
        choices=("all", "hub", "agent", "client", "sources", "checksums"),
        default="all",
        help="build one part of the release instead of everything",
    )
    parser.add_argument(
        "--families",
        default=",".join(HUB_BUILDS),
        help="which distribution families to build for",
    )
    parser.add_argument(
        "--agent-package-url-base",
        default="",
        help="where a release publishes the agent packages the hub seeds",
    )
    arguments = parser.parse_args()

    output_dir = (REPO_ROOT / arguments.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if arguments.only in ("all", "agent"):
        for family in _families(arguments.families):
            if family not in AGENT_BUILDS:
                print(f"  no agent package for {family}")
                continue
            print(
                f"building the agent package for {family} "
                f"{arguments.architecture} in {AGENT_BUILDS[family]['image']}"
            )
            _build_in_container(
                AGENT_BUILDS[family],
                AGENT_CONTAINER_BUILD,
                output_dir,
                arguments.architecture,
                family,
            )

    if arguments.only in ("all", "client"):
        for family in _families(arguments.families):
            if family not in CLIENT_BUILDS:
                print(f"  no client package for {family}")
                continue
            print(
                f"building the client package for {family} "
                f"{arguments.architecture} in {CLIENT_BUILDS[family]['image']}"
            )
            _build_in_container(
                CLIENT_BUILDS[family],
                CLIENT_CONTAINER_BUILD,
                output_dir,
                arguments.architecture,
                family,
            )

    if arguments.only in ("all", "hub"):
        for family in _families(arguments.families):
            published = HUB_BUILDS[family].get("architectures", BUILD_PLATFORMS)
            if arguments.architecture not in published:
                print(f"  no hub package for {family} {arguments.architecture}")
                continue
            print(
                f"building the hub package for {family} "
                f"{arguments.architecture} in {HUB_BUILDS[family]['image']}"
            )
            _build_in_container(
                HUB_BUILDS[family],
                CONTAINER_BUILD,
                output_dir,
                arguments.architecture,
                family,
                agent_package_url_base=arguments.agent_package_url_base,
            )

    if arguments.only in ("all", "sources"):
        _write_source_archive(output_dir)

    if arguments.only in ("all", "checksums"):
        _write_checksums(output_dir)
    return 0


def _families(requested: str) -> list:
    """The families to build, checked against the ones this project has.

    Args:
        requested: The comma-separated list from the command line.

    Returns:
        The family names, in the order asked for.

    Raises:
        SystemExit: When one of them is not a family at all. A family with no
            agent package is not that: the agent loop says so and moves on.
    """
    names = [name.strip() for name in requested.split(",") if name.strip()]
    for name in names:
        if name not in HUB_BUILDS:
            raise SystemExit(
                f"no build for {name}; there is one for: {', '.join(HUB_BUILDS)}"
            )
    return names


def _build_in_container(
    build: dict,
    script: str,
    output_dir: Path,
    architecture: str,
    family: str,
    *,
    agent_package_url_base: str = "",
) -> None:
    """Run one packaging build inside a container of its own family.

    Args:
        build: The family's entry in :data:`HUB_BUILDS`,
            :data:`AGENT_BUILDS` or :data:`CLIENT_BUILDS`.
        script: The shell command template to run inside it.
        output_dir: Where the package should land.
        architecture: The architecture to build for, named the Debian way.
        family: Which family is being built, which names the architecture.
        agent_package_url_base: Where a release publishes the agent packages
            the hub's build seeds its cache with; nothing is stamped without
            it.

    Raises:
        SystemExit: If the architecture is not one the packages are published
            for, no container tool is available, or the build fails.
    """
    names = ARCHITECTURE_NAMES.get(architecture, {})
    platform = BUILD_PLATFORMS.get(architecture)
    if platform is None:
        raise SystemExit(
            f"the packages are published for {', '.join(BUILD_PLATFORMS)}, "
            f"not {architecture}"
        )
    engine = _container_engine()
    if engine is None:
        raise SystemExit(
            "podman or docker is needed: both packages carry an interpreter "
            "and compiled extensions, so both are built on their baseline "
            "distribution"
        )
    stamp = (
        ["-e", f"{AGENT_PACKAGE_URL_BASE_ENV}={agent_package_url_base}"]
        if agent_package_url_base
        else []
    )
    # --network=host because this machine's own nftables rules are what a
    # container network would otherwise have to negotiate with.
    _run(
        [
            engine,
            "run",
            "--rm",
            "--network=host",
            "--platform",
            platform,
            "-v",
            f"{REPO_ROOT}:/src:ro",
            "-v",
            f"{output_dir}:/out",
        ]
        + stamp
        + [
            build["image"],
            "sh",
            "-c",
            script.format(
                install=build["install"],
                script=build["script"],
                architecture=names.get(family, architecture),
                extra=build.get("extra", ""),
            ),
        ]
    )


def _write_source_archive(output_dir: Path) -> None:
    """Write the release's one source archive.

    ``neutrino-<version>/`` holds this tree as git carries it at the current
    commit, and ``neutrino-<version>/third_party/`` the pinned upstream
    archives as they were fetched.

    Args:
        output_dir: The directory holding the packages.

    Raises:
        SystemExit: When an upstream archive is not the one pinned, or the
            tree is not a git checkout.
    """
    version = _version()
    root = f"neutrino-{version}"
    target = output_dir / f"{root}-source.tar.gz"
    with tempfile.TemporaryDirectory() as workdir:
        tree = Path(workdir) / root
        tree.mkdir()
        archived = subprocess.run(
            ["git", "archive", "--format=tar", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
        )
        if archived.returncode != 0:
            raise SystemExit(archived.stderr.decode(errors="replace").strip())
        with tarfile.open(fileobj=io.BytesIO(archived.stdout)) as bundle:
            bundle.extractall(tree, filter="data")

        third_party = tree / "third_party"
        third_party.mkdir()
        for name, url, digest in SOURCE_ARCHIVES:
            print(f"  fetching {name}")
            with urllib.request.urlopen(url, timeout=600) as response:
                data = response.read()
            found = hashlib.sha256(data).hexdigest()
            if found != digest:
                raise SystemExit(f"{name}: expected sha256 {digest}, got {found}")
            (third_party / name).write_bytes(data)

        with tarfile.open(target, "w:gz") as archive:
            archive.add(tree, arcname=root)
    print(f"wrote {target} ({target.stat().st_size // 1024 // 1024} MiB)")


def _version() -> str:
    """The version the packages declare, read off the hub's pyproject."""
    text = (REPO_ROOT / "hub" / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if match is None:
        raise SystemExit("hub/pyproject.toml declares no version")
    return match.group(1)


def _write_checksums(output_dir: Path) -> None:
    """Write SHA256SUMS beside the packages.

    The hub verifies this before installing an agent on a device, so a
    truncated download fails loudly instead of half-installing.

    Args:
        output_dir: The directory holding the packages.
    """
    lines = []
    for path in sorted(output_dir.iterdir()):
        if path.name == "SHA256SUMS" or not path.is_file():
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.name}")
        print(f"  {path.name}  {path.stat().st_size // 1024} KiB")
    (output_dir / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {output_dir / 'SHA256SUMS'}")


def _container_engine() -> "str | None":
    """Whichever container tool is installed, or None."""
    for name in ("podman", "docker"):
        if _has_tool(name):
            return name
    return None


def _has_tool(name: str) -> bool:
    """Whether a build tool is on the path.

    Args:
        name: The executable to look for.

    Returns:
        True when it can be run.
    """
    return subprocess.run(["which", name], capture_output=True).returncode == 0


def _host_architecture() -> str:
    """The Debian architecture name for this machine."""
    result = subprocess.run(
        ["dpkg", "--print-architecture"], capture_output=True, text=True
    )
    return result.stdout.strip() or "amd64"


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
            f"{' '.join(command[:2])} failed:\n{(result.stderr or result.stdout).strip()}"
        )
    if result.stdout.strip():
        print(f"  {result.stdout.strip().splitlines()[-1]}")


if __name__ == "__main__":
    sys.exit(main())
