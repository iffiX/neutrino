"""Build every package this machine can produce, and their checksums.

    python3 packaging/build_release.py --output-dir dist/

The agent's package is architecture-independent and builds anywhere. The hub's
is not: it must be built on the distribution it targets, because its virtual
environment carries no standard library and its compiled wheels fix the
architecture. This runs that build in a container so the result does not
depend on whatever this machine happens to be.

macOS and Windows agent packages are not built here; they need those platforms
and are produced in CI.

Not pure: runs container and packaging tools.
"""

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# The oldest distribution the hub package supports. Building here sets the
# glibc floor (2.36) and the interpreter the package depends on (python3.11).
HUB_BUILD_IMAGE = "debian:12"

CONTAINER_BUILD = (
    "apt-get -qq update >/dev/null 2>&1 && "
    "apt-get -qq install -y python3 python3-venv python3-pip dpkg-dev "
    ">/dev/null 2>&1 && cp -r /src /build && cd /build && "
    "python3 hub/packaging/build_deb.py --output-dir /out --architecture {arch}"
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
        default=_host_architecture(),
        help="the architecture to build the hub for",
    )
    parser.add_argument(
        "--agent-only",
        action="store_true",
        help="skip the hub, which needs a container",
    )
    arguments = parser.parse_args()

    output_dir = (REPO_ROOT / arguments.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    print("building the agent package")
    _run(
        [
            sys.executable,
            str(REPO_ROOT / "agent/packaging/build_deb.py"),
            "--output-dir",
            str(output_dir),
        ]
    )

    if not arguments.agent_only:
        print(f"building the hub package in {HUB_BUILD_IMAGE}")
        _build_hub(output_dir, arguments.architecture)

    _write_checksums(output_dir)
    return 0


def _build_hub(output_dir: Path, architecture: str) -> None:
    """Build the hub package inside the baseline container.

    Args:
        output_dir: Where the package should land.
        architecture: The Debian architecture to declare.

    Raises:
        SystemExit: If no container tool is available or the build fails.
    """
    engine = _container_engine()
    if engine is None:
        raise SystemExit(
            "podman or docker is needed to build the hub package on its "
            "baseline distribution; pass --agent-only to skip it"
        )
    # --network=host because this machine's own nftables rules are what a
    # container network would otherwise have to negotiate with.
    _run(
        [
            engine,
            "run",
            "--rm",
            "--network=host",
            "-v",
            f"{REPO_ROOT}:/src:ro",
            "-v",
            f"{output_dir}:/out",
            HUB_BUILD_IMAGE,
            "sh",
            "-c",
            CONTAINER_BUILD.format(arch=architecture),
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
        if subprocess.run(["which", name], capture_output=True).returncode == 0:
            return name
    return None


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
