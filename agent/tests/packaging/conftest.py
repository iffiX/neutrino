"""The build scripts on the import path, the way they put each other there.

``agent/packaging`` and the repository's own ``packaging`` are not packages —
importing either as one would shadow the ``packaging`` distribution the
tooling itself uses — so both directories go on the path. The package's own
modules are imported by their own names, the shared ones as
``shared.<module>``.
"""

import sys
from pathlib import Path

PACKAGING_DIR = Path(__file__).resolve().parent.parent.parent / "packaging"
SHARED_PACKAGING_DIR = PACKAGING_DIR.parent.parent / "packaging"

for directory in (SHARED_PACKAGING_DIR, PACKAGING_DIR):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
