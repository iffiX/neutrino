"""Check and build the documentation site under docs/guide.

    python3 packaging/build/build_docs.py --base /neutrino/

Runs on: any machine with Node 24 or newer and Python 3.11 or newer. Runs
``npm ci`` when ``--install`` is given, then ``npm run check`` (formatting,
lint, types and the screenshot list), then ``npm run build`` once for each
``--base``, the path the site is served under. The site is written to
``docs/guide/.vitepress/dist``.

Not pure: runs npm, writes the site.
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_DIR = REPO_ROOT / "docs" / "guide"

# What the site's configuration reads as the path it is served under.
DOCS_BASE_ENV = "NEUTRINO_DOCS_BASE"


def main() -> int:
    """Check and build the site.

    Returns:
        The process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--base",
        action="append",
        default=[],
        help="the path the site is served under; repeat to build for several",
    )
    parser.add_argument(
        "--install", action="store_true", help="run npm ci before anything else"
    )
    arguments = parser.parse_args()
    for tool in ("node", "npm"):
        if shutil.which(tool) is None:
            raise SystemExit(f"{tool} is needed and is not on the path")

    if arguments.install:
        _npm(["ci"])
    _npm(["run", "check"])
    for base in arguments.base or ["/"]:
        print(f"building the site for {base}")
        _npm(["run", "build"], {DOCS_BASE_ENV: base})
    return 0


def _npm(arguments: list, environment: "dict | None" = None) -> None:
    """Run one npm command in the site's directory.

    Args:
        arguments: What follows ``npm``.
        environment: Variables added to this process's own.

    Raises:
        SystemExit: When it fails.
    """
    result = subprocess.run(
        ["npm", *arguments],
        cwd=DOCS_DIR,
        env=dict(os.environ, **(environment or {})),
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"npm {' '.join(arguments)} exited {result.returncode}")


if __name__ == "__main__":
    sys.exit(main())
