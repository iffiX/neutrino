"""The edition the client was built as, which chooses where it fetches from.

``EDITION`` is the stamp a build writes into ``_version.py``, else the
``EDITION`` file at the root of a checkout, else ``intl``. The client leaves
nothing out in either edition.
"""

from pathlib import Path

EDITION_INTL = "intl"
EDITION_CN = "cn"
EDITIONS = (EDITION_INTL, EDITION_CN)
# The file at the root of a checkout naming its edition.
EDITION_FILE_NAME = "EDITION"


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
