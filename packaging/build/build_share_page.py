"""Assemble the App share page into the tree a static host serves.

    python3 packaging/build/build_share_page.py --output-dir dist/share_page/

Runs on: any machine with Python 3.11 or newer. The tree is what Cloudflare
Pages and EdgeOne Pages publish as they are: the shell page at the root,
which the host also serves for every path it holds no file for, the page's
three scripts under ``__neutrino/``, and the host's header file at the root,
``_headers`` for Cloudflare Pages and ``edgeone.json`` for EdgeOne Pages,
each sending ``Service-Worker-Allowed: /`` with ``sw.js``. Each script is
named with ``?v=`` and the first 10 hex characters of its content's sha256.
Nothing is deployed.

Not pure: writes the output directory.
"""

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "packaging"))
from shared import edition_build  # noqa: E402

SHARE_PAGE_DIR = REPO_ROOT / "share_page"
# The directory of the site the page's scripts are served from.
SHARE_PAGE_PREFIX = "__neutrino"
SHARE_PAGE_FILES = ("index.html", "shell.js", "sw.js", "shim.js")
# The files each host reads from the site's root.
SHARE_PAGE_HOST_FILES = ("_headers", "edgeone.json")
# Each script and the file that names its address, in build order. A file is
# hashed after the address it names carries its fingerprint.
SHARE_PAGE_SCRIPT_NAMERS = (
    ("shim.js", "sw.js"),
    ("sw.js", "shell.js"),
    ("shell.js", "index.html"),
)
# Hex characters of a script's sha256 in its address.
SHARE_PAGE_FINGERPRINT_CHARS = 10


def main() -> int:
    """Write the tree.

    Returns:
        The process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    edition_build.add_edition_argument(parser)
    parser.add_argument(
        "--output-dir",
        default="dist/share_page",
        help="the directory the tree is written into, emptied first",
    )
    arguments = parser.parse_args()
    edition_build.require_edition_tree(arguments.edition)
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

    Raises:
        SystemExit: When a file does not name a script's address exactly once.
    """
    contents = {name: (SHARE_PAGE_DIR / name).read_bytes() for name in SHARE_PAGE_FILES}
    for script, namer in SHARE_PAGE_SCRIPT_NAMERS:
        contents[namer] = fingerprint_address(contents[namer], script, contents[script])
    if output_dir.exists():
        shutil.rmtree(output_dir)
    page_dir = output_dir / SHARE_PAGE_PREFIX
    page_dir.mkdir(parents=True)
    for name, content in contents.items():
        target = output_dir if name == "index.html" else page_dir
        (target / name).write_bytes(content)
    for name in SHARE_PAGE_HOST_FILES:
        shutil.copyfile(SHARE_PAGE_DIR / name, output_dir / name)
    return output_dir


def fingerprint_address(namer: bytes, script: str, content: bytes) -> bytes:
    """Add a script's fingerprint to its quoted address in the file that names it.

    Args:
        namer: The content of the file that names the script.
        script: The script's file name.
        content: The script's content.

    Returns:
        The namer's content with ``?v=<fingerprint>`` after the address.

    Raises:
        SystemExit: When the namer does not hold the address exactly once.
    """
    address = f'"/{SHARE_PAGE_PREFIX}/{script}"'.encode()
    count = namer.count(address)
    if count != 1:
        raise SystemExit(
            f"the share page names {address.decode()} {count} times; it must name it once"
        )
    fingerprint = hashlib.sha256(content).hexdigest()[:SHARE_PAGE_FINGERPRINT_CHARS]
    named = f'"/{SHARE_PAGE_PREFIX}/{script}?v={fingerprint}"'.encode()
    return namer.replace(address, named)


if __name__ == "__main__":
    sys.exit(main())
