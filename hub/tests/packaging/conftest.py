"""The build scripts on the import path, the way they put each other there.

``hub/packaging`` is scripts rather than a package — importing it as one would
shadow the ``packaging`` distribution the tooling itself uses — so the
directory goes on the path and its modules are imported by their own names.
The repository's own ``packaging`` and its ``build`` directory go there too,
the shared modules imported as ``shared.<module>`` and the target scripts by
their own names.
"""

import sys
from pathlib import Path

PACKAGING_DIR = Path(__file__).resolve().parent.parent.parent / "packaging"
SHARED_PACKAGING_DIR = PACKAGING_DIR.parent.parent / "packaging"
BUILD_SCRIPTS_DIR = SHARED_PACKAGING_DIR / "build"

for directory in (SHARED_PACKAGING_DIR, BUILD_SCRIPTS_DIR, PACKAGING_DIR):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
