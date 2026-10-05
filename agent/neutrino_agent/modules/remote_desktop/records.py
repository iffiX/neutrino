"""The Remote desktop module's records under the state root, read and
written whole.

Not pure: reads and writes files.
"""

import json
import os


def read_json(path: str) -> dict:
    """One record.

    Args:
        path: The file.

    Returns:
        Its object; empty when the file is missing or holds no object.
    """
    try:
        with open(path, "r", encoding="utf-8") as stream:
            data = json.load(stream)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_json(path: str, data: dict) -> None:
    """Write one record where only root reads it.

    Args:
        path: The file.
        data: The object.

    Raises:
        OSError: When the file cannot be written.
    """
    directory = os.path.dirname(path)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    temporary = f"{path}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, sort_keys=True)
    os.replace(temporary, path)
