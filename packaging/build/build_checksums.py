"""Write latest.json and SHA256SUMS over every file in a directory of
release files.

    python3 packaging/build/build_checksums.py --output-dir dist/

Runs on: any machine with Python 3.11 or newer. The release collects every
file of both editions into one directory first and writes these two once,
over all of them: ``latest.json`` names the release as ``{tag, version}``,
the tag being ``v`` and the version the packages declare, and
``SHA256SUMS`` lists every file of the directory, ``latest.json`` among
them.

Not pure: writes latest.json and SHA256SUMS.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "packaging"))
from build_sources import version  # noqa: E402
from shared import edition_build  # noqa: E402
from shared.constants import PACKAGING_LATEST_FILE  # noqa: E402

# The file the checksums are written into.
CHECKSUMS_FILE = "SHA256SUMS"


def main() -> int:
    """Write the two files.

    Returns:
        The process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    edition_build.add_edition_argument(parser)
    parser.add_argument(
        "--output-dir", default="dist", help="the directory holding the release files"
    )
    arguments = parser.parse_args()
    edition_build.require_edition_tree(arguments.edition)
    output_dir = (REPO_ROOT / arguments.output_dir).resolve()
    if not output_dir.is_dir():
        raise SystemExit(f"{output_dir} is not a directory of release files")
    write_latest(output_dir, version())
    write_checksums(output_dir)
    return 0


def write_latest(output_dir: Path, package_version: str) -> Path:
    """Write ``latest.json``, which names the release.

    Args:
        output_dir: The directory holding the release files.
        package_version: The version the packages declare.

    Returns:
        The file written.
    """
    target = output_dir / PACKAGING_LATEST_FILE
    target.write_text(
        json.dumps({"tag": f"v{package_version}", "version": package_version}) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {target}")
    return target


def write_checksums(output_dir: Path) -> None:
    """Write SHA256SUMS beside the release files.

    The hub verifies this before installing an agent on a device, so a
    truncated download fails loudly instead of half-installing.

    Args:
        output_dir: The directory holding the release files.
    """
    lines = []
    for path in sorted(output_dir.iterdir()):
        if path.name == CHECKSUMS_FILE or not path.is_file():
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.name}")
        print(f"  {path.name}  {path.stat().st_size // 1024} KiB")
    (output_dir / CHECKSUMS_FILE).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {output_dir / CHECKSUMS_FILE}")


if __name__ == "__main__":
    sys.exit(main())
