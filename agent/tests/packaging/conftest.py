"""The build scripts on the import path, the way they put each other there.

``agent/packaging``, the repository's own ``packaging`` and its ``build``
directory are not packages — importing either of the first two as one would
shadow the ``packaging`` distribution the tooling itself uses — so all three
go on the path. The package's own modules and the target scripts are
imported by their own names, the shared ones as ``shared.<module>``.
"""

import io
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

PACKAGING_DIR = Path(__file__).resolve().parent.parent.parent / "packaging"
SHARED_PACKAGING_DIR = PACKAGING_DIR.parent.parent / "packaging"
BUILD_SCRIPTS_DIR = SHARED_PACKAGING_DIR / "build"

for directory in (SHARED_PACKAGING_DIR, BUILD_SCRIPTS_DIR, PACKAGING_DIR):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))


@pytest.fixture(autouse=True)
def cc_switch_fetched(monkeypatch):
    """Every cc-switch download answered from memory, shaped as upstream
    ships it; the urls asked for, in order."""
    from shared import cc_switch_assets

    asked = []

    def fetch(url, digest):
        asked.append(url)
        buffer = io.BytesIO()
        if url.endswith(".zip"):
            with zipfile.ZipFile(buffer, "w") as bundle:
                bundle.writestr("cc-switch.exe", b"MZ cc-switch")
        else:
            with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
                info = tarfile.TarInfo("cc-switch")
                info.size = len(b"cc-switch")
                info.mode = 0o644
                bundle.addfile(info, io.BytesIO(b"cc-switch"))
        return buffer.getvalue()

    monkeypatch.setattr(cc_switch_assets, "_fetch", fetch)
    return asked
