"""Reading the feature manifests and describing them to agents.

The manifests under ``manifests/`` are the whole catalog: one JSON per feature
saying, per platform, how it is obtained. The gateway reads them, hashes the
set so an agent can tell when its copy is stale, and lists them for the panel.
Comment keys are stripped the same way the rest of ``config/`` is.
"""

import hashlib
import json

from neutrino_hub.utils.constants import UTILS_DATA_DIR
from neutrino_hub.utils.json_file import strip_comments

MANIFESTS_DIR = UTILS_DATA_DIR / "manifests"


def load_catalog() -> dict:
    """Read every manifest, keyed by feature name.

    Returns:
        Feature name to its parsed manifest, comment keys removed.
    """
    catalog = {}
    if not MANIFESTS_DIR.is_dir():
        return catalog
    for path in sorted(MANIFESTS_DIR.glob("*.json")):
        try:
            manifest = strip_comments(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
        name = manifest.get("name")
        if name:
            catalog[name] = manifest
    return catalog


def catalog_hash(catalog: dict) -> str:
    """A stable hash of the catalog, for staleness checks.

    Args:
        catalog: The catalog from :func:`load_catalog`.

    Returns:
        A short hex digest that changes whenever any manifest does.
    """
    serialized = json.dumps(catalog, sort_keys=True).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()[:16]
