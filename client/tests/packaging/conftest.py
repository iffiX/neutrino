"""The build scripts on the import path, the way they put each other there.

``client/packaging`` is scripts rather than a package — importing it as one
would shadow the ``packaging`` distribution the tooling itself uses — so the
directory goes on the path and its modules are imported by their own names.
"""

import sys
from pathlib import Path

PACKAGING_DIR = Path(__file__).resolve().parent.parent.parent / "packaging"

if str(PACKAGING_DIR) not in sys.path:
    sys.path.insert(0, str(PACKAGING_DIR))
