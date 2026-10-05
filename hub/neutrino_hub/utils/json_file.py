"""Reading and writing the JSON files under ``config/``.

``config/`` is the single source of truth for the appliance, so every read goes
through here: keys beginning with an underscore are documentation comments in
the example files and are stripped before the data reaches any library, and
so is an example's placeholder id in a list.
"""

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from neutrino_hub.utils.constants import (
    UTILS_CONFIG_DIR,
    UTILS_EXAMPLE_RECORD_PREFIX,
)

# The one lock every config mutation takes: a read-modify-write re-reads its
# file inside it, and an operation spanning two files (a provider and its
# vault object, a device and its key) nests under the same re-entrant lock
# and becomes one step. Global rather than per file, because references
# cross files and a narrower lock would let a composite interleave.
CONFIG_WRITE_LOCK = threading.RLock()

# What to call after each write, installed by whoever wants to hear. Nothing
# here reaches for the web layer; the panel's runtime sets this on startup.
_config_write_hook = None


def set_config_write_hook(hook) -> None:
    """Install what to call after each ``config/`` write.

    Args:
        hook: Called with the relative path just written. None installs
            nothing.
    """
    global _config_write_hook
    _config_write_hook = hook


def read_config(relative_path: str) -> dict[str, Any]:
    """Read one JSON file from ``config/``.

    Args:
        relative_path: Path below ``config/``, for example ``xray/nodes.json``.

    Returns:
        The parsed object with comment keys removed.

    Raises:
        FileNotFoundError: If the file does not exist. `nhub setup` copies the
            matching example out of the package on first run, so a miss here
            means setup was skipped.
        ValueError: If the file is not valid JSON.
    """
    path = UTILS_CONFIG_DIR / relative_path
    if not path.is_file():
        raise FileNotFoundError(f"missing config file {path}; run nhub setup")
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
    if _config_write_hook is not None:
        _config_write_hook(relative_path)


def copy_example(example_path: Path, real_path: Path) -> None:
    """Write a real config file from its example, without the example's records.

    Args:
        example_path: The committed ``*.example.json``.
        real_path: The file written, root-only.

    Raises:
        OSError: If the example cannot be read or the file written.
        ValueError: If the example is not valid JSON.
    """
    data = json.loads(example_path.read_text(encoding="utf-8"))
    real_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(_without_example_records(data), indent=2, ensure_ascii=False)
    _write_atomic(real_path, text + "\n", mode=0o600)


def write_generated(path: Path, text: str, *, mode: int = 0o644) -> None:
    """Write a rendered artifact outside the repo, atomically.

    Args:
        path: Absolute destination, normally under ``/var/lib/neutrino/hub/generated/``.
        text: The rendered file contents.
        mode: Permission bits for the result.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_atomic(path, text, mode=mode)


def rewrite_generated(path: Path, text: str, *, mode: int = 0o600) -> None:
    """Write new contents into an existing rendered file, keeping the file itself.

    A program that watches the file by its inode sees a write, where a
    replace would leave it watching the old file.

    Args:
        path: The file, which exists.
        text: The new contents.
        mode: Permission bits for the result.

    Raises:
        OSError: If the file cannot be opened or written.
    """
    with path.open("r+", encoding="utf-8") as stream:
        stream.truncate(0)
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(path, mode)


def strip_comments(data: Any) -> Any:
    """Remove ``_comment`` documentation keys from parsed config data.

    Args:
        data: Any parsed JSON value.

    Returns:
        The same structure with every underscore-prefixed mapping key removed,
        and every list item that is an example's placeholder id.
    """
    if isinstance(data, dict):
        return {
            key: strip_comments(value)
            for key, value in data.items()
            if not key.startswith("_")
        }
    if isinstance(data, list):
        return [strip_comments(item) for item in data if not _is_example_id(item)]
    return data


def _without_example_records(data: Any) -> Any:
    """The data with every placeholder record and id removed, comments kept."""
    if isinstance(data, dict):
        return {
            key: _without_example_records(value)
            for key, value in data.items()
            if not key.startswith(UTILS_EXAMPLE_RECORD_PREFIX)
        }
    if isinstance(data, list):
        return [
            _without_example_records(item) for item in data if not _is_example_id(item)
        ]
    return data


def _is_example_id(value: Any) -> bool:
    """Whether a list item is an example's placeholder id."""
    return isinstance(value, str) and value.startswith(UTILS_EXAMPLE_RECORD_PREFIX)


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
