"""Assemble the Web share page into the tree a static host serves.

    python3 packaging/build/build_share_page.py --output-dir dist/share_page/

Runs on: any machine with Python 3.11 or newer. The tree is what Cloudflare
Pages and EdgeOne Pages publish as they are: the page's four files under
``__neutrino/``, the shell page again at the root, which the host serves for
every path it holds no file for, and the host's header file at the root,
``_headers`` for Cloudflare Pages and ``edgeone.json`` for EdgeOne Pages,
each sending ``Service-Worker-Allowed: /`` with ``sw.js``. Nothing is
deployed.

Not pure: writes the output directory.
"""

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SHARE_PAGE_DIR = REPO_ROOT / "share_page"
# The directory of the site the page is served from.
SHARE_PAGE_PREFIX = "__neutrino"
SHARE_PAGE_FILES = ("index.html", "shell.js", "sw.js", "shim.js")
# The files each host reads from the site's root.
SHARE_PAGE_HOST_FILES = ("_headers", "edgeone.json")


def main() -> int:
    """Write the tree.

    Returns:
        The process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--output-dir",
        default="dist/share_page",
        help="the directory the tree is written into, emptied first",
    )
    arguments = parser.parse_args()
    built = assemble((REPO_ROOT / arguments.output_dir).resolve())
    for path in sorted(built.rglob("*")):
        if path.is_file():
            print(f"{path.relative_to(built)} ({path.stat().st_size} bytes)")
    return 0


def assemble(output_dir: Path) -> Path:
    """Write the site's tree into one directory.

    Args:
        output_dir: The directory, emptied first.

    Returns:
        The directory written.
    """
    if output_dir.exists():
        shutil.rmtree(output_dir)
    page_dir = output_dir / SHARE_PAGE_PREFIX
    page_dir.mkdir(parents=True)
    for name in SHARE_PAGE_FILES:
        shutil.copyfile(SHARE_PAGE_DIR / name, page_dir / name)
    shutil.copyfile(SHARE_PAGE_DIR / "index.html", output_dir / "index.html")
    for name in SHARE_PAGE_HOST_FILES:
        shutil.copyfile(SHARE_PAGE_DIR / name, output_dir / name)
    return output_dir


if __name__ == "__main__":
    sys.exit(main())
