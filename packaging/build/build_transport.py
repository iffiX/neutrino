"""Build ``neutrino_transport`` for one target, or for every target.

    python3 packaging/build/build_transport.py --target linux-amd64 --output-dir dist/
    python3 packaging/build/build_transport.py --all --output-dir dist/

Runs on: anywhere with the pinned Go on the path. The binary is static,
``CGO_ENABLED=0``, cross-compiled from ``transport/`` with the package
version stamped by ``-ldflags "-X main.version=..."``, and lands in
``dist/go/<target>/neutrino_transport`` (``.exe`` on Windows), where every
package build of that target takes it from.

Not pure: runs the Go toolchain.
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "packaging"))
from shared import go_build  # noqa: E402
from shared.constants import PACKAGING_GO_TARGETS  # noqa: E402

TRANSPORT_MODULE = REPO_ROOT / "transport"
TRANSPORT_PACKAGE = "./cmd/neutrino_transport"
TRANSPORT_NAME = "neutrino_transport"


def main() -> int:
    """Build the transport for the targets asked.

    Returns:
        The process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--target", choices=PACKAGING_GO_TARGETS, help="one target")
    parser.add_argument("--all", action="store_true", help="every target")
    parser.add_argument(
        "--output-dir", default="dist", help="the build's output directory"
    )
    arguments = parser.parse_args()
    targets = list(PACKAGING_GO_TARGETS) if arguments.all else [arguments.target]
    if targets == [None]:
        parser.error("--target or --all is required")
    for target in targets:
        built = go_build.build_program(
            TRANSPORT_MODULE,
            TRANSPORT_PACKAGE,
            TRANSPORT_NAME,
            target,
            Path(arguments.output_dir),
        )
        print(f"{target}: {built} ({built.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
