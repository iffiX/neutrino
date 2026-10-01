"""Write SHA256SUMS over every file in a directory of packages.

    python3 packaging/build/build_checksums.py --output-dir dist/

Runs on: any machine with Python 3.11 or newer. The release collects every
package into one directory first and writes the checksums once, over all of
them.

Not pure: writes SHA256SUMS.
"""

import argparse
import hashlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    """Write the checksums.

    Returns:
        The process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--output-dir", default="dist", help="the directory holding the packages"
    )
    arguments = parser.parse_args()
    output_dir = (REPO_ROOT / arguments.output_dir).resolve()
    if not output_dir.is_dir():
        raise SystemExit(f"{output_dir} is not a directory of packages")
    write_checksums(output_dir)
    return 0


def write_checksums(output_dir: Path) -> None:
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


if __name__ == "__main__":
    sys.exit(main())
