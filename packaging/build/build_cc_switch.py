"""Write the pinned cc-switch release files, with their licence, into a
directory of release files.

    python3 packaging/build/build_cc_switch.py --edition cn --output-dir dist_cn/

Runs on: any machine with Python 3.11 or newer. Each file comes from the
pinned upstream url in ``packaging/shared/constants.py``, under the name
upstream gives it, and is checked against its pinned sha256; the licence goes
beside them as ``cc-switch-cli-v<version>-LICENSE.txt``. The mainland release
attaches them all, for the hubs of its edition to fetch. Run it before
``build_checksums.py``, so ``SHA256SUMS`` lists them.

Not pure: downloads, writes files.
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "packaging"))
from shared import cc_switch_assets  # noqa: E402
from shared import edition_build  # noqa: E402


def main() -> int:
    """Write the files.

    Returns:
        The process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    edition_build.add_edition_argument(parser)
    parser.add_argument(
        "--output-dir", default="dist", help="the directory of release files"
    )
    arguments = parser.parse_args()
    edition_build.require_edition_tree(arguments.edition)
    output_dir = (REPO_ROOT / arguments.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    for path in cc_switch_assets.write_release_files(output_dir):
        print(f"wrote {path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
