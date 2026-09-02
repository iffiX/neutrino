"""Build the installable agent tarball.

The gateway uploads this archive to a device and runs the ``install.sh`` inside
it:

    python3 -m neutrino_agent.build_package
    python3 -m neutrino_agent.build_package --output-dir <dir>
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import argparse
import sys
import tarfile
from pathlib import Path

from neutrino_agent import AGENT_VERSION

# --- config ---
REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_MEMBERS = ("neutrino_agent", "systemd", "desktop", "install.sh")
EXCLUDED_NAMES = ("__pycache__", ".pyc")


def main() -> int:
    """Write the tarball.

    Returns:
        Process exit status: 0 on success, 1 when a member is missing.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default=str(REPO_ROOT / "dist"),
        help="where to write the archive (default: dist/)",
    )
    parser.add_argument(
        "--latest",
        action="store_true",
        default=True,
        help="also write neutrino_agent-latest.tar.gz beside the versioned file",
    )
    args = parser.parse_args()

    for name in PACKAGE_MEMBERS:
        if not (REPO_ROOT / name).exists():
            print(f"error: missing {name} in {REPO_ROOT}", file=sys.stderr)
            return 1

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    versioned_path = output_dir / f"neutrino_agent-{AGENT_VERSION}.tar.gz"
    _write_archive(versioned_path)
    print(f"wrote {versioned_path} ({versioned_path.stat().st_size} bytes)")

    if args.latest:
        latest_path = output_dir / "neutrino_agent-latest.tar.gz"
        _write_archive(latest_path)
        print(f"wrote {latest_path}")
    return 0


def _write_archive(path: Path) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for name in PACKAGE_MEMBERS:
            archive.add(REPO_ROOT / name, arcname=name, filter=_exclude_build_artifacts)


def _exclude_build_artifacts(entry: tarfile.TarInfo) -> tarfile.TarInfo | None:
    if any(marker in entry.name for marker in EXCLUDED_NAMES):
        return None
    entry.uid = 0
    entry.gid = 0
    entry.uname = "root"
    entry.gname = "root"
    return entry


if __name__ == "__main__":
    sys.exit(main())
