"""Reading the device module manifests.

The manifests under ``manifests/`` are the modules half of the device
catalog: one JSON per module saying, per platform, how it is obtained or
detected. Every manifest names its ``installer`` tier; one that does not is
refused at load, so a wrong file fails the suite instead of shipping.
Comment keys are stripped the same way the rest of ``config/`` is.
"""

import json

from neutrino_hub.modules.devices.constants import AGENT_MODULE_INSTALLER_TIERS
from neutrino_hub.utils.constants import UTILS_DATA_DIR
from neutrino_hub.utils.json_file import strip_comments

MANIFESTS_DIR = UTILS_DATA_DIR / "manifests"


def load_module_manifests() -> dict:
    """Read every manifest, keyed by module name.

    Returns:
        Module name to its parsed manifest, comment keys removed.

    Raises:
        ValueError: For a manifest whose ``installer`` is missing or not one
            of the tiers.
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
        if not name:
            continue
        installer = manifest.get("installer")
        if installer not in AGENT_MODULE_INSTALLER_TIERS:
            raise ValueError(
                f"manifest {path.name}: installer must be one of "
                f"{', '.join(AGENT_MODULE_INSTALLER_TIERS)}, not {installer!r}"
            )
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
