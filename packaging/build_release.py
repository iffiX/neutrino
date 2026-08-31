"""Build every package this machine can produce, and their checksums.

    python3 packaging/build_release.py --output-dir dist/

The agent's package is architecture-independent and builds anywhere. The hub's
is not: it must be built on the distribution it targets, because its virtual
environment carries no standard library and its compiled wheels fix the
architecture. This runs that build in a container so the result does not
depend on whatever this machine happens to be.

The agent's `.rpm` is built too, when `rpmbuild` is installed. Its `.pkg` and
`.exe` are not built anywhere yet; they need the platforms they are for.

``--only`` builds one part of the release. The tag workflow uses it to put the
hub's architectures on separate runners and to write the checksums once, after
every part has been collected.

Not pure: runs container and packaging tools.
"""

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# The container platform for each architecture the hub is published for.
# Building for anything but the host's own needs QEMU registered with
# binfmt_misc, which is what the tag workflow does before it calls this.
HUB_BUILD_PLATFORMS = {"amd64": "linux/amd64", "arm64": "linux/arm64"}

# Only what the hub's package build reads is copied in — the package, the
# packaging, and the licences of everything it carries. Taking the whole tree
# would carry `config/`, whose real files are root-owned and unreadable, and
# `hub/frontend/node_modules`, which the package does not contain.
# What builds the hub for each distribution family, and what that family needs
# installed first. Each is run inside a container of that family, because the
# environment the package carries has no standard library of its own and the
# compiled wheels in it fix the architecture.
HUB_BUILDS = {
    "debian": {
        "image": "debian:12",
        "install": "apt-get -qq update >/dev/null 2>&1 && "
        "apt-get -qq install -y python3 python3-venv python3-pip dpkg-dev "
        ">/dev/null 2>&1",
        "script": "build_deb.py",
        "architecture": "{arch}",
    },
    "rhel": {
        "image": "fedora:41",
        "install": "dnf -q -y install python3 python3-pip rpm-build >/dev/null 2>&1",
        "script": "build_rpm.py",
        "architecture": "{rpm_arch}",
    },
    "arch": {
        "image": "archlinux:latest",
        "install": "pacman -Sy --noconfirm --needed python python-pip base-devel "
        ">/dev/null 2>&1 && useradd -m builder 2>/dev/null || true",
        "script": "build_pkg.py",
        "architecture": "{pkg_arch}",
        "extra": "--build-user builder",
    },
}

CONTAINER_BUILD = (
    "{install} && mkdir -p /build/hub && "
    "cp -r /src/hub/neutrino_hub /src/hub/packaging /src/hub/pyproject.toml "
    "/build/hub/ && cp -r /src/licenses /build/licenses && cd /build && "
    "python3 hub/packaging/{script} --output-dir /out "
    "--architecture {architecture} {extra}"
)

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
        help="the architecture to build the hub for",
    )
    parser.add_argument(
        "--only",
        choices=("all", "hub", "agent", "checksums"),
        default="all",
        help="build one part of the release instead of everything",
    )
    parser.add_argument(
        "--families",
        default=",".join(HUB_BUILDS),
        help="which distribution families to build the hub for",
    )
    arguments = parser.parse_args()

    output_dir = (REPO_ROOT / arguments.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if arguments.only in ("all", "agent"):
        print("building the agent's deb")
        _run(
            [
                sys.executable,
                str(REPO_ROOT / "agent/packaging/build_deb.py"),
                "--output-dir",
                str(output_dir),
            ]
        )
        if _has_tool("rpmbuild"):
            print("building the agent's rpm")
            _run(
                [
                    sys.executable,
                    str(REPO_ROOT / "agent/packaging/build_rpm.py"),
                    "--output-dir",
                    str(output_dir),
                ]
            )
        else:
            print("  no rpmbuild here, so no rpm")

    if arguments.only in ("all", "hub"):
        for family in arguments.families.split(","):
            family = family.strip()
            if family not in HUB_BUILDS:
                raise SystemExit(
                    f"no hub build for {family}; there is one for: "
                    f"{', '.join(HUB_BUILDS)}"
                )
            print(
                f"building the hub package for {family} "
                f"{arguments.architecture} in {HUB_BUILDS[family]['image']}"
            )
            _build_hub(output_dir, arguments.architecture, family)

    if arguments.only in ("all", "checksums"):
        _write_checksums(output_dir)
    return 0


def _build_hub(output_dir: Path, architecture: str, family: str) -> None:
    """Build the hub package for one distribution family, in a container.

    Args:
        output_dir: Where the package should land.
        architecture: The architecture to build for, named the Debian way.
        family: Which of :data:`HUB_BUILDS` to run.

    Raises:
        SystemExit: If the architecture is not one the hub is published for,
            no container tool is available, or the build fails.
    """
    build = HUB_BUILDS[family]
    names = ARCHITECTURE_NAMES.get(architecture, {})
    platform = HUB_BUILD_PLATFORMS.get(architecture)
    if platform is None:
        raise SystemExit(
            f"the hub is published for {', '.join(HUB_BUILD_PLATFORMS)}, "
            f"not {architecture}"
        )
    engine = _container_engine()
    if engine is None:
        raise SystemExit(
            "podman or docker is needed to build the hub package on its "
            "baseline distribution; pass --only agent to skip it"
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
            build["image"],
            "sh",
            "-c",
            CONTAINER_BUILD.format(
                install=build["install"],
                script=build["script"],
                architecture=names.get(family, architecture),
                extra=build.get("extra", ""),
            ),
        ]
    )


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
