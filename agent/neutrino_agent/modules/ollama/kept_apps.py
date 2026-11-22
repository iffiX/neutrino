"""The record of the publisher's Ollama app taken over on Windows and macOS.

One JSON file under the module's ``kept/`` folder holds, by account, what
the take-over found: whether the app ran, and what of its start at login
was kept aside, so an uninstall gives back what it took and nothing else.

Not pure: reads and writes the record.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import json
import os


def read_kept(path: str) -> dict:
    """The accounts taken over, by name.

    Args:
        path: The record's file.

    Returns:
        Each account's record; empty when there is no record.
    """
    try:
        with open(path, encoding="utf-8") as stream:
            held = json.load(stream)
    except (OSError, ValueError):
        return {}
    return held if isinstance(held, dict) else {}


def write_kept(path: str, records: dict) -> None:
    """Write the accounts taken over, the folder made first, readable by root alone.

    Args:
        path: The record's file.
        records: Each account's record, by name.

    Raises:
        OSError: When the record cannot be written.
    """
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    with open(path, "w", encoding="utf-8") as stream:
        json.dump(records, stream, indent=2, sort_keys=True)
