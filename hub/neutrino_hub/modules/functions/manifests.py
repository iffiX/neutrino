"""Reading the function manifests.

The manifests under ``manifests/`` are the functions half of the device
catalog: one JSON per function saying, per platform, how it is obtained.
Comment keys are stripped the same way the rest of ``config/`` is.
"""

import json

from neutrino_hub.utils.constants import UTILS_DATA_DIR
from neutrino_hub.utils.json_file import strip_comments

MANIFESTS_DIR = UTILS_DATA_DIR / "manifests"


def load_function_manifests() -> dict:
    """Read every manifest, keyed by function name.

    Returns:
        Function name to its parsed manifest, comment keys removed.
    """
    manifests = {}
    if not MANIFESTS_DIR.is_dir():
        return manifests
    for path in sorted(MANIFESTS_DIR.glob("*.json")):
        try:
            manifest = strip_comments(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
        name = manifest.get("name")
        if name:
            manifests[name] = manifest
    return manifests


def manifests_stamp() -> tuple:
    """A cheap fingerprint of the manifest files, for cache keys.

    Returns:
        A tuple that changes whenever a manifest is added, removed or edited.
    """
    if not MANIFESTS_DIR.is_dir():
        return ()
    entries = []
    for path in sorted(MANIFESTS_DIR.glob("*.json")):
        try:
            stat = path.stat()
        except OSError:
            continue
        entries.append((path.name, stat.st_mtime_ns, stat.st_size))
    return tuple(entries)
