"""Check and build the documentation site under docs.

    python3 packaging/build/build_docs.py --base /neutrino/

Runs on: any machine with Node 24 or newer and Python 3.11 or newer. Runs
``npm ci`` in ``docs`` and in ``hub/frontend`` when ``--install`` is given,
then ``npm run check`` (formatting, lint, types and the page check), then
``npm run demo:build`` in ``hub/frontend``, which type-checks and builds the
panel demo into ``demo/dist``, then ``npm run build`` once for each
``--base``, the path the site is served under, with the demo copied into the
site's ``demo/``. The site is written to ``docs/.vitepress/dist``.

Not pure: runs npm, writes the demo and the site.
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "packaging"))
from shared import edition_build  # noqa: E402

DOCS_DIR = REPO_ROOT / "docs"
DOCS_SITE_DIR = DOCS_DIR / ".vitepress" / "dist"
# The panel demo: built in the panel's directory, which holds its packages.
DOCS_FRONTEND_DIR = REPO_ROOT / "hub" / "frontend"
DOCS_DEMO_BUILD_DIR = REPO_ROOT / "demo" / "dist"
DOCS_DEMO_SITE_PATH = "demo"

# What the site's configuration reads as the path it is served under.
DOCS_BASE_ENV = "NEUTRINO_DOCS_BASE"


def main() -> int:
    """Check and build the site.

    Returns:
        The process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    edition_build.add_edition_argument(parser)
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
    edition_build.require_edition_tree(arguments.edition)
    for tool in ("node", "npm"):
        if shutil.which(tool) is None:
            raise SystemExit(f"{tool} is needed and is not on the path")

    if arguments.install:
        _npm(["ci"])
        _npm(["ci"], directory=DOCS_FRONTEND_DIR)
    _npm(["run", "check"])
    print("building the panel demo", flush=True)
    _npm(["run", "demo:build"], directory=DOCS_FRONTEND_DIR)
    for base in arguments.base or ["/"]:
        print(f"building the site for {base}", flush=True)
        _npm(["run", "build"], {DOCS_BASE_ENV: base})
        shutil.copytree(DOCS_DEMO_BUILD_DIR, DOCS_SITE_DIR / DOCS_DEMO_SITE_PATH)
    return 0


def _npm(
    arguments: list,
    environment: "dict | None" = None,
    directory: Path = DOCS_DIR,
) -> None:
    """Run one npm command, in the site's directory unless another is named.

    Args:
        arguments: What follows ``npm``.
        environment: Variables added to this process's own.
        directory: The directory npm runs in.

    Raises:
        SystemExit: When it fails.
    """
    result = subprocess.run(
        ["npm", *arguments],
        cwd=directory,
        env=dict(os.environ, **(environment or {})),
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"npm {' '.join(arguments)} exited {result.returncode}")


if __name__ == "__main__":
    sys.exit(main())
