"""Reading the device module manifests.

The manifests under ``manifests/`` are the modules half of the device
catalog: one JSON per module saying, per platform, how it is obtained or
detected. Every manifest names its ``installer`` tier and its ``source``;
one that does not is refused at load, so a wrong file fails the suite
instead of shipping. Comment keys are stripped the same way the rest of
``config/`` is.

**They come back in the order both surfaces draw them**: the tiers in the
order a person trusts them — what the machine's own package manager
provides, then what the module's installer fetches from a public
repository, then what
somebody installs from a vendor themselves — and by title inside each. The
panel and the agent's page read this same order, so the two lists agree
without either of them sorting.
"""

import json
import re

from neutrino_hub.modules.devices.constants import (
    AGENT_MODULE_DOWNLOAD_FIELDS,
    AGENT_MODULE_INSTALLER_BUILTIN,
    AGENT_MODULE_INSTALLER_TIERS,
    AGENT_MODULE_INSTALLER_USER,
)
from neutrino_hub.utils.constants import UTILS_DATA_DIR
from neutrino_hub.utils.json_file import strip_comments

MANIFESTS_DIR = UTILS_DATA_DIR / "manifests"
# What a platform branch's ``min_version`` looks like: 2.28, 26100, 12.3.
MANIFEST_VERSION_PATTERN = r"\d+(\.\d+)*"


def load_module_manifests() -> dict:
    """Read every manifest, keyed by module name, in display order.

    Returns:
        Module name to its parsed manifest, comment keys removed, ordered by
        installer tier and then by title.

    Raises:
        ValueError: For a manifest whose ``installer`` is missing or not one
            of the tiers, which names no ``source``, or whose platform
            branch lacks what the agent is sent: ``verify``, and for a
            module the hub installs, an ``uninstall`` block.
    """
    loaded = []
    if not MANIFESTS_DIR.is_dir():
        return {}
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
        if not str(manifest.get("source", "") or ""):
            raise ValueError(
                f"manifest {path.name}: source must name where the software "
                f"comes from — a repository, a vendor, or 'system'"
            )
        _check_branches(path.name, manifest)
        loaded.append((name, manifest))
    loaded.sort(
        key=lambda pair: (
            AGENT_MODULE_INSTALLER_TIERS.index(pair[1]["installer"]),
            str(pair[1].get("title", pair[0])).lower(),
        )
    )
    return dict(loaded)


def _check_branches(file_name: str, manifest: dict) -> None:
    """Refuse a platform branch the agent could not act on.

    Every branch that names software carries ``verify``, the command whose
    exit says whether the software is there. A module the hub installs
    carries an ``uninstall`` block too: the packages to take off, the
    commands to run after, and whether the module's data stays. A branch
    that is ``{}`` says the platform carries the software natively. A branch
    whose ``installer`` is ``builtin`` names software the system carries,
    which the agent's runner checks for itself: it names nothing to
    download or install and needs neither ``verify`` nor ``uninstall``.

    Args:
        file_name: The manifest's file, for the message.
        manifest: The parsed manifest.

    Raises:
        ValueError: Naming the branch and what it lacks, a
            ``min_version`` that is not a dotted number, an ``installer``
            other than ``builtin``, or a builtin branch naming something
            to download or install.
    """
    is_installed_by_hub = manifest.get("installer") != AGENT_MODULE_INSTALLER_USER
    platforms = manifest.get("platforms", {})
    if not isinstance(platforms, dict):
        raise ValueError(f"manifest {file_name}: platforms must be an object")
    for key, entry in platforms.items():
        if not isinstance(entry, dict):
            raise ValueError(f"manifest {file_name}: platform {key} must be an object")
        if entry == {}:
            continue
        floor = entry.get("min_version")
        if floor is not None and not (
            isinstance(floor, str) and re.fullmatch(MANIFEST_VERSION_PATTERN, floor)
        ):
            raise ValueError(
                f"manifest {file_name}: platform {key} min_version must be a "
                f"dotted number, not {floor!r}"
            )
        if "installer" in entry:
            if entry["installer"] != AGENT_MODULE_INSTALLER_BUILTIN:
                raise ValueError(
                    f"manifest {file_name}: platform {key} installer must be "
                    f"{AGENT_MODULE_INSTALLER_BUILTIN!r}, not {entry['installer']!r}"
                )
            named = [field for field in AGENT_MODULE_DOWNLOAD_FIELDS if field in entry]
            if named:
                raise ValueError(
                    f"manifest {file_name}: platform {key} is builtin and names "
                    f"nothing to download or install, not {', '.join(named)}"
                )
            continue
        if not str(entry.get("verify", "") or ""):
            raise ValueError(
                f"manifest {file_name}: platform {key} must name a verify command"
            )
        if not is_installed_by_hub:
            continue
        removal = entry.get("uninstall")
        is_shaped = (
            isinstance(removal, dict)
            and isinstance(removal.get("packages"), list)
            and isinstance(removal.get("post_uninstall"), list)
            and isinstance(removal.get("is_data_kept"), bool)
        )
        if not is_shaped:
            raise ValueError(
                f"manifest {file_name}: platform {key} must carry an uninstall "
                "block with packages, post_uninstall and is_data_kept"
            )


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
