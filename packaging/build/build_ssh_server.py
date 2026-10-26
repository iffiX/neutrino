"""Build ``neutrino_ssh_server``, the agent's SSH server, for one target or all.

    python3 packaging/build/build_ssh_server.py --target linux-amd64 --output-dir dist/
    python3 packaging/build/build_ssh_server.py --all --output-dir dist/

Runs on: anywhere with the pinned Go on the path. The binary is static,
``CGO_ENABLED=0``, cross-compiled from ``agent/sshserver/`` with the package
version stamped, and lands in ``dist/go/<target>/neutrino_ssh_server``
(``.exe`` on Windows), beside ``neutrino_transport``.

Not pure: runs the Go toolchain.
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "packaging"))
from shared import edition_build, go_build  # noqa: E402
from shared.constants import PACKAGING_GO_TARGETS  # noqa: E402

SSH_SERVER_MODULE = REPO_ROOT / "agent" / "sshserver"
SSH_SERVER_PACKAGE = "./cmd/neutrino_ssh_server"
SSH_SERVER_NAME = "neutrino_ssh_server"


def main() -> int:
    """Build the SSH server for the targets asked.

    Returns:
        The process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    edition_build.add_edition_argument(parser)
    parser.add_argument("--target", choices=PACKAGING_GO_TARGETS, help="one target")
    parser.add_argument("--all", action="store_true", help="every target")
    parser.add_argument(
        "--output-dir", default="dist", help="the build's output directory"
    )
    arguments = parser.parse_args()
    edition_build.require_edition_tree(arguments.edition)
    targets = list(PACKAGING_GO_TARGETS) if arguments.all else [arguments.target]
    if targets == [None]:
        parser.error("--target or --all is required")
    if not (SSH_SERVER_MODULE / "go.mod").exists():
        raise SystemExit(f"{SSH_SERVER_MODULE} holds no Go module")
    for target in targets:
        built = go_build.build_program(
            SSH_SERVER_MODULE,
            SSH_SERVER_PACKAGE,
            SSH_SERVER_NAME,
            target,
            Path(arguments.output_dir),
        )
        print(f"{target}: {built} ({built.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
