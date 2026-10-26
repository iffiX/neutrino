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


import pytest  # noqa: E402

# The targets the release builds the Go programs for.
GO_TARGETS = (
    "linux-amd64",
    "linux-arm64",
    "windows-amd64",
    "darwin-arm64",
    "darwin-amd64",
)


@pytest.fixture(autouse=True)
def go_programs(tmp_path, monkeypatch):
    """The transport the release built for every target, under a temporary dist/go."""
    import payload

    root = tmp_path / "dist" / "go"
    for target in GO_TARGETS:
        name = (
            "neutrino_transport.exe"
            if target.startswith("windows")
            else ("neutrino_transport")
        )
        program = root / target / name
        program.parent.mkdir(parents=True)
        program.write_bytes(b"transport for " + target.encode())
    monkeypatch.setattr(payload, "GO_PROGRAMS_DIR", root)
    return root
