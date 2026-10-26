"""The build scripts on the import path, the way they put each other there.

``agent/packaging``, the repository's own ``packaging`` and its ``build``
directory are not packages — importing either of the first two as one would
shadow the ``packaging`` distribution the tooling itself uses — so all three
go on the path. The package's own modules and the target scripts are
imported by their own names, the shared ones as ``shared.<module>``. The
Go programs every package carries are stood in for under a temporary
``dist/go``.
"""

import sys
from pathlib import Path

import pytest

PACKAGING_DIR = Path(__file__).resolve().parent.parent.parent / "packaging"
SHARED_PACKAGING_DIR = PACKAGING_DIR.parent.parent / "packaging"
BUILD_SCRIPTS_DIR = SHARED_PACKAGING_DIR / "build"

for directory in (SHARED_PACKAGING_DIR, BUILD_SCRIPTS_DIR, PACKAGING_DIR):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))


@pytest.fixture(autouse=True)
def go_programs(tmp_path_factory, monkeypatch):
    """The Go programs of every target, as ``dist/go/<target>/`` holds them.

    Returns:
        The directory standing in for ``dist/go``.
    """
    import payload
    from shared.constants import PACKAGING_GO_TARGETS

    root = tmp_path_factory.mktemp("go")
    for target in PACKAGING_GO_TARGETS:
        extension = ".exe" if target.startswith("windows-") else ""
        (root / target).mkdir()
        for name in payload.GO_PROGRAM_NAMES:
            (root / target / f"{name}{extension}").write_bytes(
                f"{name} for {target}".encode()
            )
    monkeypatch.setattr(payload, "GO_PROGRAMS_ROOT", root)
    return root
