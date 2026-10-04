"""The edition table: the one way the rest of the client reaches NetBird.

A left-out feature is one the mainland edition ``cn`` builds without, by
deleting its files from the tree: NetBird. Code outside a feature's own files
never imports them; it asks this table for the hooks of one registration
point and gets those of the present features alone. A feature is present
when its package imports. Every hook is named by its dotted path and
imported on its first lookup, so loading this file imports no feature.

``EDITION`` names the edition, never which features the client has: the
stamp a build writes into ``_version.py``, else the ``EDITION`` file at the
root of a checkout, else ``intl``.
"""

import importlib
import importlib.util
from pathlib import Path

EDITION_INTL = "intl"
EDITION_CN = "cn"
EDITIONS = (EDITION_INTL, EDITION_CN)
# The file at the root of a checkout naming its edition.
EDITION_FILE_NAME = "EDITION"

EDITION_FEATURE_NETBIRD = "netbird"
# Each feature, by the package whose presence is the feature's.
EDITION_FEATURE_PACKAGES = {
    EDITION_FEATURE_NETBIRD: "neutrino_client.netbird",
}

_NETBIRD = EDITION_FEATURE_NETBIRD
# Each registration point, by the hooks the features give it, in the order
# the point takes them. A hook is ``module:attribute``.
EDITION_HOOKS = {
    # core/overlay.py: the drivers of the virtual networks beside EasyTier's,
    # each a class with ``provider``, ``key``, ``network``, ``hub_network``
    # and ``hub_name``.
    "overlay_drivers": (
        (_NETBIRD, "neutrino_client.netbird.driver:OverlayNetbirdDriver"),
    ),
    # core/enrollment.py: the overlay objects a binding keeps beside
    # EasyTier's, as ``{fields, default_modes, optional_fields}``.
    "overlay_objects": (
        (_NETBIRD, "neutrino_client.netbird.constants:NETBIRD_OVERLAY_OBJECT"),
    ),
    # bundled.py: the binaries the packages carry beside the client's own,
    # as ``{system: {binary: path}}``.
    "bundled_paths": (
        (_NETBIRD, "neutrino_client.netbird.constants:NETBIRD_BUNDLED_PATHS"),
    ),
}

_present: dict = {}


def has_feature(name: str) -> bool:
    """Whether a left-out feature is in this tree.

    Args:
        name: ``netbird``.

    Returns:
        True when the feature's package imports.

    Raises:
        KeyError: When ``name`` is no feature.
    """
    package = EDITION_FEATURE_PACKAGES[name]
    if package not in _present:
        try:
            _present[package] = importlib.util.find_spec(package) is not None
        except ImportError:
            _present[package] = False
    return _present[package]


def hooks(point: str) -> tuple:
    """The hooks the present features give one registration point.

    Args:
        point: A key of :data:`EDITION_HOOKS`.

    Returns:
        Each present feature's hook, imported, in the table's order; empty
        when no present feature gives the point one.

    Raises:
        KeyError: When ``point`` is no registration point.
    """
    return tuple(
        _load(target)
        for feature, target in EDITION_HOOKS[point]
        if has_feature(feature)
    )


def _load(target: str):
    """Import one hook by its ``module:attribute`` path."""
    module_name, _, attribute = target.partition(":")
    return getattr(importlib.import_module(module_name), attribute)


def _checkout_edition() -> str:
    """The edition the root ``EDITION`` file of a checkout names.

    Returns:
        ``intl`` or ``cn``; ``intl`` when the file is missing or names
        neither.
    """
    path = Path(__file__).resolve().parents[3] / EDITION_FILE_NAME
    try:
        named = path.read_text(encoding="utf-8").strip()
    except OSError:
        return EDITION_INTL
    return named if named in EDITIONS else EDITION_INTL


try:  # Written into the tree when a package is built.
    from neutrino_client._version import EDITION
except ImportError:
    EDITION = _checkout_edition()
