"""Reading and writing the JSON files under ``config/``.

``config/`` is the single source of truth for the appliance, so every read goes
through here: keys beginning with an underscore are documentation comments in
the example files and are stripped before the data reaches any library.
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from neutrino_hub.utils.constants import UTILS_CONFIG_DIR


def read_config(relative_path: str) -> dict[str, Any]:
    """Read one JSON file from ``config/``.

    Args:
        relative_path: Path below ``config/``, for example ``xray/nodes.json``.

    Returns:
        The parsed object with comment keys removed.

    Raises:
        FileNotFoundError: If the file does not exist. The installer copies the
            matching ``.example.json`` on first run, so a miss here means setup
            was skipped.
        ValueError: If the file is not valid JSON.
    """
    path = UTILS_CONFIG_DIR / relative_path
    if not path.is_file():
        raise FileNotFoundError(
            f"missing config file {path}; copy {path.with_suffix('.example.json')} "
            f"or run nhub install"
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{path} is not valid JSON: {error}") from error
    return strip_comments(data)


def write_config(relative_path: str, data: dict[str, Any]) -> None:
    """Write one JSON file under ``config/`` atomically.

    The write goes to a temporary file in the same directory and is then
    renamed, so a crash mid-write cannot leave a truncated config behind.

    Args:
        relative_path: Path below ``config/``, for example ``xray/nodes.json``.
        data: The object to serialize.
    """
    path = UTILS_CONFIG_DIR / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    _write_atomic(path, text, mode=0o600)


def write_generated(path: Path, text: str, *, mode: int = 0o644) -> None:
    """Write a rendered artifact outside the repo, atomically.

    Args:
        path: Absolute destination, normally under ``/etc/neutrino/generated/``.
        text: The rendered file contents.
        mode: Permission bits for the result.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_atomic(path, text, mode=mode)


def strip_comments(data: Any) -> Any:
    """Remove ``_comment`` documentation keys from parsed config data.

    Args:
        data: Any parsed JSON value.

    Returns:
        The same structure with every underscore-prefixed mapping key removed.
    """
    if isinstance(data, dict):
        return {
            key: strip_comments(value)
            for key, value in data.items()
            if not key.startswith("_")
        }
    if isinstance(data, list):
        return [strip_comments(item) for item in data]
    return data


def _write_atomic(path: Path, text: str, *, mode: int) -> None:
    handle, temporary_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.chmod(temporary_name, mode)
        os.replace(temporary_name, path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise
