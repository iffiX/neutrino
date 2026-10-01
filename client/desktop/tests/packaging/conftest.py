"""The build scripts on the import path, the way they put each other there.

``client/desktop/packaging``, the repository's own ``packaging`` and its
``build`` directory are not packages — importing either of the first two as
one would shadow the ``packaging`` distribution the tooling itself uses — so
all three go on the path. The package's own modules and the target scripts
are imported by their own names, the shared ones as ``shared.<module>``.
"""

import sys
from pathlib import Path

PACKAGING_DIR = Path(__file__).resolve().parent.parent.parent / "packaging"
SHARED_PACKAGING_DIR = PACKAGING_DIR.parents[2] / "packaging"
BUILD_SCRIPTS_DIR = SHARED_PACKAGING_DIR / "build"

for directory in (SHARED_PACKAGING_DIR, BUILD_SCRIPTS_DIR, PACKAGING_DIR):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
